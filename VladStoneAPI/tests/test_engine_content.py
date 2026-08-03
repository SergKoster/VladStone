"""Контент-пак v4 (этап 15б): 12 карт §14.1 как данные, валидные и играбельные."""

from app.domain.combat.engine import (
    TOWER_HP,
    EffectContext,
    add_towers,
    plan_bot_intents,
    resolve_turn_v4,
    towers_of,
    validate_blueprint,
    validate_card,
    validate_spell_script,
    validate_state,
    winner_team_by_towers,
)
from app.domain.combat.engine.content import (
    BLUEPRINTS,
    CARDS,
    DECK_CARD_IDS_V4,
    SPELLS,
    V4_COLS,
    V4_ROWS,
    v4_mana_gain,
)
from app.domain.combat.models import HeroState, PlayerSide, PlayerState, Rarity


def test_content_validates_on_the_v4_board() -> None:
    # I7: весь контент обязан проходить валидацию на сиде, не в бою.
    for blueprint in BLUEPRINTS.values():
        validate_blueprint(blueprint, rows=V4_ROWS, cols=V4_COLS)
    for script in SPELLS.values():
        validate_spell_script(script, rows=V4_ROWS, cols=V4_COLS)
    for card in CARDS.values():
        validate_card(card, blueprints=BLUEPRINTS, spells=SPELLS)


def test_deck_is_all_twelve_commons_without_duplicates() -> None:
    assert len(DECK_CARD_IDS_V4) == 12
    assert len(set(DECK_CARD_IDS_V4)) == 12
    assert all(CARDS[card_id].rarity == Rarity.COMMON for card_id in DECK_CARD_IDS_V4)
    assert "samurai_koster" in DECK_CARD_IDS_V4
    assert all(card.rules_text for card in CARDS.values())


def test_mana_curve_v4() -> None:
    # +2 за ход, каждый 4-й — +3 (решение владельца).
    assert [v4_mana_gain(turn) for turn in range(1, 9)] == [2, 2, 2, 3, 2, 2, 2, 3]


def _player(player_id: str, side: PlayerSide, team: int) -> PlayerState:
    return PlayerState(
        id=player_id,
        side=side,
        team=team,
        mana=2,
        hero=HeroState(owner_id=player_id, side=side),
        deck=list(DECK_CARD_IDS_V4[3:]),
        hand=list(DECK_CARD_IDS_V4[:3]),
    )


def test_full_content_bot_match_survives_thirty_turns() -> None:
    # Дымовой матч на ПОЛНОМ контенте: оба игрока — боты v4, все карты в
    # колодах, башни на месте; validate_state работает на каждой границе.
    ctx = EffectContext(
        rows=V4_ROWS,
        cols=V4_COLS,
        units=[],
        players=[
            _player("human", PlayerSide.BOTTOM, 0),
            _player("bot", PlayerSide.TOP, 1),
        ],
        blueprints=dict(BLUEPRINTS),
        cards=dict(CARDS),
        spells=dict(SPELLS),
    )
    for player in ctx.players:
        add_towers(ctx, player)

    for turn in range(1, 31):
        if winner_team_by_towers(ctx) is not None:
            break
        intents = [plan_bot_intents(ctx, player.id) for player in ctx.players]
        resolve_turn_v4(ctx, turn=turn, spell_coin=0, intents=intents, mana_gain=v4_mana_gain)
        validate_state(ctx, checkpoint=f"turn:{turn}")

    # Бой шёл по-настоящему: у кого-то из сторон башни уже пострадали.
    tower_hp = [
        tower.current_hp
        for player in ctx.players
        for tower in towers_of(ctx, player.id)
    ]
    assert any(hp < TOWER_HP for hp in tower_hp) or winner_team_by_towers(ctx) is not None
