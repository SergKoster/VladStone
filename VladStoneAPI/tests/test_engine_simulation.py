from app.domain.combat.engine.battle import JUDGEMENT_TURN
from app.domain.combat.engine.simulation import run_baseline_bot_match


def test_baseline_bot_simulation_is_seed_deterministic_and_finite() -> None:
    first = run_baseline_bot_match(42)
    again = run_baseline_bot_match(42)

    assert first == again
    assert 1 <= first.turns_resolved <= JUDGEMENT_TURN
    assert set(first.tower_hp_by_team) == {0, 1}
    assert all(len(hp) <= 5 for hp in first.tower_hp_by_team.values())
