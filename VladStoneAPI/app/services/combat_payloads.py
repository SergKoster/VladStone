from app.domain.combat.models import MatchState


def combat_response(match: MatchState) -> dict:
    match_snapshot = match.model_copy(update={"events": []})
    return {
        "match": match_snapshot.model_dump(mode="json"),
        "events": [event.model_dump(mode="json") for event in match.events],
    }
