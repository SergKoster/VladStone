"""Цикл колоды live-движка v4.

Legacy ``domain/combat/deck.py`` привязан к MVP-каталогу. У v4 свой пул карт,
который передаёт ``EffectContext.deck_card_ids``: при пустой колоде она
собирается из карт пула, которых сейчас нет в руке (COMBAT_REWORK §19 I6).
``None`` оставлен для изолированных тестовых/скриптовых контекстов без
deck-cycle: их пустая рука не получает карты «из воздуха».
"""

import random
from collections.abc import Sequence

from app.domain.combat.models import PlayerState


def draw_v4_card(
    player: PlayerState,
    *,
    card_ids: Sequence[str] | None,
    rng: random.Random | None = None,
) -> str | None:
    """Переместить верхнюю карту в руку, пересобрав пустую v4-колоду при нужде."""
    if not player.deck:
        if card_ids is None:
            return None
        player.deck = [card_id for card_id in card_ids if card_id not in player.hand]
        (rng or random).shuffle(player.deck)
    if not player.deck:
        return None
    drawn = player.deck.pop(0)
    player.hand.append(drawn)
    return drawn
