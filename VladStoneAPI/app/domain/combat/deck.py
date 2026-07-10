import random

from app.domain.combat.cards import DECK_CARD_IDS
from app.domain.combat.models import PlayerState

HAND_START_SIZE = 3


def init_player_deck(player: PlayerState, *, rng: random.Random | None = None) -> PlayerState:
    """Shuffle the pre-built deck and deal the player's starting hand."""
    deck = list(DECK_CARD_IDS)
    (rng or random).shuffle(deck)
    player.hand = deck[:HAND_START_SIZE]
    player.deck = deck[HAND_START_SIZE:]
    return player


def draw_card(player: PlayerState, *, rng: random.Random | None = None) -> str | None:
    """Move the top deck card into the hand; reshuffle when the deck runs out.

    The reshuffled deck is rebuilt from the full card list minus what is still
    in hand, so the "no duplicates" invariant of the test deck holds.
    """
    if not player.deck:
        remaining = [card_id for card_id in DECK_CARD_IDS if card_id not in player.hand]
        (rng or random).shuffle(remaining)
        player.deck = remaining
    if not player.deck:
        return None
    drawn = player.deck.pop(0)
    player.hand.append(drawn)
    return drawn


def covers_hand(player: PlayerState, card_ids: list[str]) -> bool:
    """True if the player's hand can cover all requested cards (multiset containment)."""
    hand = list(player.hand)
    for card_id in card_ids:
        if card_id not in hand:
            return False
        hand.remove(card_id)
    return True
