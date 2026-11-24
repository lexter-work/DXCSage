"""Claude. The neutral message format is already Anthropic-shaped, so messages pass through.
Network path not run in this repo's tests (needs an API key)."""
import anthropic

from sage.providers.base import Done, Provider, TextDelta, ToolSpec, ToolUse


class AnthropicProvider(Provider):
    name = "anthropic"

    async def stream(self, *, model, system, messages, tools: list[ToolSpec], api_key, max_tokens):
        client = anthropic.AsyncAnthropic(api_key=api_key)
        kwargs = {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages}
        if tools:
            kwargs["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.schema} for t in tools]
        async with client.messages.stream(**kwargs) as s:
            async for text in s.text_stream:
                yield TextDelta(text)
            final = await s.get_final_message()
        for b in final.content:
            if b.type == "tool_use":
                yield ToolUse(id=b.id, name=b.name, input=dict(b.input))
        yield Done(final.usage.input_tokens, final.usage.output_tokens)
