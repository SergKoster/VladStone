from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass

from fastapi import WebSocket

from app.domain.combat.engine.battle import BattleStateV4
from app.domain.combat.engine.payload import v4_combat_response
from app.services.combat_matches import expired_match_payload

OUTBOUND_QUEUE_SIZE = 8
SEND_TIMEOUT_SECONDS = 3


@dataclass
class _Connection:
    viewer_id: str | None
    queue: asyncio.Queue[dict]
    sender_task: asyncio.Task[None]


class MatchChannelManager:
    def __init__(self) -> None:
        self._connections: dict[str, dict[WebSocket, _Connection]] = defaultdict(dict)

    async def connect(
        self,
        match_id: str,
        websocket: WebSocket,
        *,
        viewer_id: str | None,
    ) -> None:
        await websocket.accept()
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=OUTBOUND_QUEUE_SIZE)
        sender_task = asyncio.create_task(self._send_loop(match_id, websocket, queue))
        self._connections[match_id][websocket] = _Connection(viewer_id, queue, sender_task)

    def disconnect(self, match_id: str, websocket: WebSocket) -> None:
        sockets = self._connections.get(match_id)
        if sockets is None:
            return
        connection = sockets.pop(websocket, None)
        if connection is not None and connection.sender_task is not asyncio.current_task():
            connection.sender_task.cancel()
        if not sockets:
            self._connections.pop(match_id, None)

    async def send_snapshot(
        self,
        websocket: WebSocket,
        match: BattleStateV4,
        *,
        events: list | None = None,
        resolved_turn: int | None = None,
        resume_from_sequence: int = 0,
    ) -> None:
        self._enqueue(
            match.id,
            websocket,
            {
                "type": "match.snapshot",
                **v4_combat_response(
                    match,
                    viewer_id=self._viewer_id_for(match.id, websocket),
                    events=events,
                    resolved_turn=resolved_turn,
                    resume_from_sequence=resume_from_sequence,
                ),
            },
        )

    async def send_pong(self, websocket: WebSocket) -> None:
        for match_id, sockets in self._connections.items():
            if websocket in sockets:
                self._enqueue(match_id, websocket, {"type": "pong"})
                return

    async def broadcast_match_update(
        self,
        match: BattleStateV4,
        *,
        events: list | None = None,
        resolved_turn: int | None = None,
    ) -> None:
        for websocket, connection in list(self._connections.get(match.id, {}).items()):
            self._enqueue(
                match.id,
                websocket,
                {
                    "type": "match.updated",
                    **v4_combat_response(
                        match,
                        viewer_id=connection.viewer_id,
                        events=events,
                        resolved_turn=resolved_turn,
                    ),
                },
            )

    async def broadcast_expired(self, match_id: str) -> None:
        payload = {"type": "match.updated", **expired_match_payload(match_id)}
        await self._broadcast(match_id, payload)

    async def _broadcast(self, match_id: str, payload: dict) -> None:
        for websocket in list(self._connections.get(match_id, {})):
            self._enqueue(match_id, websocket, payload)

    def _enqueue(self, match_id: str, websocket: WebSocket, payload: dict) -> None:
        connection = self._connections.get(match_id, {}).get(websocket)
        if connection is None:
            return
        try:
            connection.queue.put_nowait(payload)
        except asyncio.QueueFull:
            # Нечитающий клиент не имеет права тормозить commit/broadcast для
            # остальных. Закрываем его асинхронно, не ожидая сетевой операции.
            self.disconnect(match_id, websocket)
            asyncio.create_task(self._close_slow_socket(websocket))

    def _viewer_id_for(self, match_id: str, websocket: WebSocket) -> str | None:
        connection = self._connections.get(match_id, {}).get(websocket)
        return connection.viewer_id if connection is not None else None

    async def _send_loop(
        self,
        match_id: str,
        websocket: WebSocket,
        queue: asyncio.Queue[dict],
    ) -> None:
        try:
            while True:
                payload = await queue.get()
                await asyncio.wait_for(
                    websocket.send_json(payload),
                    timeout=SEND_TIMEOUT_SECONDS,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            asyncio.create_task(self._close_slow_socket(websocket))
        finally:
            self.disconnect(match_id, websocket)

    @staticmethod
    async def _close_slow_socket(websocket: WebSocket) -> None:
        try:
            await asyncio.wait_for(websocket.close(code=1013), timeout=1)
        except Exception:
            pass


match_channel_manager = MatchChannelManager()
