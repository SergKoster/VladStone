import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.realtime.match_channels import match_channel_manager
from app.services.auth import get_user_by_refresh_token
from app.services.combat_matches import (
    expire_combat_match_if_outdated,
    get_combat_match_record,
    load_v4_battle,
)
from app.services.combat_turn_timers import resolve_expired_planning_match

router = APIRouter(prefix="/ws", tags=["websocket"])
MAX_WS_MESSAGE_BYTES = 4096
EXTERNAL_ENVIRONMENTS = {"production", "staging"}


@router.websocket("/matches/{match_id}")
async def match_websocket(websocket: WebSocket, match_id: str) -> None:
    with SessionLocal() as db:
        record = get_combat_match_record(db, match_id)
        if record is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        refresh_token = websocket.cookies.get("refresh_token")
        user = get_user_by_refresh_token(db, refresh_token) if refresh_token else None
        if get_settings().environment in EXTERNAL_ENVIRONMENTS and user is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        if record.owner_user_id is not None and (user is None or record.owner_user_id != user.id):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Ruleset gate on connect: an old-version match closes gracefully
        # instead of streaming an unparseable snapshot.
        if expire_combat_match_if_outdated(record):
            db.commit()
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        resolved = resolve_expired_planning_match(db, record)
        if resolved is not None:
            db.commit()
            match = resolved.state
        else:
            match = load_v4_battle(record)

    # Ленивый дорезолв на reconnect — такой же серверный факт, как дорезолв
    # HTTP/воркером. Сначала сообщаем уже подключённым клиентам, затем новый
    # сокет получит тот же envelope своим snapshot.
    if resolved is not None:
        await match_channel_manager.broadcast_match_update(
            resolved.state,
            events=resolved.events,
            resolved_turn=resolved.resolved_turn,
        )

    await match_channel_manager.connect(match_id, websocket)
    try:
        await match_channel_manager.send_snapshot(
            websocket,
            match,
            events=resolved.events if resolved is not None else match.last_events,
            resolved_turn=(
                resolved.resolved_turn if resolved is not None else match.last_resolved_turn
            ),
        )
        while True:
            incoming = await websocket.receive()
            raw = incoming.get("text")
            if raw is None or len(raw.encode("utf-8")) > MAX_WS_MESSAGE_BYTES:
                await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                return
            message = json.loads(raw)
            if not isinstance(message, dict):
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            if message.get("type") == "ping":
                await match_channel_manager.send_pong(websocket)
    except WebSocketDisconnect:
        pass
    finally:
        match_channel_manager.disconnect(match_id, websocket)
