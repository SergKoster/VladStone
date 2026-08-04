"""one active combat slot per account

Revision ID: 0005_active_match_slots
Revises: 0004_profile_handles
Create Date: 2026-08-04 00:00:00
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_active_match_slots"
down_revision: str | None = "0004_profile_handles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table(
        "combat_active_slots",
        sa.Column("user_id", sa.Integer(), nullable=False),
        # NULL exists only during the admission transaction, before the newly
        # created match has an id to attach to the locked slot.
        sa.Column("match_id", sa.String(length=96), nullable=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["combat_matches.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index("ix_combat_active_slots_match_id", "combat_active_slots", ["match_id"])

    # Existing deployments may have several active rows for one account.  The
    # approved migration rule is newest-wins: walk matches newest-first and
    # keep a row only while every participant still has no newer slot.  A match
    # conflicting for even one participant is expired for everyone, avoiding a
    # split PvP match where only one seat still believes it is active.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, owner_user_id, state_json
            FROM combat_matches
            WHERE status IN ('waiting_for_opponent', 'planning', 'resolving')
            ORDER BY updated_at DESC, created_at DESC, id DESC
            """
        )
    ).mappings()
    assigned_users: set[int] = set()
    for row in rows:
        participant_ids = [
            value
            for value in bind.execute(
                sa.text("SELECT user_id FROM combat_match_participants WHERE match_id = :match_id"),
                {"match_id": row["id"]},
            ).scalars()
            if value is not None
        ]
        if not participant_ids and row["owner_user_id"] is not None:
            participant_ids = [row["owner_user_id"]]
        participant_ids = list(dict.fromkeys(participant_ids))
        if any(user_id in assigned_users for user_id in participant_ids):
            _expire_match(bind, row["id"], row["state_json"])
            continue
        for user_id in participant_ids:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO combat_active_slots (user_id, match_id, acquired_at)
                    VALUES (:user_id, :match_id, CURRENT_TIMESTAMP)
                    """
                ),
                {"user_id": user_id, "match_id": row["id"]},
            )
            assigned_users.add(user_id)


def downgrade() -> None:
    op.drop_index("ix_combat_active_slots_match_id", table_name="combat_active_slots")
    op.drop_table("combat_active_slots")


def _expire_match(bind, match_id: str, state_json: str) -> None:
    try:
        raw = json.loads(state_json)
    except json.JSONDecodeError:
        raw = {}
    raw["status"] = "expired"
    raw["planning_deadline"] = None
    raw.setdefault("result", {})["status"] = "expired"
    bind.execute(
        sa.text(
            "UPDATE combat_matches SET status = 'expired', state_json = :state_json "
            "WHERE id = :match_id"
        ),
        {"match_id": match_id, "state_json": json.dumps(raw, ensure_ascii=False)},
    )
