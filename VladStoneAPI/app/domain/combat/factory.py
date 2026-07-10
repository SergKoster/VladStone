from datetime import datetime
from uuid import uuid4

from app.domain.combat.board import add_turn_mana, side_for_team
from app.domain.combat.cards import BRUISER_CARD, RANGER_CARD
from app.domain.combat.constants import RULESET_VERSION
from app.domain.combat.deck import init_player_deck
from app.domain.combat.models import (
    CardDefinition,
    HeroState,
    MatchState,
    PlayerSide,
    PlayerState,
    Position,
    UnitState,
)
from app.domain.combat.timing import start_planning_timer


def create_unit(
    *,
    unit_id: str,
    owner_id: str,
    side: PlayerSide,
    card: CardDefinition,
    position: Position,
) -> UnitState:
    return UnitState(
        id=unit_id,
        owner_id=owner_id,
        side=side,
        card_id=card.id,
        position=position,
        stats=card.stats,
        current_hp=card.stats.hp,
        remaining_steps=card.stats.move_steps,
        remaining_attacks=card.stats.attacks,
    )


def create_participant(
    *,
    player_id: str,
    team: int,
    is_bot: bool = False,
    user_id: int | None = None,
    mana: int = 0,
) -> PlayerState:
    side = side_for_team(team)
    return PlayerState(
        id=player_id,
        side=side,
        team=team,
        is_bot=is_bot,
        user_id=user_id,
        mana=mana,
        hero=HeroState(owner_id=player_id, side=side),
    )


def create_demo_match() -> MatchState:
    top_player = create_participant(player_id="player_top", team=1, mana=2)
    bottom_player = create_participant(player_id="player_bottom", team=0, mana=2)
    return MatchState(
        id="demo",
        ruleset_version=RULESET_VERSION,
        players=[top_player, bottom_player],
        units=[
            create_unit(
                unit_id="top_ranger",
                owner_id=top_player.id,
                side=top_player.side,
                card=RANGER_CARD,
                position=Position(row=1, col=1),
            ),
            create_unit(
                unit_id="bottom_bruiser",
                owner_id=bottom_player.id,
                side=bottom_player.side,
                card=BRUISER_CARD,
                position=Position(row=3, col=1),
            ),
        ],
    )


def create_player_match(
    *,
    user_id: int | None = None,
    now: datetime | None = None,
) -> MatchState:
    # Seat ids are neutral on purpose: nothing may key logic off "player"/"bot"
    # (R12) — participants are found by is_bot / user_id / team instead.
    human = create_participant(
        player_id="p1",
        team=0,
        user_id=user_id,
        mana=add_turn_mana(0, 1),
    )
    bot = create_participant(
        player_id="p2",
        team=1,
        is_bot=True,
        mana=add_turn_mana(0, 1),
    )
    match = MatchState(
        id=f"local_pve_{uuid4().hex}",
        ruleset_version=RULESET_VERSION,
        players=[bot, human],
    )
    # The scripted test bot plays a fixed pattern, not a deck; real bot decks
    # arrive with the v4 engine.
    init_player_deck(human)
    return start_planning_timer(match, now=now)
