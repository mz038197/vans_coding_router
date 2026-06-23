from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.infrastructure.lobby.mentions import normalize_display_name, parse_mentions
from src.infrastructure.lobby.paths import room_log_path
from src.infrastructure.lobby.protocol import MemberInfo, RoomConfig
from src.infrastructure.lobby.storage import save_room_config


BroadcastFn = Callable[..., Awaitable[None]]
SendFn = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class Member:
    agent_id: str
    display_name: str
    rejoin_token: str
    connection_id: str
    online: bool = True


@dataclass
class Room:
    config: RoomConfig
    workspace: Path
    members: dict[str, Member] = field(default_factory=dict)
    connection_index: dict[str, str] = field(default_factory=dict)  # conn_id -> agent_id
    speak_queue: list[str] = field(default_factory=list)
    round_robin_index: int = 0
    current_speaker: str | None = None
    turn_no: int = 0
    next_serial: int = 0
    first_grant_done: bool = False
    pending_next_id: str | None = None
    _gap_task: asyncio.Task[None] | None = field(default=None, repr=False)
    _timeout_task: asyncio.Task[None] | None = field(default=None, repr=False)
    _broadcast: BroadcastFn | None = field(default=None, repr=False)

    def set_broadcast(self, fn: BroadcastFn) -> None:
        self._broadcast = fn

    async def emit_all(self, event: dict[str, Any]) -> None:
        if self._broadcast is not None:
            await self._broadcast(event)

    async def emit_one(self, connection_id: str, event: dict[str, Any]) -> None:
        if self._broadcast is not None:
            await self._broadcast(event, target_connection_id=connection_id)

    def member_list(self) -> list[MemberInfo]:
        return [
            MemberInfo(agent_id=m.agent_id, display_name=m.display_name)
            for m in self.members.values()
            if m.online
        ]

    def display_name_map(self) -> dict[str, str]:
        return {
            m.display_name: m.agent_id
            for m in self.members.values()
            if m.online
        }

    def is_display_name_taken(self, display_name: str, *, exclude_agent_id: str | None = None) -> bool:
        norm = normalize_display_name(display_name)
        for m in self.members.values():
            if not m.online:
                continue
            if exclude_agent_id and m.agent_id == exclude_agent_id:
                continue
            if normalize_display_name(m.display_name) == norm:
                return True
        return False

    def allocate_agent_id(self) -> str:
        self.next_serial += 1
        return f"m{self.next_serial:03d}"

    async def handle_join(
        self,
        connection_id: str,
        *,
        display_name: str | None,
        rejoin_token: str | None,
    ) -> dict[str, Any]:
        if rejoin_token:
            for member in self.members.values():
                if member.rejoin_token == rejoin_token:
                    old_connection_id = member.connection_id
                    if old_connection_id != connection_id:
                        self.connection_index.pop(old_connection_id, None)
                    member.connection_id = connection_id
                    member.online = True
                    self.connection_index[connection_id] = member.agent_id
                    return self._join_ok(member)
            return {
                "type": "join_rejected",
                "reason": "invalid_rejoin_token",
                "message": "rejoin_token 無效，請勿帶 token 並提供 display_name 重新加入。",
            }

        if not display_name or not display_name.strip():
            return {
                "type": "join_rejected",
                "reason": "display_name_required",
                "message": "請提供 display_name。",
            }

        display_name = display_name.strip()
        if self.is_display_name_taken(display_name):
            return {
                "type": "join_rejected",
                "reason": "display_name_taken",
                "message": f"顯示名稱「{display_name}」已在聊天室中，請改用其他名稱後再 join。",
            }

        agent_id = self.allocate_agent_id()
        token = secrets.token_hex(16)
        member = Member(
            agent_id=agent_id,
            display_name=display_name,
            rejoin_token=token,
            connection_id=connection_id,
        )
        self.members[agent_id] = member
        self.connection_index[connection_id] = agent_id
        return self._join_ok(member)

    def _join_ok(self, member: Member) -> dict[str, Any]:
        return {
            "type": "join_ok",
            "agent_id": member.agent_id,
            "display_name": member.display_name,
            "rejoin_token": member.rejoin_token,
            "members": [m.to_dict() for m in self.member_list()],
        }

    async def publish_members(self) -> None:
        await self.emit_all(
            {
                "type": "members",
                "room_id": self.config.room_id,
                "members": [m.to_dict() for m in self.member_list()],
            }
        )

    async def send_room_config(self, connection_id: str) -> None:
        await self.emit_one(connection_id, {"type": "room_config", **self.config.to_dict()})

    async def update_config(self, config: RoomConfig) -> None:
        self.config = config
        await self.emit_all({"type": "room_config_updated", **self.config.to_dict()})

    async def start_discussion(self) -> dict[str, Any]:
        if self.config.discussion_started:
            return {"ok": False, "reason": "already_started"}
        if not self.member_list():
            return {"ok": False, "reason": "no_members"}
        first = self._round_robin_next()
        if not first:
            return {"ok": False, "reason": "no_members"}
        self.config.discussion_started = True
        save_room_config(self.workspace, self.config)
        await self.emit_all(
            {
                "type": "discussion_started",
                "room_id": self.config.room_id,
            }
        )
        await self.grant_turn(first, skip_gap=self.config.skip_gap_on_first_grant)
        return {"ok": True, "agent_id": first}

    async def shutdown(self) -> None:
        await self._cancel_gap()
        await self._cancel_timeout()
        self.current_speaker = None
        self.speak_queue.clear()
        self.pending_next_id = None

    async def disconnect(self, connection_id: str) -> None:
        agent_id = self.connection_index.pop(connection_id, None)
        if not agent_id:
            return
        member = self.members.get(agent_id)
        if not member or member.connection_id != connection_id:
            return
        member.online = False
        if self.current_speaker == agent_id:
            await self._cancel_timeout()
            self.current_speaker = None
            await self._schedule_next()
        await self.publish_members()

    async def handle_say(self, agent_id: str, text: str) -> None:
        if agent_id != self.current_speaker:
            return
        member = self.members.get(agent_id)
        if not member:
            return
        ts = datetime.now(UTC).isoformat()
        await self._append_timeline(
            {
                "kind": "message",
                "from": agent_id,
                "display_name": member.display_name,
                "text": text,
                "ts": ts,
            }
        )
        await self.emit_all(
            {
                "type": "message",
                "from": agent_id,
                "display_name": member.display_name,
                "text": text,
                "ts": ts,
            }
        )
        self._enqueue_from_text(text, speaker_id=agent_id)

    def _enqueue_from_text(self, text: str, *, speaker_id: str) -> None:
        mentioned: list[str] = []
        if self.config.mention_enabled:
            mentioned = parse_mentions(text, display_name_to_agent_id=self.display_name_map())
            mentioned = [t for t in mentioned if t != speaker_id and self._is_online(t)]

        if mentioned:
            self.speak_queue.extend(mentioned)
            return

        if self.config.round_robin_enabled:
            nxt = self._round_robin_next(exclude=speaker_id)
            if nxt:
                self.speak_queue.append(nxt)

    def _is_online(self, agent_id: str) -> bool:
        m = self.members.get(agent_id)
        return bool(m and m.online)

    def _round_robin_next(self, *, exclude: str | None = None) -> str | None:
        online_ids = [m.agent_id for m in self.members.values() if m.online]
        if not online_ids:
            return None
        if exclude and len(online_ids) == 1 and online_ids[0] == exclude:
            return None
        for _ in range(len(online_ids)):
            agent_id = online_ids[self.round_robin_index % len(online_ids)]
            self.round_robin_index = (self.round_robin_index + 1) % len(online_ids)
            if agent_id != exclude:
                return agent_id
        return None

    async def handle_turn_done(self, agent_id: str) -> None:
        if agent_id != self.current_speaker:
            return
        await self._cancel_timeout()
        self.current_speaker = None
        await self._schedule_next()

    async def handle_pass(self, agent_id: str) -> None:
        await self.handle_turn_done(agent_id)

    async def _schedule_next(self) -> None:
        if self.config.paused or not self.config.discussion_started:
            return
        await self._cancel_gap()
        if not self.speak_queue and self.config.round_robin_enabled:
            nxt = self._round_robin_next()
            if nxt:
                self.speak_queue.append(nxt)
        if not self.speak_queue:
            return
        next_id = self.speak_queue.pop(0)
        if not self._is_online(next_id):
            await self._schedule_next()
            return
        gap = self.config.turn_gap_sec
        if gap <= 0:
            await self.grant_turn(next_id)
            return
        member = self.members[next_id]
        self.pending_next_id = next_id
        ts = datetime.now(UTC).isoformat()
        pending_event = {
            "type": "turn_pending",
            "next_agent_id": next_id,
            "next_display_name": member.display_name,
            "gap_sec": gap,
        }
        await self._append_timeline(
            {
                "kind": "turn_pending",
                "next_agent_id": next_id,
                "next_display_name": member.display_name,
                "gap_sec": gap,
                "ts": ts,
            }
        )
        await self.emit_all(pending_event)

        async def _after_gap() -> None:
            try:
                await asyncio.sleep(gap)
                if self.pending_next_id == next_id and self.current_speaker is None:
                    await self.grant_turn(next_id)
            finally:
                self.pending_next_id = None

        self._gap_task = asyncio.create_task(_after_gap())

    async def grant_turn(self, agent_id: str, *, skip_gap: bool = False) -> None:
        if self.config.paused or not self.config.discussion_started or not self._is_online(agent_id):
            return
        await self._cancel_gap()
        await self._cancel_timeout()
        self.current_speaker = agent_id
        self.turn_no += 1
        if not self.first_grant_done:
            self.first_grant_done = True
        member = self.members[agent_id]
        hint = f"輪到你了，請針對聊天室討論發表看法。"
        ts = datetime.now(UTC).isoformat()
        event = {
            "type": "turn_granted",
            "room_id": self.config.room_id,
            "agent_id": agent_id,
            "display_name": member.display_name,
            "turn_no": self.turn_no,
            "deadline_sec": self.config.turn_timeout_sec,
            "prompt_hint": hint,
        }
        await self._append_timeline(
            {
                "kind": "turn_granted",
                "agent_id": agent_id,
                "display_name": member.display_name,
                "turn_no": self.turn_no,
                "ts": ts,
            }
        )
        await self.emit_all(event)

        async def _on_timeout() -> None:
            try:
                await asyncio.sleep(self.config.turn_timeout_sec)
                if self.current_speaker == agent_id:
                    revoked_member = self.members.get(agent_id)
                    revoked_event = {
                        "type": "turn_revoked",
                        "agent_id": agent_id,
                        "reason": "timeout",
                        "display_name": revoked_member.display_name if revoked_member else "",
                    }
                    await self._append_timeline(
                        {
                            "kind": "turn_revoked",
                            "agent_id": agent_id,
                            "display_name": revoked_member.display_name if revoked_member else "",
                            "reason": "timeout",
                            "ts": datetime.now(UTC).isoformat(),
                        }
                    )
                    await self.emit_all(revoked_event)
                    self.current_speaker = None
                    await self._schedule_next()
            except asyncio.CancelledError:
                raise

        self._timeout_task = asyncio.create_task(_on_timeout())

    async def _cancel_gap(self) -> None:
        if self._gap_task and not self._gap_task.done():
            self._gap_task.cancel()
            try:
                await self._gap_task
            except asyncio.CancelledError:
                pass
        self._gap_task = None
        self.pending_next_id = None

    async def _cancel_timeout(self) -> None:
        if self._timeout_task and not self._timeout_task.done():
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass
        self._timeout_task = None

    async def _append_timeline(self, entry: dict[str, Any]) -> None:
        path = room_log_path(self.workspace, self.config.room_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if "ts" not in entry:
            entry = {**entry, "ts": datetime.now(UTC).isoformat()}
        line = json.dumps(entry, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    async def broadcast_system(self, text: str) -> None:
        ts = datetime.now(UTC).isoformat()
        await self._append_timeline(
            {
                "kind": "message",
                "from": "system",
                "display_name": "主持人",
                "text": text,
                "ts": ts,
            }
        )
        await self.emit_all(
            {
                "type": "message",
                "from": "system",
                "display_name": "主持人",
                "text": text,
                "ts": ts,
            }
        )
