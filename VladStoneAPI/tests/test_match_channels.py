import asyncio

from app.realtime.match_channels import OUTBOUND_QUEUE_SIZE, MatchChannelManager


class _SlowSocket:
    def __init__(self) -> None:
        self.send_started = asyncio.Event()
        self.release_send = asyncio.Event()

    async def accept(self) -> None:
        return None

    async def send_json(self, payload: dict) -> None:
        self.send_started.set()
        await self.release_send.wait()

    async def close(self, code: int) -> None:
        return None


def test_slow_socket_does_not_block_match_broadcast() -> None:
    async def scenario() -> None:
        manager = MatchChannelManager()
        socket = _SlowSocket()
        await manager.connect("match", socket)  # type: ignore[arg-type]
        manager._enqueue("match", socket, {"n": 0})  # type: ignore[arg-type]
        await socket.send_started.wait()

        for number in range(OUTBOUND_QUEUE_SIZE + 1):
            await asyncio.wait_for(manager._broadcast("match", {"n": number}), timeout=0.1)

        await asyncio.sleep(0)
        assert "match" not in manager._connections
        socket.release_send.set()

    asyncio.run(scenario())
