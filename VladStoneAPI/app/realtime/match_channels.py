from __future__ import annotations

from collections import defaultdict

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.domain.combat.engine.battle import BattleStateV4
from app.domain.combat.engine.payload import v4_combat_response
from app.services.combat_matches import expired_match_payload


class MatchChannelManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, match_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[match_id].add(websocket)

    def disconnect(self, match_id: str, websocket: WebSocket) -> None:
        sockets = self._connections.get(match_id)
        if sockets is None:
            return
        sockets.discard(websocket)
        if not sockets:
            self._connections.pop(match_id, None)

    async def send_snapshot(self, websocket: WebSocket, match: BattleStateV4) -> None:
        await websocket.send_json({"type": "match.snapshot", **v4_combat_response(match)})

    async def send_pong(self, websocket: WebSocket) -> None:
        await websocket.send_json({"type": "pong"})

    async def broadcast_match_update(self, match: BattleStateV4) -> None:
        await self._broadcast(match.id, {"type": "match.updated", **v4_combat_response(match)})

    async def broadcast_expired(self, match_id: str) -> None:
        payload = {"type": "match.updated", **expired_match_payload(match_id)}
        await self._broadcast(match_id, payload)

    async def _broadcast(self, match_id: str, payload: dict) -> None:
        disconnected: list[WebSocket] = []
        for websocket in list(self._connections.get(match_id, set())):
            if websocket.application_state != WebSocketState.CONNECTED:
                disconnected.append(websocket)
                continue
            try:
                await websocket.send_json(payload)
            except RuntimeError:
                disconnected.append(websocket)
        for websocket in disconnected:
            self.disconnect(match_id, websocket)


match_channel_manager = MatchChannelManager()
