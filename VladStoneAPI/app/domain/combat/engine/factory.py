"""Создание участников матча v4 и раздача стартовой колоды.

Участник (models.PlayerState) общий у MVP и v4 (R12); здесь — v4-раздача из
DECK_CARD_IDS_V4 и per-player стойка стороны из команды.
"""

import random

from app.domain.combat.board import side_for_team
from app.domain.combat.engine.content import DECK_CARD_IDS_V4
from app.domain.combat.models import HeroState, PlayerState


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
        # «Герой» как HP-объект в v4 не используется (роль перешла к 5 башням,
        # §17) — держим дефолт ради общей модели участника с MVP.
        hero=HeroState(owner_id=player_id, side=side),
    )


def deal_v4_hand(player: PlayerState, *, hand_size: int = 3, rng: random.Random | None = None):
    """Перетасовать v4-колоду и раздать стартовую руку (первые hand_size карт)."""
    deck = list(DECK_CARD_IDS_V4)
    (rng or random).shuffle(deck)
    player.hand = deck[:hand_size]
    player.deck = deck[hand_size:]
    return player
