from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Cookie, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from src.application.use_cases.lobby_use_case import LobbyHostUseCase
from src.application.use_cases.portal_use_case import PortalUseCase
from src.infrastructure.config import RouterSettings
from src.infrastructure.lobby.paths import InvalidRoomIdError, validate_room_id
from src.infrastructure.lobby.protocol import JoinMessage, PassMessage, SayMessage, TurnDoneMessage, parse_client_message
from src.infrastructure.lobby.storage import load_room_messages, load_room_timeline

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
LOBBY_HTML_PATH = WEB_DIR / "lobby_host.html"
PORTAL_CSS_PATH = WEB_DIR / "portal.css"


class CreateRoomRequest(BaseModel):
    room_id: str


class RoomConfigPatch(BaseModel):
    topic: str = ""
    rules: str = ""
    turn_timeout_sec: int = Field(default=60, ge=1, le=600)
    turn_gap_sec: int = Field(default=5, ge=0, le=120)
    mention_enabled: bool = True
    round_robin_enabled: bool = True
    skip_gap_on_first_grant: bool = True
    paused: bool = False


class BroadcastRequest(BaseModel):
    text: str


def create_lobby_router(
    lobby_use_case: LobbyHostUseCase,
    portal_use_case: PortalUseCase,
    settings: RouterSettings,
) -> APIRouter:
    router = APIRouter(tags=["Lobby"])

    def _user(session_user_id: str | None) -> dict[str, Any] | None:
        if not session_user_id:
            return None
        return portal_use_case.me(int(session_user_id))

    def _require_host(session_user_id: str | None) -> dict[str, Any]:
        user = _user(session_user_id)
        try:
            return lobby_use_case.assert_host(user)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None

    def _handle_value_error(exc: ValueError) -> HTTPException:
        if str(exc) == "room not found":
            return HTTPException(status_code=404, detail=str(exc))
        return HTTPException(status_code=400, detail=str(exc))

    @router.get("/portal/static/portal.css")
    async def portal_css():
        if not PORTAL_CSS_PATH.is_file():
            raise HTTPException(status_code=404, detail="portal.css not found")
        return HTMLResponse(
            PORTAL_CSS_PATH.read_text(encoding="utf-8"),
            media_type="text/css",
        )

    @router.get("/lobby", response_class=HTMLResponse)
    async def lobby_page(session_user_id: str | None = Cookie(default=None)):
        _require_host(session_user_id)
        return HTMLResponse(LOBBY_HTML_PATH.read_text(encoding="utf-8"))

    @router.get("/lobby/api/config")
    async def lobby_config():
        base = settings.public_url.rstrip("/")
        ws_proto = "wss" if base.startswith("https://") else "ws"
        ws_base = base.replace("https://", "ws://").replace("http://", "ws://")
        return {
            "public_url": base,
            "ws_url": f"{ws_base}/lobby/ws",
            "join_command_template": (
                f"peas-agent lobby join --url {ws_proto}://{{host}}/lobby/ws "
                "--room {room_id} --display-name \"姓名\""
            ),
        }

    @router.get("/lobby/api/rooms")
    async def list_rooms(session_user_id: str | None = Cookie(default=None)):
        user = _require_host(session_user_id)
        return {"items": lobby_use_case.list_rooms(user)}

    @router.post("/lobby/api/rooms")
    async def create_room(
        body: CreateRoomRequest,
        session_user_id: str | None = Cookie(default=None),
    ):
        user = _require_host(session_user_id)
        try:
            return lobby_use_case.create_room(user, body.room_id)
        except InvalidRoomIdError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except ValueError as exc:
            raise _handle_value_error(exc) from None

    @router.get("/lobby/api/rooms/{room_id}")
    async def get_room(room_id: str, session_user_id: str | None = Cookie(default=None)):
        user = _require_host(session_user_id)
        try:
            return lobby_use_case.get_room(user, room_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except ValueError as exc:
            raise _handle_value_error(exc) from None

    @router.patch("/lobby/api/rooms/{room_id}/config")
    async def patch_room_config(
        room_id: str,
        body: RoomConfigPatch,
        session_user_id: str | None = Cookie(default=None),
    ):
        user = _require_host(session_user_id)
        try:
            return await lobby_use_case.update_config(user, room_id, body.model_dump())
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except ValueError as exc:
            raise _handle_value_error(exc) from None

    @router.post("/lobby/api/rooms/{room_id}/start")
    async def start_room(room_id: str, session_user_id: str | None = Cookie(default=None)):
        user = _require_host(session_user_id)
        try:
            return await lobby_use_case.start_discussion(user, room_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except ValueError as exc:
            raise _handle_value_error(exc) from None

    @router.post("/lobby/api/rooms/{room_id}/broadcast")
    async def broadcast_room(
        room_id: str,
        body: BroadcastRequest,
        session_user_id: str | None = Cookie(default=None),
    ):
        user = _require_host(session_user_id)
        try:
            await lobby_use_case.broadcast(user, room_id, body.text)
            return {"ok": True}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except ValueError as exc:
            raise _handle_value_error(exc) from None

    @router.delete("/lobby/api/rooms/{room_id}")
    async def delete_room_api(room_id: str, session_user_id: str | None = Cookie(default=None)):
        user = _require_host(session_user_id)
        try:
            await lobby_use_case.delete_room(user, room_id)
            return {"ok": True}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except ValueError as exc:
            raise _handle_value_error(exc) from None

    async def _send_admin_snapshot(ws: WebSocket, room: Any) -> None:
        room_id = room.config.room_id
        await ws.send_text(
            json.dumps(
                {"type": "history", "entries": load_room_timeline(lobby_use_case.workspace, room_id)},
                ensure_ascii=False,
            )
        )
        await ws.send_text(json.dumps({"type": "room_config", **room.config.to_dict()}, ensure_ascii=False))
        await ws.send_text(
            json.dumps(
                {
                    "type": "members",
                    "room_id": room_id,
                    "members": [m.to_dict() for m in room.member_list()],
                },
                ensure_ascii=False,
            )
        )
        await ws.send_text(
            json.dumps(
                {
                    "type": "admin_status",
                    "current_speaker": room.current_speaker,
                    "turn_no": room.turn_no,
                    "discussion_started": room.config.discussion_started,
                    "paused": room.config.paused,
                },
                ensure_ascii=False,
            )
        )

    @router.websocket("/lobby/admin/ws/{room_id}")
    async def admin_websocket(ws: WebSocket, room_id: str):
        session_user_id = ws.cookies.get("session_user_id")
        user = _user(session_user_id)
        try:
            lobby_use_case.assert_host(user)
            config = lobby_use_case.assert_room_access(user, room_id)
        except (PermissionError, ValueError):
            await ws.close(code=1008)
            return

        room = lobby_use_case.get_room_for_ws(config.room_id)
        if room is None:
            await ws.close(code=1008)
            return

        await ws.accept()
        connection_id = uuid.uuid4().hex
        lobby_use_case.hub.add_admin(room_id, connection_id, ws)
        try:
            await _send_admin_snapshot(ws, room)
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            lobby_use_case.hub.remove_admin(room_id, connection_id)

    @router.websocket("/lobby/ws")
    async def agent_websocket(ws: WebSocket):
        await ws.accept()
        connection_id = uuid.uuid4().hex
        joined_room_id: str | None = None
        agent_id: str | None = None

        try:
            while True:
                raw = await ws.receive_text()
                msg = parse_client_message(json.loads(raw))

                if isinstance(msg, JoinMessage):
                    try:
                        validate_room_id(msg.room_id)
                    except InvalidRoomIdError as exc:
                        await ws.send_text(
                            json.dumps(
                                {
                                    "type": "join_rejected",
                                    "reason": "invalid_room_id",
                                    "message": str(exc),
                                },
                                ensure_ascii=False,
                            )
                        )
                        continue

                    room = lobby_use_case.get_room_for_ws(msg.room_id)
                    if room is None:
                        await ws.send_text(
                            json.dumps(
                                {
                                    "type": "join_rejected",
                                    "reason": "room_not_found",
                                    "message": f"Room {msg.room_id} does not exist",
                                },
                                ensure_ascii=False,
                            )
                        )
                        continue

                    result = await room.handle_join(
                        connection_id,
                        display_name=msg.display_name,
                        rejoin_token=msg.rejoin_token,
                    )
                    await ws.send_text(json.dumps(result, ensure_ascii=False))
                    if result.get("type") == "join_ok":
                        joined_room_id = msg.room_id
                        lobby_use_case.hub.add(joined_room_id, connection_id, ws)
                        agent_id = result["agent_id"]
                        await room.send_room_config(connection_id)
                        await room.publish_members()
                        messages = load_room_messages(lobby_use_case.workspace, msg.room_id)
                        await lobby_use_case.hub.send(
                            joined_room_id,
                            {"type": "message_history", "messages": messages},
                            target_connection_id=connection_id,
                        )
                    continue

                if not joined_room_id or not agent_id:
                    continue

                room = lobby_use_case.get_room_for_ws(joined_room_id)
                if room is None:
                    continue

                if isinstance(msg, SayMessage):
                    await room.handle_say(agent_id, msg.text)
                elif isinstance(msg, TurnDoneMessage):
                    await room.handle_turn_done(agent_id)
                elif isinstance(msg, PassMessage):
                    await room.handle_pass(agent_id)
        except WebSocketDisconnect:
            pass
        finally:
            if joined_room_id:
                room = lobby_use_case.get_room_for_ws(joined_room_id)
                if room is not None:
                    await room.disconnect(connection_id)
                lobby_use_case.hub.remove(joined_room_id, connection_id)

    return router
