from datetime import datetime
from uuid import uuid4

from app.domain.combat.board import add_turn_mana
from app.domain.combat.cards import BRUISER_CARD, RANGER_CARD
from app.domain.combat.constants import RULESET_VERSION
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


def create_demo_match() -> MatchState:
    top_player = PlayerState(
        id="player_top",
        side=PlayerSide.TOP,
        mana=2,
        hero=HeroState(owner_id="player_top", side=PlayerSide.TOP),
    )
    bottom_player = PlayerState(
        id="player_bottom",
        side=PlayerSide.BOTTOM,
        mana=2,
        hero=HeroState(owner_id="player_bottom", side=PlayerSide.BOTTOM),
    )
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


def create_player_match(*, now: datetime | None = None) -> MatchState:
    player = PlayerState(
        id="player",
        side=PlayerSide.BOTTOM,
        mana=add_turn_mana(0, 1),
        hero=HeroState(owner_id="player", side=PlayerSide.BOTTOM),
    )
    bot = PlayerState(
        id="bot",
        side=PlayerSide.TOP,
        mana=add_turn_mana(0, 1),
        hero=HeroState(owner_id="bot", side=PlayerSide.TOP),
    )
    match = MatchState(
        id=f"local_pve_{uuid4().hex}",
        ruleset_version=RULESET_VERSION,
        players=[bot, player],
    )
    return start_planning_timer(match, now=now)
