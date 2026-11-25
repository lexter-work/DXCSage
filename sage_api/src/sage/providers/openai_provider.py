"""GPT via Chat Completions with tools. Network path not run in this repo's tests (needs an API key)."""
import json

from openai import AsyncOpenAI

from sage.providers.base import Done, Provider, TextDelta, ToolSpec, ToolUse


def to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
    out = [{"role": "system", "content": system}]
    for m in messages:
        blocks = m["content"]
        if m["role"] == "user":
            for b in blocks:
                if b["type"] == "tool_result":
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
            text = "".join(b["text"] for b in blocks if b["type"] == "text")
            if text:
                out.append({"role": "user", "content": text})
        else:
            msg = {"role": "assistant", "content": "".join(b["text"] for b in blocks if b["type"] == "text") or None}
            calls = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                     for b in blocks if b["type"] == "tool_use"]
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
    return out


def accumulate_tool_calls(deltas: list[dict]) -> list[ToolUse]:
    acc: dict[int, dict] = {}
    for d in deltas:
        slot = acc.setdefault(d["index"], {"id": "", "name": "", "args": ""})
        slot["id"] = d.get("id") or slot["id"]
        slot["name"] = d.get("name") or slot["name"]
        slot["args"] += d.get("arguments") or ""
    return [ToolUse(id=s["id"], name=s["name"], input=json.loads(s["args"] or "{}")) for _, s in sorted(acc.items())]


class OpenAIProvider(Provider):
    name = "openai"

    async def stream(self, *, model, system, messages, tools: list[ToolSpec], api_key, max_tokens):
        client = AsyncOpenAI(api_key=api_key)
        kwargs = {"model": model, "messages": to_openai_messages(system, messages), "stream": True,
                  "stream_options": {"include_usage": True}}
        if tools:
            kwargs["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.schema}}
                               for t in tools]
        deltas, usage = [], None
        async for chunk in await client.chat.completions.create(**kwargs):
            if chunk.usage:
                usage = chunk.usage
            for choice in chunk.choices:
                if choice.delta.content:
                    yield TextDelta(choice.delta.content)
                for tc in choice.delta.tool_calls or []:
                    deltas.append({"index": tc.index, "id": tc.id, "name": tc.function.name if tc.function else None,
                                   "arguments": tc.function.arguments if tc.function else None})
        for use in accumulate_tool_calls(deltas):
            yield use
        yield Done(usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0)

    EXCLUDE = ("audio", "realtime", "transcribe", "tts", "image", "search-api", "codex", "live", "whisper", "healthcare")

    async def list_models(self, api_key: str) -> list[str]:
        client = AsyncOpenAI(api_key=api_key)
        page = await client.models.list()
        return sorted(m.id for m in page.data
                      if m.id.startswith("gpt") and not any(x in m.id for x in self.EXCLUDE))
