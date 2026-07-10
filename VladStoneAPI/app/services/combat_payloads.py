from app.domain.combat.helpers import human_players
from app.domain.combat.models import MatchState


def combat_response(match: MatchState, *, viewer_id: str | None = None) -> dict:
    """Serialize a match for one client (payloads are viewer-specific).

    Anti-cheat invariants: a deck's order and contents never leave the server
    (only deck_count does), and a hand is serialized only to its owner — other
    participants see just hand_count.

    ``viewer_id`` defaults to the match's single human seat (PvE convenience);
    PvP must pass the recipient explicitly.
    """
    if viewer_id is None:
        humans = human_players(match)
        viewer_id = humans[0].id if humans else None
    match_snapshot = match.model_copy(update={"events": []})
    match_payload = match_snapshot.model_dump(mode="json")
    for player_payload, player in zip(match_payload["players"], match.players, strict=True):
        del player_payload["deck"]
        player_payload["deck_count"] = len(player.deck)
        player_payload["hand_count"] = len(player.hand)
        if player.id != viewer_id:
            player_payload["hand"] = []
        # Account ids are server-side bookkeeping, not client data.
        del player_payload["user_id"]
    match_payload["viewer_id"] = viewer_id
    return {
        "match": match_payload,
        "events": [event.model_dump(mode="json") for event in match.events],
    }
