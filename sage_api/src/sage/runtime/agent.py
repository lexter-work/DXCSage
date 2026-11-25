"""Agent loop. Messages and tool calls are stored, so a run can be rebuilt after a restart.
A durable workflow that is waiting leaves the run in status 'waiting' with resume_at; the scheduler resumes it."""
import asyncio
import json
import logging

from pydantic import ValidationError

from sage.providers.base import Done, TextDelta, ToolSpec, ToolUse
from sage.runtime.context import WorkflowContext
from sage.runtime.errors import RunCancelled, WorkflowFailed, WorkflowSuspended
from sage.tasks.base import TaskContext
from sage.util import iso, utcnow
from sage.workflow_setup import AccessError

log = logging.getLogger("sage.agent")

SYSTEM_PROMPT = ("You are DXC Sage, an assistant for SAP work. Use the provided workflow tools when they fit. "
                 "A workflow can run for hours; its result arrives when it finishes. Never invent results.")


class AgentService:
    def __init__(self, *, db, audit, settings, providers, workflows, setup, rfc, data_dir, usage, ssh=None, email=None, clock=utcnow, poll_seconds=5):
        self._db, self._audit, self._settings, self._providers = db, audit, settings, providers
        self._workflows, self._setup, self._rfc, self._data_dir, self._usage = workflows, setup, rfc, data_dir, usage
        self._clock, self._poll, self._ssh, self._email = clock, poll_seconds, ssh, email
        self._tasks: dict[int, asyncio.Task] = {}
        self._scheduler: asyncio.Task | None = None

    # ---- runs ----
    async def _run(self, run_id):
        return await self._db.fetchone("SELECT * FROM runs WHERE id=?", (run_id,))

    async def _emit(self, run_id, type_, data=None):
        await self._db.execute("INSERT INTO run_events(run_id,type,data,created_at) VALUES(?,?,?,?)",
                               (run_id, type_, json.dumps(data or {}, default=str), iso(self._clock())))

    async def create_run(self, chat_id, user, text) -> int:
        chat = await self._db.fetchone("SELECT * FROM chats WHERE id=? AND user_id=? AND deleted_at IS NULL", (chat_id, user["id"]))
        if not chat:
            raise LookupError("chat")
        if await self._db.fetchone("SELECT id FROM runs WHERE chat_id=? AND status IN ('running','waiting')", (chat_id,)):
            raise RuntimeError("This chat already has an active run.")
        now = iso(self._clock())
        async with self._db.tx() as t:
            run_id = await t.execute("INSERT INTO runs(chat_id,user_id,provider,model,status,started_at) VALUES(?,?,?,?,'running',?)",
                                     (chat_id, user["id"], chat["provider"], chat["model"], now))
            await t.execute("INSERT INTO messages(chat_id,run_id,role,content,created_at) VALUES(?,?,'user',?,?)",
                            (chat_id, run_id, json.dumps([{"type": "text", "text": text}]), now))
        await self._audit.write("run.start", user["username"], run_id, {"chat_id": chat_id, "provider": chat["provider"], "model": chat["model"]})
        return run_id

    def launch(self, run_id):
        if run_id in self._tasks:
            return
        task = asyncio.create_task(self.drive(run_id))
        self._tasks[run_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(run_id, None))

    async def drive(self, run_id):
        run = await self._run(run_id)
        if run["status"] not in ("running", "waiting"):
            return
        await self._db.execute("UPDATE runs SET status='running', resume_at=NULL WHERE id=?", (run_id,))
        try:
            await self._loop(run_id)
        except WorkflowSuspended:
            return
        except RunCancelled:
            await self._finish(run_id, "cancelled")
        except Exception as e:  # noqa: BLE001
            log.exception("run %s failed", run_id)
            await self._finish(run_id, "failed", str(e))

    async def _finish(self, run_id, status, error=None):
        await self._db.execute("UPDATE runs SET status=?, error=?, ended_at=?, resume_at=NULL WHERE id=?",
                               (status, error, iso(self._clock()), run_id))
        run = await self._run(run_id)
        await self._usage.record_run(run_id)
        await self._audit.write("run.end", "system", run_id, {"status": status, "error": error,
                                                              "tokens_in": run["tokens_in"], "tokens_out": run["tokens_out"]})
        await self._emit(run_id, {"done": "done", "failed": "error", "cancelled": "cancelled"}[status], {"error": error})

    async def cancel(self, run_id, actor):
        run = await self._run(run_id)
        await self._db.execute("UPDATE runs SET cancel_requested=1 WHERE id=?", (run_id,))
        await self._audit.write("run.cancel", actor, run_id)
        if run["status"] == "waiting" and run_id not in self._tasks:
            await self._db.execute("UPDATE tool_calls SET status='cancelled', ended_at=? WHERE run_id=? AND status IN ('waiting','running')",
                                   (iso(self._clock()), run_id))
            await self._finish(run_id, "cancelled")

    async def _check_cancel(self, run_id):
        if (await self._run(run_id))["cancel_requested"]:
            raise RunCancelled()

    # ---- loop ----
    async def _history(self, chat_id):
        rows = await self._db.fetchall("SELECT role,content FROM messages WHERE chat_id=? ORDER BY id", (chat_id,))
        return [{"role": r["role"], "content": json.loads(r["content"])} for r in rows]

    async def _add_message(self, run, role, blocks):
        await self._db.execute("INSERT INTO messages(chat_id,run_id,role,content,created_at) VALUES(?,?,?,?,?)",
                               (run["chat_id"], run["id"], role, json.dumps(blocks), iso(self._clock())))

    async def tool_specs(self) -> list[ToolSpec]:
        disabled = await self._settings.get("workflows.disabled")
        specs = []
        for name, cls in self._workflows.items():
            if name in disabled:
                continue
            systems = await self._setup.enabled_systems(name)
            if not systems:
                continue
            schema = cls.Input.model_json_schema()
            if "system_name" in schema.get("properties", {}):
                schema["properties"]["system_name"]["enum"] = [s["label"] for s in systems]
            specs.append(ToolSpec(name=name, description=cls.description, schema=schema))
        return specs

    async def _loop(self, run_id):
        run = await self._run(run_id)
        user = await self._db.fetchone("SELECT * FROM users WHERE id=?", (run["user_id"],))
        provider = self._providers[run["provider"]]
        api_key = await self._settings.get(f"providers.{run['provider']}_api_key")
        if not api_key:
            raise WorkflowFailed(f"No API key is set for {run['provider']}.")
        max_turns = int(await self._settings.get("agent.max_turns"))
        turns = 0
        while True:
            await self._check_cancel(run_id)
            history = await self._history(run["chat_id"])
            last = history[-1]
            pending = [b for b in last["content"] if b["type"] == "tool_use"] if last["role"] == "assistant" else []
            if pending:
                results = await self._run_tools(run_id, user, pending)
                await self._add_message(run, "user", results)
                continue
            if last["role"] == "assistant":
                return await self._finish(run_id, "done")
            if turns >= max_turns:
                return await self._finish(run_id, "failed", "max_turns reached")
            turns += 1
            blocks = await self._ask(run_id, run, provider, api_key, history)
            await self._add_message(run, "assistant", blocks)

    async def _ask(self, run_id, run, provider, api_key, history):
        tools = await self.tool_specs()
        text, uses, tin, tout = "", [], 0, 0
        max_tokens = int(await self._settings.get("providers.max_tokens"))
        async for ev in provider.stream(model=run["model"], system=SYSTEM_PROMPT, messages=history, tools=tools,
                                        api_key=api_key, max_tokens=max_tokens):
            if isinstance(ev, TextDelta):
                text += ev.text
                await self._emit(run_id, "text", {"text": ev.text})
            elif isinstance(ev, ToolUse):
                uses.append(ev)
            elif isinstance(ev, Done):
                tin, tout = ev.input_tokens, ev.output_tokens
        await self._db.execute("UPDATE runs SET tokens_in=tokens_in+?, tokens_out=tokens_out+? WHERE id=?", (tin, tout, run_id))
        blocks = ([{"type": "text", "text": text}] if text else []) + \
                 [{"type": "tool_use", "id": u.id, "name": u.name, "input": u.input} for u in uses]
        return blocks or [{"type": "text", "text": "(no output)"}]

    async def _run_tools(self, run_id, user, uses):
        results = []
        for use in uses:
            existing = await self._db.fetchone("SELECT * FROM tool_calls WHERE run_id=? AND provider_call_id=?", (run_id, use["id"]))
            if existing and existing["status"] in ("ok", "error"):
                results.append({"type": "tool_result", "tool_use_id": use["id"], "content": existing["output"] or "",
                                "is_error": existing["status"] == "error"})
            else:
                results.append(await self._execute(run_id, user, use, existing))
        return results

    def _mail(self, workflow, event, call_id, run_id, system, actor, detail=""):
        if self._email:
            self._email.notify(workflow=workflow, event=event, tool_call_id=call_id, run_id=run_id, system=system, actor=actor, detail=detail)

    async def _execute(self, run_id, user, use, existing):
        name, actor = use["name"], user["username"]
        if existing:
            call_id = existing["id"]
        else:
            call_id = await self._db.execute(
                "INSERT INTO tool_calls(run_id,provider_call_id,workflow,input,status,started_at) VALUES(?,?,?,?,'running',?)",
                (run_id, use["id"], name, json.dumps(use["input"]), iso(self._clock())))
            await self._audit.write("tool.call", actor, run_id, {"workflow": name, "input": use["input"]})
            await self._emit(run_id, "tool_start", {"workflow": name, "input": use["input"]})
        status, output, label = "ok", "", ""
        started = not existing
        try:
            cls = self._workflows.get(name)
            if cls is None:
                raise WorkflowFailed(f"Unknown workflow '{name}'.")
            data = cls.Input.model_validate(use["input"])
            system, binding = None, {}
            if hasattr(data, "system_name"):
                system, binding = await self._setup.authorize_run(name, data.system_name, actor)
                await self._db.execute("UPDATE tool_calls SET system_id=? WHERE id=?", (system["id"], call_id))
                label = system["label"]
            if started:
                self._mail(name, "started", call_id, run_id, label, actor)
            backoff = await self._settings.get("wait.backoff")
            max_wait = int(await self._settings.get("wait.max_wait"))
            task_ctx = TaskContext(system["id"] if system else None, self._rfc, self._settings, binding, self._data_dir,
                                   system["label"] if system else "", self._ssh, sid=system["sid"] if system else "", workflows=self._workflows)

            async def cancelled():
                return bool((await self._run(run_id))["cancel_requested"])

            async def emit(t, d):
                await self._emit(run_id, t, d)

            ctx = WorkflowContext(db=self._db, audit=self._audit, run_id=run_id, tool_call_id=call_id, workflow=name, actor=actor,
                                  task_ctx=task_ctx, backoff=backoff, max_wait=max_wait, clock=self._clock,
                                  is_cancelled=cancelled, emit=emit)
            out = await cls().run(ctx, data)
            output = out.model_dump_json()
            if (state := cls.result_state(out)):
                self._mail(name, f"result:{state}", call_id, run_id, label, actor, getattr(out, "message", ""))
        except WorkflowSuspended as s:
            self._mail(name, "waiting", call_id, run_id, label, actor)
            await self._db.execute("UPDATE tool_calls SET status='waiting' WHERE id=?", (call_id,))
            await self._db.execute("UPDATE runs SET status='waiting', resume_at=? WHERE id=?", (iso(s.resume_at), run_id))
            await self._emit(run_id, "waiting", {"workflow": name, "resume_at": iso(s.resume_at)})
            raise
        except RunCancelled:
            await self._db.execute("UPDATE tool_calls SET status='cancelled', ended_at=? WHERE id=?", (iso(self._clock()), call_id))
            self._mail(name, "cancelled", call_id, run_id, label, actor)
            raise
        except (WorkflowFailed, AccessError) as e:
            status, output = "error", str(e)
        except ValidationError as e:
            status, output = "error", f"Invalid input: {e.errors(include_url=False)}"
        except Exception:  # noqa: BLE001
            log.exception("workflow %s crashed", name)
            status, output = "error", "Internal error while running the workflow."
        await self._db.execute("UPDATE tool_calls SET status=?, output=?, ended_at=? WHERE id=?",
                               (status, output, iso(self._clock()), call_id))
        await self._audit.write("tool.end", actor, run_id, {"workflow": name, "status": status})
        self._mail(name, "completed" if status == "ok" else "failed", call_id, run_id, label, actor, output if status != "ok" else "")
        await self._emit(run_id, "tool_end", {"workflow": name, "status": status})
        return {"type": "tool_result", "tool_use_id": use["id"], "content": output, "is_error": status != "ok"}

    # ---- restart and scheduling ----
    async def recover_on_startup(self):
        now = iso(self._clock())
        for r in await self._db.fetchall("SELECT id,status FROM runs WHERE status IN ('running','waiting')"):
            if r["id"] in self._tasks:
                continue
            call = await self._db.fetchone("SELECT workflow FROM tool_calls WHERE run_id=? AND status IN ('running','waiting')", (r["id"],))
            cls = self._workflows.get(call["workflow"]) if call else None
            if cls is not None and cls.durable:
                if r["status"] == "running":
                    await self._db.execute("UPDATE runs SET status='waiting', resume_at=? WHERE id=?", (now, r["id"]))
            elif r["status"] == "running":
                await self._db.execute("UPDATE tool_calls SET status='error', output='Interrupted by a server restart.' "
                                       "WHERE run_id=? AND status='running'", (r["id"],))
                await self._finish(r["id"], "failed", "Interrupted by a server restart.")

    async def _tick(self):
        now = iso(self._clock())
        for r in await self._db.fetchall("SELECT id FROM runs WHERE status='waiting' AND resume_at<=?", (now,)):
            self.launch(r["id"])

    def start_scheduler(self):
        async def loop():
            while True:
                try:
                    await self._tick()
                except Exception:  # noqa: BLE001
                    log.exception("scheduler tick failed")
                await asyncio.sleep(self._poll)
        self._scheduler = asyncio.create_task(loop())

    async def stop_scheduler(self):
        if self._scheduler:
            self._scheduler.cancel()
        for t in list(self._tasks.values()):
            t.cancel()
