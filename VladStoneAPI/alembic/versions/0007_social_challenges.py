"""friend relationships, blocks and direct battle challenges

Revision ID: 0007_social_challenges
Revises: 0006_quick_matchmaking
Create Date: 2026-08-04 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_social_challenges"
down_revision: str | None = "0006_quick_matchmaking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "friend_relationships",
        sa.Column("user_low_id", sa.Integer(), nullable=False),
        sa.Column("user_high_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("user_low_id < user_high_id", name="ck_friend_relationships_normalized"),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted')",
            name="ck_friend_relationships_status",
        ),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_high_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_low_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_low_id", "user_high_id"),
    )
    op.create_index("ix_friend_relationships_status", "friend_relationships", ["status"])
    op.create_index(
        "ix_friend_relationships_requested_by_user_id",
        "friend_relationships",
        ["requested_by_user_id"],
    )
    op.create_table(
        "user_blocks",
        sa.Column("blocker_user_id", sa.Integer(), nullable=False),
        sa.Column("blocked_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("blocker_user_id != blocked_user_id", name="ck_user_blocks_not_self"),
        sa.ForeignKeyConstraint(["blocked_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["blocker_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("blocker_user_id", "blocked_user_id"),
    )
    op.create_table(
        "battle_challenges",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("challenger_user_id", sa.Integer(), nullable=False),
        sa.Column("challenged_user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("match_id", sa.String(length=96), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "challenger_user_id != challenged_user_id",
            name="ck_battle_challenges_not_self",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'cancelled', 'expired')",
            name="ck_battle_challenges_status",
        ),
        sa.ForeignKeyConstraint(["challenged_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["challenger_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["match_id"], ["combat_matches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_battle_challenges_challenger_user_id", "battle_challenges", ["challenger_user_id"]
    )
    op.create_index(
        "ix_battle_challenges_challenged_user_id", "battle_challenges", ["challenged_user_id"]
    )
    op.create_index("ix_battle_challenges_status", "battle_challenges", ["status"])
    op.create_index("ix_battle_challenges_expires_at", "battle_challenges", ["expires_at"])
    op.create_index("ix_battle_challenges_match_id", "battle_challenges", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_battle_challenges_match_id", table_name="battle_challenges")
    op.drop_index("ix_battle_challenges_expires_at", table_name="battle_challenges")
    op.drop_index("ix_battle_challenges_status", table_name="battle_challenges")
    op.drop_index("ix_battle_challenges_challenged_user_id", table_name="battle_challenges")
    op.drop_index("ix_battle_challenges_challenger_user_id", table_name="battle_challenges")
    op.drop_table("battle_challenges")
    op.drop_table("user_blocks")
    op.drop_index("ix_friend_relationships_requested_by_user_id", table_name="friend_relationships")
    op.drop_index("ix_friend_relationships_status", table_name="friend_relationships")
    op.drop_table("friend_relationships")
