"""Thinking envelope round trip on the Responses path (ADR 0093), through the gateway's public interface."""

import json

import httpx
import pytest

from src.infrastructure.config import ProviderSettings
from src.infrastructure.gateways.anthropic_gateway import AnthropicGateway

MODEL = "claude-opus-5-5"


def _sse(*events: dict) -> bytes:
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)


def _reply(blocks: list[dict], *, msg_id: str = "msg_01", model: str = MODEL, stop: str = "end_turn", start_extra=None) -> bytes:
    """A fake Anthropic stream that produces exactly ``blocks`` as the message content."""
    message = {"id": msg_id, "type": "message", "role": "assistant", "model": model, "content": [], "usage": {"input_tokens": 9}}
    message.update(start_extra or {})
    events: list[dict] = [{"type": "message_start", "message": message}]
    for index, block in enumerate(blocks):
        kind = block["type"]
        if kind == "thinking":
            events.append({"type": "content_block_start", "index": index, "content_block": {"type": "thinking", "thinking": "", "signature": ""}})
            text = block["thinking"]
            events.append({"type": "content_block_delta", "index": index, "delta": {"type": "thinking_delta", "thinking": text[:3]}})
            events.append({"type": "content_block_delta", "index": index, "delta": {"type": "thinking_delta", "thinking": text[3:]}})
            events.append({"type": "content_block_delta", "index": index, "delta": {"type": "signature_delta", "signature": block["signature"]}})
        elif kind == "text":
            events.append({"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}})
            events.append({"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": block["text"]}})
        elif kind == "tool_use":
            events.append(
                {"type": "content_block_start", "index": index, "content_block": {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}}
            )
            events.append(
                {"type": "content_block_delta", "index": index, "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}}
            )
        events.append({"type": "content_block_stop", "index": index})
    events.append({"type": "message_delta", "delta": {"stop_reason": stop}, "usage": {"output_tokens": 5}})
    events.append({"type": "message_stop"})
    return _sse(*events)


class _FakeAnthropic:
    """Answers each Messages request with the next queued stream."""

    def __init__(self, *bodies: bytes):
        self.bodies = list(bodies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = self.bodies.pop(0) if self.bodies else _reply([{"type": "text", "text": "ok"}])
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    @property
    def sent(self) -> dict:
        return json.loads(self.requests[-1].content)


def _gateway(monkeypatch, fake) -> AnthropicGateway:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-a")
    monkeypatch.delenv("ANTHROPIC_API_KEY_2", raising=False)
    return AnthropicGateway(
        ProviderSettings(
            name="anthropic",
            type="anthropic",
            base_url="https://api.anthropic.com/v1",
            api_key_envs=("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_2"),
            max_concurrent_per_key=10,
        ),
        timeout=5.0,
        transport=httpx.MockTransport(fake),
    )


@pytest.mark.asyncio
async def test_every_request_asks_anthropic_to_drop_invalid_thinking_under_the_beta_header(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    await gateway.responses_create({"model": MODEL, "input": "hi"})
    [_ async for _ in gateway.responses_create_stream({"model": MODEL, "input": "hi", "stream": True})]

    for request in fake.requests:
        body = json.loads(request.content)
        assert request.headers["anthropic-beta"] == "thinking-binding-controls-2026-08-01"
        assert body["thinking"]["block_binding"] == {"prefix_mismatch_behavior": "drop_block"}


@pytest.mark.asyncio
async def test_each_input_transformation_anthropic_reports_is_logged_with_its_reason(monkeypatch, caplog):
    dropped = {"type": "thinking_block_dropped", "message_index": 1, "content_index": 0, "reason": "prefix_mismatch"}
    late = {"type": "thinking_block_dropped", "message_index": 3, "content_index": 0, "reason": "model_mismatch"}
    body = _reply([{"type": "text", "text": "ok"}], start_extra={"input_transformations": [dropped]})
    # After a server-side fallback the final message_delta carries the array again.
    body = body.replace(
        b'"delta": {"stop_reason": "end_turn"}',
        b'"delta": {"stop_reason": "end_turn"}, "input_transformations": ' + json.dumps([late]).encode(),
    )
    fake = _FakeAnthropic(body)
    gateway = _gateway(monkeypatch, fake)
    caplog.set_level("INFO", logger="src.infrastructure.gateways.anthropic_gateway")

    reply = await gateway.responses_create({"model": MODEL, "input": "hi"})

    assert reply["status"] == "completed"
    logged = [r.getMessage() for r in caplog.records if "anthropic_input_transformation" in r.getMessage()]
    assert len(logged) == 2
    assert "reason=prefix_mismatch" in logged[0]
    assert "reason=model_mismatch" in logged[1]
    assert f"model={MODEL}" in logged[0]


def _as_copilot_echoes(reply: dict) -> list[dict]:
    """Turn a Responses reply into the history items Copilot sends back on the next turn.

    Copilot keeps a reasoning item only with ``encrypted_content``, sends its summary back empty,
    and trims trailing whitespace from the assistant text.
    """
    items: list[dict] = []
    for item in reply["output"]:
        if item["type"] == "reasoning":
            if item.get("encrypted_content"):
                items.append({"type": "reasoning", "id": item["id"], "summary": [], "encrypted_content": item["encrypted_content"]})
        elif item["type"] == "message":
            text = "".join(part["text"] for part in item["content"]).rstrip()
            items.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]})
        elif item["type"] == "function_call":
            items.append({k: item[k] for k in ("type", "id", "call_id", "name", "arguments")})
    return items


def _user(text: str) -> dict:
    return {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}


def _thought(n: int) -> list[dict]:
    return [
        {"type": "thinking", "thinking": f"Thinking about round {n}.", "signature": f"sig-{n}"},
        {"type": "text", "text": f"Answer {n}.  \n\n"},
    ]


@pytest.mark.asyncio
async def test_the_next_turn_replays_the_prior_assistant_turn_byte_for_byte(monkeypatch):
    blocks = _thought(1)
    fake = _FakeAnthropic(_reply(blocks))
    gateway = _gateway(monkeypatch, fake)
    first = await gateway.responses_create({"model": MODEL, "input": [_user("q1")]})

    reasoning = first["output"][0]
    assert reasoning["type"] == "reasoning" and reasoning["id"].startswith("rs_")
    assert reasoning["summary"] == [{"type": "summary_text", "text": "Thinking about round 1."}]
    assert reasoning["encrypted_content"]

    await gateway.responses_create({"model": MODEL, "input": [_user("q1"), *_as_copilot_echoes(first), _user("q2")]})

    sent = fake.sent["messages"]
    assert sent[1] == {"role": "assistant", "content": blocks}
    assert json.dumps(sent[1]["content"]) == json.dumps(blocks)
    assert sent[2] == {"role": "user", "content": "q2"}


_READ_FILE = {"type": "function", "name": "read_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}


def _tool_round(n: int) -> list[dict]:
    return [
        {"type": "thinking", "thinking": f"I need file {n}.", "signature": f"sig-tool-{n}"},
        {"type": "text", "text": f"Reading {n}. "},
        {"type": "tool_use", "id": f"toolu_{n}", "name": "read_file", "input": {"path": f"{n}.py"}},
    ]


async def _agent_loop(gateway, fake, rounds: list[list[dict]]) -> tuple[list[dict], list[dict]]:
    """Run one user turn through ``rounds`` tool-calling replies, Copilot-style, and return the
    history Copilot would hold afterwards plus each round's echoed items."""
    history = [_user("fix it")]
    echoed: list[list[dict]] = []
    for n, blocks in enumerate(rounds):
        fake.bodies.append(_reply(blocks, msg_id=f"msg_r{n}"))
        reply = await gateway.responses_create({"model": MODEL, "input": history, "tools": [_READ_FILE]})
        items = _as_copilot_echoes(reply)
        echoed.append(items)
        history = history + items
        for block in blocks:
            if block["type"] == "tool_use":
                history.append({"type": "function_call_output", "call_id": block["id"], "output": "data"})
    return history, echoed


def _assistant_turns(sent: dict) -> list[list[dict]]:
    return [m["content"] for m in sent["messages"] if m["role"] == "assistant"]


@pytest.mark.asyncio
async def test_a_multi_round_history_replays_every_rounds_thinking(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)
    rounds = [_tool_round(1), _tool_round(2), _tool_round(3)]
    history, _ = await _agent_loop(gateway, fake, rounds)

    await gateway.responses_create({"model": MODEL, "input": history, "tools": [_READ_FILE]})

    assert _assistant_turns(fake.sent) == rounds
    tool_results = [m["content"][0]["tool_use_id"] for m in fake.sent["messages"] if m["role"] == "user" and isinstance(m["content"], list)]
    assert tool_results == ["toolu_1", "toolu_2", "toolu_3"]


def _without_thinking(blocks: list[dict]) -> list[dict]:
    kept = [dict(b) for b in blocks if b["type"] != "thinking"]
    for block in kept:
        if block["type"] == "text":
            block["text"] = block["text"].rstrip()  # Copilot's trimmed copy
    return kept


def _strip_envelope(items: list[dict]) -> list[dict]:
    return [item for item in items if item["type"] != "reasoning"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("missing", "expected_with_thinking"),
    [
        (0, [False, True, True]),  # front: only that round loses thinking
        (1, [False, False, True]),  # middle: it and every earlier round lose thinking
        (2, [False, False, False]),  # newest: no round keeps thinking
    ],
)
async def test_thinking_is_kept_only_for_the_trailing_run_of_rounds_with_an_envelope(
    monkeypatch, missing, expected_with_thinking
):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)
    rounds = [_tool_round(1), _tool_round(2), _tool_round(3)]
    history, echoed = await _agent_loop(gateway, fake, rounds)
    target = echoed[missing]
    start = next(i for i in range(len(history)) if history[i : i + len(target)] == target)
    history = history[:start] + _strip_envelope(target) + history[start + len(target) :]

    reply = await gateway.responses_create({"model": MODEL, "input": history, "tools": [_READ_FILE]})

    assert reply["status"] == "completed"
    expected = [blocks if keep else _without_thinking(blocks) for blocks, keep in zip(rounds, expected_with_thinking)]
    assert _assistant_turns(fake.sent) == expected


def _replace_envelope(items: list[dict], envelope) -> list[dict]:
    return [{**item, "encrypted_content": envelope} if item["type"] == "reasoning" else item for item in items]


def _envelope_of(document) -> str:
    import base64

    raw = document if isinstance(document, bytes) else json.dumps(document).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_envelope",
    [
        "not base64 at all!!",
        "gAAAAABfakeOpenAIEncryptedReasoning==",
        _envelope_of(b"{not json"),
        _envelope_of({"v": 1, "model": MODEL, "content": [{"type": "server_tool_use", "id": "x", "name": "web", "input": {}}]}),
        _envelope_of({"v": 1, "model": MODEL, "content": [{"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}]}),
        _envelope_of({"v": 1, "model": MODEL, "content": [{"type": "thinking", "thinking": "x"}]}),
        _envelope_of({"v": 1, "model": "claude-sonnet-5-5", "content": [{"type": "text", "text": "Answer 1.  \n\n"}]}),
        _envelope_of({"v": 99, "model": MODEL, "content": [{"type": "text", "text": "Answer 1.  \n\n"}]}),
        12345,
    ],
    ids=["garbage", "foreign", "not-json", "unknown-block", "extra-field", "unsigned-thinking", "other-model", "future-version", "not-a-string"],
)
async def test_a_malformed_foreign_or_other_model_envelope_counts_as_missing(monkeypatch, bad_envelope):
    blocks = _thought(1)
    fake = _FakeAnthropic(_reply(blocks))
    gateway = _gateway(monkeypatch, fake)
    first = await gateway.responses_create({"model": MODEL, "input": [_user("q1")]})
    echoed = _replace_envelope(_as_copilot_echoes(first), bad_envelope)

    reply = await gateway.responses_create({"model": MODEL, "input": [_user("q1"), *echoed, _user("q2")]})

    assert reply["status"] == "completed"
    assert fake.sent["messages"] == [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "Answer 1."},
        {"role": "user", "content": "q2"},
    ]


@pytest.mark.asyncio
async def test_an_envelope_from_a_different_model_is_not_replayed_to_this_one(monkeypatch):
    blocks = _thought(1)
    fake = _FakeAnthropic(_reply(blocks))
    gateway = _gateway(monkeypatch, fake)
    first = await gateway.responses_create({"model": "claude-sonnet-5-5", "input": [_user("q1")]})

    await gateway.responses_create({"model": MODEL, "input": [_user("q1"), *_as_copilot_echoes(first), _user("q2")]})

    assert _assistant_turns(fake.sent) == ["Answer 1."]


@pytest.mark.asyncio
async def test_rewritten_tool_call_ids_are_mapped_back_to_the_originals_by_position(monkeypatch):
    blocks = [
        {"type": "thinking", "thinking": "Read both.", "signature": "sig-both"},
        {"type": "tool_use", "id": "toolu_A", "name": "read_file", "input": {"path": "a.py"}},
        {"type": "tool_use", "id": "toolu_B", "name": "read_file", "input": {"path": "b.py"}},
    ]
    fake = _FakeAnthropic(_reply(blocks, stop="tool_use"))
    gateway = _gateway(monkeypatch, fake)
    first = await gateway.responses_create({"model": MODEL, "input": [_user("q")], "tools": [_READ_FILE]})
    echoed = _as_copilot_echoes(first)
    renamed = {"toolu_A": "call_copilot_1", "toolu_B": "call_copilot_2"}
    for item in echoed:
        if item["type"] == "function_call":
            item["call_id"] = renamed[item["call_id"]]
    outputs = [{"type": "function_call_output", "call_id": new, "output": old} for old, new in renamed.items()]

    await gateway.responses_create({"model": MODEL, "input": [_user("q"), *echoed, *outputs], "tools": [_READ_FILE]})

    assert fake.sent["messages"][1] == {"role": "assistant", "content": blocks}
    assert fake.sent["messages"][2]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_A", "content": "toolu_A"},
        {"type": "tool_result", "tool_use_id": "toolu_B", "content": "toolu_B"},
    ]


@pytest.mark.asyncio
async def test_a_streamed_reply_carries_the_same_envelope_as_the_non_streamed_one(monkeypatch):
    blocks = _thought(1)
    fake = _FakeAnthropic(_reply(blocks), _reply(blocks))
    gateway = _gateway(monkeypatch, fake)
    body = {"model": MODEL, "input": [_user("q1")]}

    raw = b"".join([chunk async for chunk in gateway.responses_create_stream({**body, "stream": True})])
    events = [json.loads(frame.split("\n")[1].removeprefix("data: ")) for frame in raw.decode().split("\n\n") if frame.strip()]
    non_stream = await gateway.responses_create(body)

    added = [e for e in events if e["type"] == "response.output_item.added"]
    assert added[0]["output_index"] == 0 and added[0]["item"]["type"] == "reasoning"
    (reasoning_done,) = [e["item"] for e in events if e["type"] == "response.output_item.done" and e["item"]["type"] == "reasoning"]
    assert reasoning_done["encrypted_content"] == non_stream["output"][0]["encrypted_content"]
    completed = events[-1]["response"]

    await gateway.responses_create({"model": MODEL, "input": [_user("q1"), *_as_copilot_echoes(completed), _user("q2")]})

    assert fake.sent["messages"][1] == {"role": "assistant", "content": blocks}
