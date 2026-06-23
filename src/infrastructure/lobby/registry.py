from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import WebSocket

from src.infrastructure.lobby.protocol import RoomConfig
from src.infrastructure.lobby.room import Room
from src.infrastructure.lobby.storage import list_room_ids, load_room_config, room_exists


class RoomRegistry:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.rooms: dict[str, Room] = {}

    def load_from_disk(self) -> None:
        for room_id in list_room_ids(self.workspace):
            config = load_room_config(self.workspace, room_id)
            if config is not None:
                self.rooms[room_id] = Room(config=config, workspace=self.workspace)

    def get(self, room_id: str) -> Room | None:
        if room_id in self.rooms:
            return self.rooms[room_id]
        if not room_exists(self.workspace, room_id):
            return None
        config = load_room_config(self.workspace, room_id)
        if config is None:
            return None
        room = Room(config=config, workspace=self.workspace)
        self.rooms[room_id] = room
        return room

    def set_config(self, config: RoomConfig) -> Room:
        room = self.get(config.room_id)
        if room is None:
            room = Room(config=config, workspace=self.workspace)
            self.rooms[config.room_id] = room
        else:
            room.config = config
        return room

    def remove(self, room_id: str) -> None:
        self.rooms.pop(room_id, None)


class ConnectionHub:
    def __init__(self) -> None:
        self.connections: dict[str, dict[str, WebSocket]] = {}
        self.admin_connections: dict[str, dict[str, WebSocket]] = {}

    def add(self, room_id: str, connection_id: str, ws: WebSocket) -> None:
        self.connections.setdefault(room_id, {})[connection_id] = ws

    def add_admin(self, room_id: str, connection_id: str, ws: WebSocket) -> None:
        self.admin_connections.setdefault(room_id, {})[connection_id] = ws

    def remove(self, room_id: str, connection_id: str) -> None:
        room = self.connections.get(room_id)
        if not room:
            return
        room.pop(connection_id, None)
        if not room:
            self.connections.pop(room_id, None)

    def remove_admin(self, room_id: str, connection_id: str) -> None:
        room = self.admin_connections.get(room_id)
        if not room:
            return
        room.pop(connection_id, None)
        if not room:
            self.admin_connections.pop(room_id, None)

    async def close_room(self, room_id: str) -> None:
        for pool in (self.connections, self.admin_connections):
            room = pool.pop(room_id, {})
            for ws in list(room.values()):
                try:
                    await ws.close()
                except Exception:
                    pass

    async def _send_to(self, room: dict[str, WebSocket], payload: str, *, target: str | None) -> None:
        if target:
            ws = room.get(target)
            if ws:
                await ws.send_text(payload)
            return
        for ws in list(room.values()):
            try:
                await ws.send_text(payload)
            except Exception:
                pass

    async def send(
        self,
        room_id: str,
        event: dict[str, Any],
        *,
        target_connection_id: str | None = None,
    ) -> None:
        room = self.connections.get(room_id, {})
        payload = json.dumps(event, ensure_ascii=False)
        await self._send_to(room, payload, target=target_connection_id)

    async def send_admin(self, room_id: str, event: dict[str, Any]) -> None:
        room = self.admin_connections.get(room_id, {})
        payload = json.dumps(event, ensure_ascii=False)
        await self._send_to(room, payload, target=None)
