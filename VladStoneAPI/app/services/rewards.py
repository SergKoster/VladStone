from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CombatRewardClaim, PlayerProfile
from app.domain.combat.models import MatchState


def claim_combat_reward(db: Session, *, match: MatchState, user_id: int) -> bool:
    if match.result.status != "finished" or match.result.reward_coins <= 0:
        return False

    existing_claim = db.scalar(
        select(CombatRewardClaim).where(
            CombatRewardClaim.user_id == user_id,
            CombatRewardClaim.match_id == match.id,
        )
    )
    if existing_claim is not None:
        return False

    profile = db.scalar(select(PlayerProfile).where(PlayerProfile.user_id == user_id))
    if profile is None:
        return False

    # The claiming user's seat decides win/loss; fall back to the PvE human
    # seat for matches started before seats carried a user_id.
    player = next(
        (candidate for candidate in match.players if candidate.user_id == user_id),
        None,
    ) or next((candidate for candidate in match.players if not candidate.is_bot), None)
    did_win = player is not None and player.team == match.result.winner_team

    profile.coins += match.result.reward_coins
    db.add(
        CombatRewardClaim(
            user_id=user_id,
            match_id=match.id,
            coins=match.result.reward_coins,
            result="win" if did_win else "loss",
        )
    )
    return True
