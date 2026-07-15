from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

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


@router.websocket("/matches/{match_id}")
async def match_websocket(websocket: WebSocket, match_id: str) -> None:
    with SessionLocal() as db:
        record = get_combat_match_record(db, match_id)
        if record is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        refresh_token = websocket.cookies.get("refresh_token")
        user = get_user_by_refresh_token(db, refresh_token) if refresh_token else None
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
            message = await websocket.receive_json()
            if message.get("type") == "ping":
                await match_channel_manager.send_pong(websocket)
    except WebSocketDisconnect:
        pass
    finally:
        match_channel_manager.disconnect(match_id, websocket)
