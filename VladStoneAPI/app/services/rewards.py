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

    profile.coins += match.result.reward_coins
    db.add(
        CombatRewardClaim(
            user_id=user_id,
            match_id=match.id,
            coins=match.result.reward_coins,
            result="win" if match.result.winner_id == "player" else "loss",
        )
    )
    return True
