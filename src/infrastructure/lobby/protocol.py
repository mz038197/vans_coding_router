from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass
class RoomConfig:
    room_id: str
    topic: str = ""
    rules: str = ""
    turn_timeout_sec: int = 60
    turn_gap_sec: int = 5
    mention_enabled: bool = True
    round_robin_enabled: bool = True
    discussion_started: bool = False
    skip_gap_on_first_grant: bool = True
    paused: bool = False
    created_by_user_id: int = 0
    created_by_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoomConfig:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


@dataclass
class MemberInfo:
    agent_id: str
    display_name: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemberInfo:
        return cls(agent_id=str(data["agent_id"]), display_name=str(data["display_name"]))


@dataclass
class JoinMessage:
    room_id: str
    display_name: str | None = None
    rejoin_token: str | None = None
    type: Literal["join"] = field(default="join", repr=False)


@dataclass
class SayMessage:
    text: str
    type: Literal["say"] = field(default="say", repr=False)


@dataclass
class TurnDoneMessage:
    type: Literal["turn_done"] = field(default="turn_done", repr=False)


@dataclass
class PassMessage:
    type: Literal["pass"] = field(default="pass", repr=False)


def parse_client_message(data: dict[str, Any]) -> JoinMessage | SayMessage | TurnDoneMessage | PassMessage:
    kind = data.get("type")
    if kind == "join":
        return JoinMessage(
            room_id=str(data["room_id"]),
            display_name=data.get("display_name"),
            rejoin_token=data.get("rejoin_token"),
        )
    if kind == "say":
        return SayMessage(text=str(data.get("text", "")))
    if kind == "turn_done":
        return TurnDoneMessage()
    if kind == "pass":
        return PassMessage()
    raise ValueError(f"unknown message type: {kind!r}")
