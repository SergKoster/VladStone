"""Детерминированные baseline-симуляции текущего PvE-правила v4.

Это измерительный инструмент, а не балансировщик: он не меняет карты, правила
или решения O10. Стратегия обоих участников — существующий легальный бот, а
seed фиксирует порядок стартовых рук для сравнения будущих изменений.
"""

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.domain.combat.engine.battle import (
    BattleStateV4,
    build_context,
    create_v4_battle,
    resolve_v4_turn,
)
from app.domain.combat.engine.bot import plan_bot_intents
from app.domain.combat.engine.towers import towers_of
from app.domain.combat.models import MatchLifecycleStatus

SIMULATION_EPOCH = datetime(2026, 8, 3, tzinfo=UTC)


@dataclass(frozen=True)
class SimulationResult:
    seed: int
    turns_resolved: int
    winner_team: int | None
    tower_hp_by_team: dict[int, tuple[int, ...]]


def run_baseline_bot_match(seed: int) -> SimulationResult:
    """Разыграть текущий v4 PvE-матч до нокаута или суда.

    Человек получает намерения того же deterministic bot, что и штатный
    соперник. Так симуляция проверяет live pipeline `battle → bot → resolver`,
    а не отдельную упрощённую модель правил.
    """
    rng = random.Random(seed)
    state = create_v4_battle(
        match_id=f"simulation_{seed:08d}",
        now=SIMULATION_EPOCH,
        rng=rng,
    )
    while state.status == MatchLifecycleStatus.PLANNING:
        human = next(player for player in state.players if not player.is_bot)
        human_intents = plan_bot_intents(build_context(state, rng=rng), human.id)
        resolve_v4_turn(
            state,
            human_intents=human_intents,
            now=SIMULATION_EPOCH + timedelta(seconds=state.turn),
            rng=rng,
        )
    return _result(state, seed)


def _result(state: BattleStateV4, seed: int) -> SimulationResult:
    ctx = build_context(state)
    tower_hp_by_team = {
        player.team: tuple(sorted(tower.current_hp for tower in towers_of(ctx, player.id)))
        for player in state.players
    }
    return SimulationResult(
        seed=seed,
        turns_resolved=state.last_resolved_turn or 0,
        winner_team=state.result.winner_team,
        tower_hp_by_team=tower_hp_by_team,
    )
