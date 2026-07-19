import asyncio
import logging
from contextlib import suppress

from app.db.session import SessionLocal
from app.realtime.match_channels import match_channel_manager
from app.services.combat_turn_timers import resolve_expired_planning_matches

TIMER_WORKER_INTERVAL_SECONDS = 1

logger = logging.getLogger(__name__)


async def run_combat_timer_worker() -> None:
    while True:
        await asyncio.sleep(TIMER_WORKER_INTERVAL_SECONDS)
        # Последний рубеж (V3-фикс): исключение тика НЕ убивает корутину —
        # мёртвый воркер означал бы «таймеры всех матчей молча стоят».
        try:
            with SessionLocal() as db:
                # Commits happen per match inside (optimistic-lock conflicts are
                # skipped there without losing the rest of the batch).
                resolved_matches = resolve_expired_planning_matches(db)
                if not resolved_matches:
                    continue
            for resolved in resolved_matches:
                with suppress(RuntimeError):
                    await match_channel_manager.broadcast_match_update(
                        resolved.state,
                        events=resolved.events,
                        resolved_turn=resolved.resolved_turn,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("combat timer worker tick failed")
