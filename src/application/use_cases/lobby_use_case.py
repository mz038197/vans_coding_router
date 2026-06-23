from __future__ import annotations

from pathlib import Path
from typing import Any

from src.infrastructure.lobby.paths import InvalidRoomIdError, validate_room_id
from src.infrastructure.lobby.protocol import RoomConfig
from src.infrastructure.lobby.registry import ConnectionHub, RoomRegistry
from src.infrastructure.lobby.room import Room
from src.infrastructure.lobby.storage import (
    delete_room,
    list_room_configs,
    load_room_config,
    save_room_config,
)


class LobbyHostUseCase:
    def __init__(self, workspace: Path, registry: RoomRegistry, hub: ConnectionHub) -> None:
        self.workspace = workspace
        self.registry = registry
        self.hub = hub

    def wire_room(self, room: Room) -> None:
        room_id = room.config.room_id

        async def _broadcast(
            event: dict[str, Any],
            target_connection_id: str | None = None,
        ) -> None:
            if target_connection_id:
                await self.hub.send(room_id, event, target_connection_id=target_connection_id)
            else:
                await self.hub.send(room_id, event)
                await self.hub.send_admin(room_id, event)

        room.set_broadcast(_broadcast)

    def _roles(self, user: dict[str, Any]) -> list[str]:
        roles = user.get("roles")
        if isinstance(roles, list) and roles:
            return [str(r) for r in roles]
        role = user.get("role")
        return [str(role)] if role else []

    def _is_admin(self, user: dict[str, Any]) -> bool:
        return "admin" in self._roles(user)

    def _is_host(self, user: dict[str, Any]) -> bool:
        roles = self._roles(user)
        return "admin" in roles or "teacher" in roles

    def assert_host(self, user: dict[str, Any] | None) -> dict[str, Any]:
        if not user:
            raise PermissionError("尚未登入")
        if not self._is_host(user):
            raise PermissionError("僅老師或管理員可使用 Agent Lobby")
        return user

    def can_access_room(self, user: dict[str, Any], config: RoomConfig) -> bool:
        if self._is_admin(user):
            return True
        return config.created_by_user_id == user["id"]

    def assert_room_access(self, user: dict[str, Any], room_id: str) -> RoomConfig:
        self.assert_host(user)
        config = load_room_config(self.workspace, room_id)
        if config is None:
            raise ValueError("room not found")
        if not self.can_access_room(user, config):
            raise PermissionError("無權限存取此聊天室")
        return config

    def list_rooms(self, user: dict[str, Any]) -> list[dict[str, Any]]:
        self.assert_host(user)
        items: list[dict[str, Any]] = []
        for config in list_room_configs(self.workspace):
            if not self.can_access_room(user, config):
                continue
            room = self.registry.get(config.room_id)
            member_count = len(room.member_list()) if room else 0
            status = "paused" if config.paused else ("active" if config.discussion_started else "waiting")
            items.append(
                {
                    "room_id": config.room_id,
                    "topic": config.topic,
                    "created_by_user_id": config.created_by_user_id,
                    "created_by_name": config.created_by_name,
                    "discussion_started": config.discussion_started,
                    "paused": config.paused,
                    "status": status,
                    "member_count": member_count,
                }
            )
        return sorted(items, key=lambda x: x["room_id"])

    def create_room(self, user: dict[str, Any], room_id: str) -> dict[str, Any]:
        user = self.assert_host(user)
        room_id = validate_room_id(room_id)
        if load_room_config(self.workspace, room_id) is not None:
            raise ValueError("room_id 已存在")
        config = RoomConfig(
            room_id=room_id,
            created_by_user_id=int(user["id"]),
            created_by_name=str(user.get("name") or user.get("email") or ""),
        )
        save_room_config(self.workspace, config)
        room = self.registry.set_config(config)
        self.wire_room(room)
        return config.to_dict()

    def get_room(self, user: dict[str, Any], room_id: str) -> dict[str, Any]:
        config = self.assert_room_access(user, room_id)
        room = self.registry.get(room_id)
        if room is None:
            raise ValueError("room not found")
        self.wire_room(room)
        return {
            "config": config.to_dict(),
            "members": [m.to_dict() for m in room.member_list()],
            "current_speaker": room.current_speaker,
            "turn_no": room.turn_no,
        }

    async def update_config(self, user: dict[str, Any], room_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        existing = self.assert_room_access(user, room_id)
        config = RoomConfig(
            room_id=room_id,
            topic=str(patch.get("topic", existing.topic)),
            rules=str(patch.get("rules", existing.rules)),
            turn_timeout_sec=int(patch.get("turn_timeout_sec", existing.turn_timeout_sec)),
            turn_gap_sec=int(patch.get("turn_gap_sec", existing.turn_gap_sec)),
            mention_enabled=bool(patch.get("mention_enabled", existing.mention_enabled)),
            round_robin_enabled=bool(patch.get("round_robin_enabled", existing.round_robin_enabled)),
            discussion_started=existing.discussion_started,
            skip_gap_on_first_grant=bool(patch.get("skip_gap_on_first_grant", existing.skip_gap_on_first_grant)),
            paused=bool(patch.get("paused", existing.paused)),
            created_by_user_id=existing.created_by_user_id,
            created_by_name=existing.created_by_name,
        )
        save_room_config(self.workspace, config)
        room = self.registry.set_config(config)
        self.wire_room(room)
        await room.update_config(config)
        return config.to_dict()

    async def start_discussion(self, user: dict[str, Any], room_id: str) -> dict[str, Any]:
        self.assert_room_access(user, room_id)
        room = self.registry.get(room_id)
        if room is None:
            raise ValueError("room not found")
        self.wire_room(room)
        return await room.start_discussion()

    async def broadcast(self, user: dict[str, Any], room_id: str, text: str) -> None:
        self.assert_room_access(user, room_id)
        room = self.registry.get(room_id)
        if room is None:
            raise ValueError("room not found")
        self.wire_room(room)
        await room.broadcast_system(text.strip())

    async def delete_room(self, user: dict[str, Any], room_id: str) -> None:
        self.assert_room_access(user, room_id)
        room = self.registry.get(room_id)
        if room is not None:
            self.wire_room(room)
            await room.shutdown()
            await self.hub.close_room(room_id)
        delete_room(self.workspace, room_id)
        self.registry.remove(room_id)

    def get_room_for_ws(self, room_id: str) -> Room | None:
        try:
            validate_room_id(room_id)
        except InvalidRoomIdError:
            return None
        room = self.registry.get(room_id)
        if room is not None:
            self.wire_room(room)
        return room
