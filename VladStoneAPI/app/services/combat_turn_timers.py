from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.db.models import CombatMatchRecord
from app.domain.combat.engine.apply import EngineEvent
from app.domain.combat.engine.battle import BattleStateV4, resolve_v4_turn
from app.domain.combat.engine.intents import PlayerIntents
from app.domain.combat.helpers import human_players
from app.domain.combat.models import MatchLifecycleStatus
from app.domain.combat.timing import is_planning_deadline_expired
from app.services.combat_matches import (
    expire_combat_match_if_outdated,
    load_v4_battle,
    save_v4_battle,
)
from app.services.rewards import claim_combat_reward


@dataclass(frozen=True)
class ResolvedPlanningMatch:
    state: BattleStateV4
    events: list[EngineEvent]
    resolved_turn: int


def resolve_expired_planning_match(
    db: Session,
    record: CombatMatchRecord,
    *,
    now: datetime | None = None,
) -> ResolvedPlanningMatch | None:
    """Дорезолв матча с истёкшим дедлайном планирования (v4).

    Ruleset-гейт сработал раньше в вызывающем коде (§8.7): сюда попадают только
    матчи текущей версии. AFK-игрок не блокирует бой — резолвим с пустыми
    намерениями человека (боты ходят внутри resolve_v4_turn).
    """
    if expire_combat_match_if_outdated(record):
        return None
    state = load_v4_battle(record)
    checked_at = now or datetime.now(UTC)
    if not is_planning_deadline_expired(state, now=checked_at):
        return None

    human = human_players(state)[0]
    resolved_turn = state.turn
    events = resolve_v4_turn(
        state,
        human_intents=PlayerIntents(player_id=human.id),
        now=checked_at,
    )
    save_v4_battle(record, state)
    if record.owner_user_id is not None:
        claim_combat_reward(db, match=state, user_id=record.owner_user_id)
    return ResolvedPlanningMatch(
        state=state,
        events=events,
        resolved_turn=resolved_turn,
    )


def resolve_expired_planning_matches(
    db: Session,
    *,
    now: datetime | None = None,
) -> list[ResolvedPlanningMatch]:
    checked_at = now or datetime.now(UTC)
    db.flush()
    records = list(
        db.scalars(
            select(CombatMatchRecord).where(
                CombatMatchRecord.status == MatchLifecycleStatus.PLANNING.value,
            )
        )
    )
    resolved_matches: list[ResolvedPlanningMatch] = []
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
