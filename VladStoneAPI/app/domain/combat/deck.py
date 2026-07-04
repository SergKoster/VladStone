import random

from app.domain.combat.cards import DECK_CARD_IDS
from app.domain.combat.models import MatchState

HAND_START_SIZE = 3


def init_player_deck(match: MatchState, *, rng: random.Random | None = None) -> MatchState:
    """Shuffle the pre-built deck and deal the starting hand."""
    deck = list(DECK_CARD_IDS)
    (rng or random).shuffle(deck)
    match.player_hand = deck[:HAND_START_SIZE]
    match.player_deck = deck[HAND_START_SIZE:]
    return match


def draw_card(match: MatchState, *, rng: random.Random | None = None) -> str | None:
    """Move the top deck card into the hand; reshuffle when the deck runs out.

    The reshuffled deck is rebuilt from the full card list minus what is still
    in hand, so the "no duplicates" invariant of the test deck holds.
    """
    if not match.player_deck:
        remaining = [card_id for card_id in DECK_CARD_IDS if card_id not in match.player_hand]
        (rng or random).shuffle(remaining)
        match.player_deck = remaining
    if not match.player_deck:
        return None
    drawn = match.player_deck.pop(0)
    match.player_hand.append(drawn)
    return drawn


def covers_hand(match: MatchState, card_ids: list[str]) -> bool:
    """True if the hand can cover all requested cards (multiset containment)."""
    hand = list(match.player_hand)
    for card_id in card_ids:
        if card_id not in hand:
            return False
        hand.remove(card_id)
    return True
