"""List the authorizations the RFC user needs for every installed workflow (or one). Built from the live workflow
registry, so a workflow added later is covered with no change here."""
from pydantic import BaseModel

from sage.runtime.errors import WorkflowFailed
from sage.tasks.sap_scan_auth import ScanAuth, ScanAuthIn
from sage.workflows.base import SystemInput, Workflow


class AuthReqInput(SystemInput):
    workflow: str | None = None     # empty = all installed workflows


class AuthValue(BaseModel):
    object: str
    field: str
    value: str
    source: str            # "declared" (S_RFC, S_TABU_NAM) or the scanned function module


class WorkflowAuth(BaseModel):
    workflow: str
    values: list[AuthValue]
    unresolved: list[str]
    errors: list[str]


class AuthReqOutput(BaseModel):
    system: str
    workflows: list[WorkflowAuth]


class SapAuthRequirements(Workflow):
    name = "sap_auth_requirements"
    description = ("List every SAP authorization object and value the RFC user needs on a registered system, for all installed "
                   "workflow tools or one of them, so they can be requested from the security team in one go. "
                   "Read-only. Does not compare with the user's current authorizations (the health check does that).")
    Input, Output = AuthReqInput, AuthReqOutput
    tasks = (ScanAuth,)

    async def run(self, ctx, data: AuthReqInput) -> AuthReqOutput:
        tc = ctx.task_ctx
        names = await tc.rfc.names(tc.system_id)

        async def targets():
            wfs = tc.workflows or {}
            if data.workflow and data.workflow not in wfs:
                raise WorkflowFailed(f"Unknown workflow '{data.workflow}'. Installed: {', '.join(sorted(wfs))}.")
            out = {}
            for n, cls in sorted(wfs.items()):
                if data.workflow and n != data.workflow:
                    continue
                reqs = cls.requirements()
                out[n] = {"declared": [list(r) for q in reqs for r in q.auth_rows(names)],
                          "fms": [q.key for q in reqs if q.kind == "fm_exists"]}
            return out

        plan = await ctx.snapshot("targets", targets)         # fixed for the run, so replays see the same workflow list
        scans = {}
        for fm in sorted({f for t in plan.values() for f in t["fms"]}):       # each function module is scanned once
            scans[fm] = await ctx.task(ScanAuth, ScanAuthIn(function_module=fm))

        result = []
        for n, t in plan.items():
            seen, values, unres, errs = set(), [], [], []
            for o, f, v in t["declared"]:
                if (o, f, v) not in seen:
                    seen.add((o, f, v))
                    values.append(AuthValue(object=o, field=f, value=v, source="declared"))
            for fm in t["fms"]:
                s = scans[fm]
                for r in s.rows:
                    if (r.auth_object, r.auth_field, r.auth_values) not in seen:
                        seen.add((r.auth_object, r.auth_field, r.auth_values))
                        values.append(AuthValue(object=r.auth_object, field=r.auth_field, value=r.auth_values, source=names.get(fm, fm)))
                unres += [f"{names.get(fm, fm)}: {u}" for u in s.unresolved]
                if s.error:
                    errs.append(f"{names.get(fm, fm)}: {s.error}")
            values.sort(key=lambda a: (a.object, a.field, a.value))
            result.append(WorkflowAuth(workflow=n, values=values, unresolved=unres, errors=errs))
        return AuthReqOutput(system=tc.system_label, workflows=result)
