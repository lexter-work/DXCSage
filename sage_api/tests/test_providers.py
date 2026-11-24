from sage.providers.openai_provider import accumulate_tool_calls, to_openai_messages

NEUTRAL = [
    {"role": "user", "content": [{"type": "text", "text": "check TS3"}]},
    {"role": "assistant", "content": [{"type": "text", "text": "ok"},
                                      {"type": "tool_use", "id": "c1", "name": "wf", "input": {"system_name": "TS3"}}]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "{\"a\":1}", "is_error": False}]},
]


def test_neutral_to_openai():
    out = to_openai_messages("sys", NEUTRAL)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[1] == {"role": "user", "content": "check TS3"}
    a = out[2]
    assert a["role"] == "assistant" and a["content"] == "ok"
    assert a["tool_calls"][0] == {"id": "c1", "type": "function", "function": {"name": "wf", "arguments": "{\"system_name\": \"TS3\"}"}}
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": "{\"a\":1}"}


def test_accumulate_streamed_tool_call_arguments():
    deltas = [
        {"index": 0, "id": "c1", "name": "wf", "arguments": "{\"system"},
        {"index": 0, "id": None, "name": None, "arguments": "_name\": \"TS3\"}"},
        {"index": 1, "id": "c2", "name": "other", "arguments": "{}"},
    ]
    uses = accumulate_tool_calls(deltas)
    assert [(u.id, u.name, u.input) for u in uses] == [("c1", "wf", {"system_name": "TS3"}), ("c2", "other", {})]
