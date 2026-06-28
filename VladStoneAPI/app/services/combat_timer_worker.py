import asyncio
from contextlib import suppress

from app.db.session import SessionLocal
from app.realtime.match_channels import match_channel_manager
from app.services.combat_turn_timers import resolve_expired_planning_matches

TIMER_WORKER_INTERVAL_SECONDS = 1


async def run_combat_timer_worker() -> None:
    while True:
        await asyncio.sleep(TIMER_WORKER_INTERVAL_SECONDS)
        with SessionLocal() as db:
            resolved_matches = resolve_expired_planning_matches(db)
            if not resolved_matches:
                continue
            db.commit()
        for match in resolved_matches:
            with suppress(RuntimeError):
                await match_channel_manager.broadcast_match_update(match)
