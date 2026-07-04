from app.domain.combat.models import MatchState


def combat_response(match: MatchState) -> dict:
    match_snapshot = match.model_copy(update={"events": []})
    # Deck order is a server-side secret (the player must not see the next
    # draw): expose only the number of cards left in the deck.
    match_payload = match_snapshot.model_dump(mode="json", exclude={"player_deck"})
    match_payload["deck_count"] = len(match.player_deck)
    return {
        "match": match_payload,
        "events": [event.model_dump(mode="json") for event in match.events],
    }
