from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.db.models import CombatMatchRecord
from app.domain.combat.models import MatchLifecycleStatus, MatchState
from app.domain.combat.rules import apply_simple_bot_turn, resolve_turn
from app.domain.combat.timing import is_planning_deadline_expired
from app.services.combat_matches import load_match, save_match
from app.services.rewards import claim_combat_reward


def resolve_expired_planning_match(
    db: Session,
    record: CombatMatchRecord,
    *,
    now: datetime | None = None,
) -> MatchState | None:
    checked_at = now or datetime.now(UTC)
    match = load_match(record)
    if not is_planning_deadline_expired(match, now=checked_at):
        return None

    match.events = []
    match = apply_simple_bot_turn(match)
    resolved = resolve_turn(match, now=checked_at)
    save_match(record, resolved)
    if record.owner_user_id is not None:
        claim_combat_reward(db, match=resolved, user_id=record.owner_user_id)
    return resolved


def resolve_expired_planning_matches(
    db: Session,
    *,
    now: datetime | None = None,
) -> list[MatchState]:
    checked_at = now or datetime.now(UTC)
    db.flush()
    records = list(
        db.scalars(
            select(CombatMatchRecord).where(
                CombatMatchRecord.status == MatchLifecycleStatus.PLANNING.value,
            )
        )
    )
    resolved_matches: list[MatchState] = []
    for record in records:
        # Commit per match: an optimistic-lock conflict on one match (someone
        # resolved it concurrently) must not discard the other resolves.
        try:
            resolved = resolve_expired_planning_match(db, record, now=checked_at)
            if resolved is None:
                continue
            db.commit()
        except StaleDataError:
            db.rollback()
            continue
        resolved_matches.append(resolved)
    return resolved_matches
