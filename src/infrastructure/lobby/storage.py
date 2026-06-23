from __future__ import annotations

import json
from pathlib import Path

from src.infrastructure.lobby.paths import ensure_lobby_dirs, room_config_path, room_log_path
from src.infrastructure.lobby.protocol import RoomConfig


def load_room_config(workspace: Path, room_id: str) -> RoomConfig | None:
    path = room_config_path(workspace, room_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return RoomConfig.from_dict(data)


def save_room_config(workspace: Path, config: RoomConfig) -> Path:
    ensure_lobby_dirs(workspace)
    path = room_config_path(workspace, config.room_id)
    path.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def list_room_ids(workspace: Path) -> list[str]:
    rooms_dir = ensure_lobby_dirs(workspace) / "rooms"
    return sorted(p.stem for p in rooms_dir.glob("*.json"))


def list_room_configs(workspace: Path) -> list[RoomConfig]:
    configs: list[RoomConfig] = []
    for room_id in list_room_ids(workspace):
        config = load_room_config(workspace, room_id)
        if config is not None:
            configs.append(config)
    return configs


def room_exists(workspace: Path, room_id: str) -> bool:
    return room_config_path(workspace, room_id).is_file()


def delete_room(workspace: Path, room_id: str) -> bool:
    deleted = False
    config_path = room_config_path(workspace, room_id)
    if config_path.is_file():
        config_path.unlink()
        deleted = True
    log_path = room_log_path(workspace, room_id)
    if log_path.is_file():
        log_path.unlink()
        deleted = True
    return deleted


def load_room_messages(workspace: Path, room_id: str, *, limit: int = 500) -> list[dict]:
    return [
        entry
        for entry in load_room_timeline(workspace, room_id, limit=limit)
        if entry.get("kind") == "message"
    ]


def load_room_timeline(workspace: Path, room_id: str, *, limit: int = 500) -> list[dict]:
    path = room_log_path(workspace, room_id)
    if not path.is_file():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "kind" not in entry and "text" in entry:
            entry = {**entry, "kind": "message"}
        entries.append(entry)
    return entries[-limit:]
