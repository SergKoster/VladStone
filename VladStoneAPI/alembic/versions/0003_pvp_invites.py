"""pvp invite lifecycle and match participants

Revision ID: 0003_pvp_invites
Revises: 0002_combat_match_version
Create Date: 2026-08-03 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_pvp_invites"
down_revision: str | None = "0002_combat_match_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "combat_match_participants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.String(length=96), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.String(length=64), nullable=False),
        sa.Column("team", sa.Integer(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["combat_matches.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_id", "user_id", name="uq_match_participants_match_user"),
        sa.UniqueConstraint("match_id", "player_id", name="uq_match_participants_match_player"),
    )
    op.create_index(
        "ix_combat_match_participants_match_id",
        "combat_match_participants",
        ["match_id"],
    )
    op.create_index(
        "ix_combat_match_participants_user_id",
        "combat_match_participants",
        ["user_id"],
    )

    op.create_table(
        "match_invites",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("match_id", sa.String(length=96), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["combat_matches.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_id"),
        sa.UniqueConstraint("token_digest"),
    )
    op.create_index("ix_match_invites_match_id", "match_invites", ["match_id"])
    op.create_index("ix_match_invites_created_by_user_id", "match_invites", ["created_by_user_id"])
    op.create_index("ix_match_invites_token_digest", "match_invites", ["token_digest"], unique=True)
    op.create_index("ix_match_invites_status", "match_invites", ["status"])
    op.create_index("ix_match_invites_expires_at", "match_invites", ["expires_at"])
    op.create_index(
        "ix_match_invites_accepted_by_user_id",
        "match_invites",
        ["accepted_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_match_invites_accepted_by_user_id", table_name="match_invites")
    op.drop_index("ix_match_invites_expires_at", table_name="match_invites")
    op.drop_index("ix_match_invites_status", table_name="match_invites")
    op.drop_index("ix_match_invites_token_digest", table_name="match_invites")
    op.drop_index("ix_match_invites_created_by_user_id", table_name="match_invites")
    op.drop_index("ix_match_invites_match_id", table_name="match_invites")
    op.drop_table("match_invites")
    op.drop_index("ix_combat_match_participants_user_id", table_name="combat_match_participants")
    op.drop_index("ix_combat_match_participants_match_id", table_name="combat_match_participants")
    op.drop_table("combat_match_participants")
