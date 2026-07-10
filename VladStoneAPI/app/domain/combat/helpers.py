from app.domain.combat.models import MatchState, PlayerState, Position, UnitState


def unit_at(units: list[UnitState], position: Position) -> UnitState | None:
    for unit in units:
        if unit.current_hp <= 0:
            continue
        if unit.position.row == position.row and unit.position.col == position.col:
            return unit
    return None


def player_by_id(match: MatchState, player_id: str) -> PlayerState:
    for player in match.players:
        if player.id == player_id:
            return player
    raise ValueError(f"Unknown player {player_id}")


def human_players(match: MatchState) -> list[PlayerState]:
    return [player for player in match.players if not player.is_bot]


def bot_players(match: MatchState) -> list[PlayerState]:
    return [player for player in match.players if player.is_bot]
