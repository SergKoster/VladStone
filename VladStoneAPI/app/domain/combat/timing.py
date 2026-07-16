from datetime import UTC, datetime, timedelta
from math import ceil

from app.domain.combat.constants import (
    MAX_RESOLVE_BUFFER_SECONDS,
    RESOLVE_STEP_SECONDS,
    TURN_DURATION_SECONDS,
    TURN_TIMER_FLOOR_SECONDS,
    TURN_TIMER_SHRINK_START_TURN,
)
from app.domain.combat.models import MatchLifecycleStatus, MatchState


def resolution_buffer_seconds(num_events: int) -> int:
    """Time to reserve for the client to animate `num_events` micro-steps."""
    return min(MAX_RESOLVE_BUFFER_SECONDS, ceil(max(0, num_events) * RESOLVE_STEP_SECONDS))


def turn_duration_seconds(turn: int) -> int:
    """Время планирования хода с эндшпильным сжатием (DESIGN §3.5).

    До TURN_TIMER_SHRINK_START_TURN — базовые TURN_DURATION_SECONDS; начиная с
    него каждый ход −1 с, пол — TURN_TIMER_FLOOR_SECONDS. Сервер отдаёт это
    число клиенту в payload (`planning_seconds`) — фронт формулу не дублирует.
    """
    over_shrink_start = max(0, turn - (TURN_TIMER_SHRINK_START_TURN - 1))
    return max(TURN_TIMER_FLOOR_SECONDS, TURN_DURATION_SECONDS - over_shrink_start)


def start_planning_timer(
    match: MatchState,
    *,
    now: datetime | None = None,
    resolve_buffer_seconds: int = 0,
) -> MatchState:
    started_at = _as_utc(now or datetime.now(UTC))
    match.planning_deadline = started_at + timedelta(
        seconds=resolve_buffer_seconds + TURN_DURATION_SECONDS
    )
    return match


def clear_planning_timer(match: MatchState) -> MatchState:
    match.planning_deadline = None
    return match


def is_planning_deadline_expired(
    match: MatchState,
    *,
    now: datetime | None = None,
) -> bool:
    if match.status != MatchLifecycleStatus.PLANNING or match.planning_deadline is None:
        return False
    return _as_utc(now or datetime.now(UTC)) >= _as_utc(match.planning_deadline)


def seconds_until_deadline(match: MatchState, *, now: datetime | None = None) -> int | None:
    if match.planning_deadline is None:
        return None
    remaining = (
        _as_utc(match.planning_deadline) - _as_utc(now or datetime.now(UTC))
    ).total_seconds()
    return max(0, int(remaining))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
