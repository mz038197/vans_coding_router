from __future__ import annotations

import re
from pathlib import Path

DEFAULT_LOBBY_WORKSPACE = Path.home() / ".vans_coding_router" / "lobby"

_ROOM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class InvalidRoomIdError(ValueError):
    pass


def validate_room_id(room_id: str) -> str:
    room_id = room_id.strip()
    if not room_id:
        raise InvalidRoomIdError("room_id required")
    if ".." in room_id or "/" in room_id or "\\" in room_id:
        raise InvalidRoomIdError("room_id must not contain path separators or '..'")
    if not _ROOM_ID_RE.match(room_id):
        raise InvalidRoomIdError(
            "room_id must start with a letter or digit and contain only letters, digits, '_', or '-'"
        )
    return room_id


def resolve_lobby_workspace(path: str | Path | None = None) -> Path:
    if path is None:
        return DEFAULT_LOBBY_WORKSPACE.expanduser().resolve()
    return Path(path).expanduser().resolve()


def ensure_lobby_dirs(workspace: Path) -> Path:
    root = workspace.expanduser().resolve()
    (root / "rooms").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    return root


def room_config_path(workspace: Path, room_id: str) -> Path:
    valid_id = validate_room_id(room_id)
    root = ensure_lobby_dirs(workspace)
    path = (root / "rooms" / f"{valid_id}.json").resolve()
    rooms_dir = (root / "rooms").resolve()
    if not path.is_relative_to(rooms_dir):
        raise InvalidRoomIdError("room_id resolves outside rooms directory")
    return path


def room_log_path(workspace: Path, room_id: str) -> Path:
    valid_id = validate_room_id(room_id)
    root = ensure_lobby_dirs(workspace)
    path = (root / "logs" / f"{valid_id}.jsonl").resolve()
    logs_dir = (root / "logs").resolve()
    if not path.is_relative_to(logs_dir):
        raise InvalidRoomIdError("room_id resolves outside logs directory")
    return path
