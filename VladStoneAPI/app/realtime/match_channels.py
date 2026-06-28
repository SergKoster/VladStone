from __future__ import annotations

from collections import defaultdict

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.domain.combat.models import MatchState
from app.services.combat_payloads import combat_response


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

    async def send_snapshot(self, websocket: WebSocket, match: MatchState) -> None:
        await websocket.send_json(
            {
                "type": "match.snapshot",
                **combat_response(match),
            }
        )

    async def send_pong(self, websocket: WebSocket) -> None:
        await websocket.send_json({"type": "pong"})

    async def broadcast_match_update(self, match: MatchState) -> None:
        payload = {
            "type": "match.updated",
            **combat_response(match),
        }
        disconnected: list[WebSocket] = []
        for websocket in list(self._connections.get(match.id, set())):
            if websocket.application_state != WebSocketState.CONNECTED:
                disconnected.append(websocket)
                continue
            try:
                await websocket.send_json(payload)
            except RuntimeError:
                disconnected.append(websocket)

        for websocket in disconnected:
            self.disconnect(match.id, websocket)


match_channel_manager = MatchChannelManager()
