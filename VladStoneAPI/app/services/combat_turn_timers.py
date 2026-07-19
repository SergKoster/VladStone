import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.db.models import CombatMatchRecord
from app.domain.combat.engine.apply import EngineEvent
from app.domain.combat.engine.battle import (
    BattleStateV4,
    is_early_resolve_due,
    pending_intents_for,
    resolve_v4_turn,
)
from app.domain.combat.helpers import human_players
from app.domain.combat.models import MatchLifecycleStatus
from app.domain.combat.timing import is_planning_deadline_expired
from app.services.combat_matches import (
    expire_combat_match_if_outdated,
    expire_combat_match_unreadable,
    load_v4_battle,
    save_v4_battle,
)
from app.services.rewards import claim_combat_reward

logger = logging.getLogger(__name__)


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
    """Дорезолв «созревшего» хода (v4): дедлайн истёк ИЛИ все готовы (V3).

    Ruleset-гейт сработал раньше в вызывающем коде (§8.7): сюда попадают только
    матчи текущей версии. AFK-игрок не блокирует бой; V3 — на дедлайне
    применяется ПОСЛЕДНИЙ присланный план человека (интент-стриминг), а не
    пустой ход; ранний резолв — когда люди готовы и окно бот-Готов (2 с)
    истекло (боты ходят внутри resolve_v4_turn).
    """
    if expire_combat_match_if_outdated(record):
        return None
    state = load_v4_battle(record)
    checked_at = now or datetime.now(UTC)
    deadline_hit = is_planning_deadline_expired(state, now=checked_at)
    if not deadline_hit and not is_early_resolve_due(state, now=checked_at):
        return None

    human = human_players(state)[0]
    resolved_turn = state.turn
    events = resolve_v4_turn(
        state,
        human_intents=pending_intents_for(state, human.id),
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
        except ValidationError:
            # State не читается текущей моделью (например, MVP-форма, ошибочно
            # сохранённая с текущим ruleset_version) — гасим запись по принципу
            # гейта §8.7. Одна битая запись НЕ должна убивать воркер: до этого
            # фикса именно так молча умирали таймеры всех матчей.
            db.rollback()
            logger.warning("timer: match %s has unreadable state; expiring it", record.id)
            expire_combat_match_unreadable(record)
            db.commit()
            continue
        except Exception:
            # Любая другая ошибка одного матча — лог и дальше по списку;
            # ленивые пути конкретного матча продолжают падать громко.
            db.rollback()
            logger.exception("timer: match %s failed to resolve", record.id)
            continue
        resolved_matches.append(resolved)
    return resolved_matches
