"""Claude's thinking carried in client-held envelopes (ADR 0093).

Nothing here knows about Responses or chat. Each path turns its own history into a list of
``AssistantRound`` (the round's text and tool use as the client sent it back, plus the envelope the
client echoed, if any) and calls ``replay_assistant_rounds``; it puts ``encode_thinking_envelope``
of each reply's content wherever its client stores the envelope (Responses ``encrypted_content``,
chat ``reasoning_opaque``).

The envelope is an encoding, not encryption: base64url of a small JSON document holding a format
version, the producing model and the round's complete Anthropic content blocks. What comes back is
untrusted, so decoding accepts only known block types with exactly their expected fields. Anything
else counts as no envelope; it never fails the request.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from typing import Any

ENVELOPE_VERSION = 1

# Each known Anthropic content block type and its fields, other than "type", with their types.
_BLOCK_FIELDS: dict[str, dict[str, type]] = {
    "thinking": {"thinking": str, "signature": str},
    "redacted_thinking": {"data": str},
    "text": {"text": str},
    "tool_use": {"id": str, "name": str, "input": dict},
}
_THINKING_TYPES = frozenset({"thinking", "redacted_thinking"})


@dataclass
class AssistantRound:
    """One assistant reply as the client sent it back.

    ``blocks`` are the round's text and tool_use blocks built from the client's history; they are
    sent when the round cannot be rebuilt from its envelope. ``envelope`` is whatever the client
    echoed in the envelope field, or None.
    """

    blocks: list[dict[str, Any]] = field(default_factory=list)
    envelope: Any = None


@dataclass
class ReplayedRounds:
    """What to send for each round, in the order given, and the tool-use id repairs.

    ``tool_use_ids`` maps a tool-use id the client sent to the original id in the envelope, for
    rounds rebuilt from an envelope whose ids the client rewrote. Apply it to the ``tool_use_id``
    of the tool results that answer those calls.
    """

    content: list[list[dict[str, Any]]]
    tool_use_ids: dict[str, str]
    rebuilt: int = 0


def encode_thinking_envelope(content: list[dict[str, Any]], *, model: str) -> str | None:
    """The envelope for one assistant round's complete Anthropic content, or None when the round
    holds anything an envelope cannot carry (an unknown block, or thinking without a signature)."""
    blocks = _valid_blocks(content)
    if blocks is None or not model:
        return None
    document = {"v": ENVELOPE_VERSION, "model": model, "content": blocks}
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_thinking_envelope(envelope: Any, *, model: str) -> list[dict[str, Any]] | None:
    """The round's Anthropic content blocks from an envelope that this router made for ``model``;
    None for a missing, malformed, foreign or other-model envelope."""
    if not isinstance(envelope, str) or not envelope or not model:
        return None
    try:
        raw = base64.urlsafe_b64decode(envelope + "=" * (-len(envelope) % 4))
        document = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(document, dict) or set(document) != {"v", "model", "content"}:
        return None
    if document["v"] != ENVELOPE_VERSION or document["model"] != model:
        return None
    content = document["content"]
    if not isinstance(content, list):
        return None
    return _valid_blocks(content, exact=True)


def replay_assistant_rounds(rounds: list[AssistantRound], *, model: str) -> ReplayedRounds:
    """Walk the rounds from the newest back and keep thinking for the trailing run of rounds whose
    envelope decodes for ``model``; those rounds are rebuilt byte for byte from it. From the first
    round without one, that round and every earlier round go without thinking blocks and keep the
    text and tool calls the client sent. Thinking is only ever removed from the front of the chain.
    """
    content: list[list[dict[str, Any]]] = [_without_thinking(r.blocks) for r in rounds]
    tool_use_ids: dict[str, str] = {}
    rebuilt = 0
    for position in range(len(rounds) - 1, -1, -1):
        round_ = rounds[position]
        blocks = decode_thinking_envelope(round_.envelope, model=model)
        repaired = _tool_use_id_repairs(round_.blocks, blocks) if blocks is not None else None
        if blocks is None or repaired is None:
            break
        content[position] = blocks
        tool_use_ids.update(repaired)
        rebuilt += 1
    return ReplayedRounds(content=content, tool_use_ids=tool_use_ids, rebuilt=rebuilt)


def _valid_blocks(content: Any, *, exact: bool = False) -> list[dict[str, Any]] | None:
    """Plain Anthropic blocks with only their known fields, or None if any block is unknown or
    incomplete. With ``exact``, a block carrying any extra field is refused as well."""
    if not isinstance(content, list) or not content:
        return None
    blocks: list[dict[str, Any]] = []
    for block in content:
        kind = block.get("type") if isinstance(block, dict) else None
        fields = _BLOCK_FIELDS.get(kind) if isinstance(kind, str) else None
        if fields is None:
            return None
        if exact and set(block) != {"type", *fields}:
            return None
        clean: dict[str, Any] = {"type": kind}
        for name, expected in fields.items():
            value = block.get(name)
            if not isinstance(value, expected):
                return None
            clean[name] = value
        if kind == "thinking" and not clean["signature"]:
            return None
        if kind == "tool_use" and not (clean["id"] and clean["name"]):
            return None
        blocks.append(clean)
    return blocks


def _tool_use_id_repairs(client: list[dict[str, Any]], envelope: list[dict[str, Any]]) -> dict[str, str] | None:
    """Client tool-use id -> envelope id, matched by position within the round. None when the two
    disagree on how many tool calls the round made: then the envelope is not this round's."""
    client_ids = [str(b.get("id") or "") for b in client if b.get("type") == "tool_use"]
    envelope_ids = [str(b["id"]) for b in envelope if b.get("type") == "tool_use"]
    if len(client_ids) != len(envelope_ids):
        return None
    return {sent: original for sent, original in zip(client_ids, envelope_ids) if sent and sent != original}


def _without_thinking(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [block for block in blocks if block.get("type") not in _THINKING_TYPES]
