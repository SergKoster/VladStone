"""Башни v4 (§17): 5 юнитов-башен на игрока за краем поля + винкон.

Решения владельца: HP башни — 20 (восстановлено в августе 2026 до внешнего
плейтеста; балансируется в O10 после P4);
башни стоят на «призрачных» клетках за краем (ряд −1 у верхнего игрока,
ряд rows у нижнего) — встать туда нельзя, снос клетку не открывает; юниты
бьют башни обычной атакой (башня = юнит с тегами structure/tower/immovable).

Досягаемость башни (C2): 2 клетки вглубь своей линии + ряд 1 соседних линий,
одна цель за атаку; тай-брейк башни — своя линия (ближняя раньше), иначе
самая левая на соседних (реализован в резолвере).
"""

from app.domain.combat.engine.apply import EffectContext
from app.domain.combat.engine.patterns import CellOffset, CellPattern, SpawnZone
from app.domain.combat.engine.stances import Stance, StanceProgram
from app.domain.combat.engine.tags import TAG_IMMOVABLE, TAG_STRUCTURE, TAG_TOWER
from app.domain.combat.engine.units import UnitBlueprint, UnitState, UnitStats, spawn_unit
from app.domain.combat.models import PlayerSide, PlayerState

# Стартовые числа башни — ручки баланса для плейтеста (O10).
TOWER_HP = 20
TOWER_DAMAGE = 1
TOWER_BLUEPRINT_ID = "tower_default"

# Досягаемость C2: своя линия на 2 вглубь + ряд 1 соседних линий.
TOWER_COVERAGE = CellPattern(
    offsets=(
        CellOffset(forward=1, col=0),
        CellOffset(forward=2, col=0),
        CellOffset(forward=1, col=-1),
        CellOffset(forward=1, col=1),
    )
)

TOWER_BLUEPRINT = UnitBlueprint(
    id=TOWER_BLUEPRINT_ID,
    name="Башня",
    stats=UnitStats(hp=TOWER_HP, damage=TOWER_DAMAGE, attacks_per_turn=1, move_steps=0),
    stance_program=StanceProgram.always(Stance.DEFENSE),
    coverage_defense=TOWER_COVERAGE,
    # Башни не разыгрываются с руки; зона — формальность модели.
    spawn_zone=SpawnZone(rows_from_back=(1,)),
    tags=(TAG_STRUCTURE, TAG_TOWER, TAG_IMMOVABLE),
)


def ghost_row(side: PlayerSide, rows: int) -> int:
    """Призрачный ряд башен стороны: за своим краем поля."""
    return -1 if side == PlayerSide.TOP else rows


def add_towers(ctx: EffectContext, player: PlayerState) -> list[UnitState]:
    """Поставить игроку по башне на линию (колонку) за его краем поля."""
    ctx.blueprints.setdefault(TOWER_BLUEPRINT_ID, TOWER_BLUEPRINT)
    row = ghost_row(player.side, ctx.rows)
    towers = []
    for col in range(ctx.cols):
        tower = spawn_unit(
            TOWER_BLUEPRINT,
            unit_id=f"{player.id}_tower_{col}",
            owner_id=player.id,
            side=player.side,
            row=row,
            col=col,
        )
        ctx.units.append(tower)
        towers.append(tower)
    return towers


def towers_of(ctx: EffectContext, player_id: str) -> list[UnitState]:
    return [
        unit
        for unit in ctx.units
        if unit.owner_id == player_id
        and TAG_TOWER in ctx.blueprint_of(unit).tags
    ]


def winner_team_by_towers(ctx: EffectContext) -> int | None:
    """Винкон §17 п.1: команда без единой башни выбывает; победитель —
    единственная команда с уцелевшими башнями. None — бой продолжается
    (или все выбыли разом — ничью оформляет вызывающий)."""
    teams = {player.team for player in ctx.players}
    alive_teams = {
        player.team for player in ctx.players if towers_of(ctx, player.id)
    }
    if alive_teams == teams or not alive_teams:
        return None
    if len(alive_teams) == 1:
        return next(iter(alive_teams))
    return None


def all_teams_eliminated(ctx: EffectContext) -> bool:
    return all(not towers_of(ctx, player.id) for player in ctx.players)


def run_judgement(hp_by_team: dict[int, list[int]]) -> int | None:
    """«Суд» S2 (эндшпиль вместо chip damage): исход мгновенно, лестницей §17.

    Уточнение владельца (июль 2026, вместо отменённого «итеративного сноса
    слабейших» — тот давал абсурд: 5 башен по 19 HP проигрывали одной с 20):
    (1) у кого БОЛЬШЕ уцелевших башен — победил; (2) поровну — чья слабейшая
    башня крепче (больше HP); (3) поровну — большая сумма HP всех башен;
    (4) полное равенство — ничья (= поражение обоим, H4). Вход — HP живых
    башен по командам; выход — команда-победитель или None (ничья).
    Чистая функция: тестируема и независима от контекста.
    """
    def strength(hps: list[int]) -> tuple[int, int, int]:
        return (len(hps), min(hps) if hps else 0, sum(hps))

    scored = {team: strength(hps) for team, hps in hp_by_team.items()}
    best = max(scored.values())
    winners = [team for team, score in scored.items() if score == best]
    return winners[0] if len(winners) == 1 else None
