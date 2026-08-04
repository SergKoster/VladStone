"""durable FIFO quick-match queue

Revision ID: 0006_quick_matchmaking
Revises: 0005_active_match_slots
Create Date: 2026-08-04 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_quick_matchmaking"
down_revision: str | None = "0005_active_match_slots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quick_matchmaking_entries",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("matched_match_id", sa.String(length=96), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["matched_match_id"], ["combat_matches.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index("ix_quick_matchmaking_entries_status", "quick_matchmaking_entries", ["status"])
    op.create_index(
        "ix_quick_matchmaking_entries_matched_match_id",
        "quick_matchmaking_entries",
        ["matched_match_id"],
    )
    op.create_index(
        "ix_quick_matchmaking_waiting_joined_at",
        "quick_matchmaking_entries",
        ["joined_at"],
        postgresql_where=sa.text("status = 'waiting'"),
        sqlite_where=sa.text("status = 'waiting'"),
    )


def downgrade() -> None:
    op.drop_index("ix_quick_matchmaking_waiting_joined_at", table_name="quick_matchmaking_entries")
    op.drop_index(
        "ix_quick_matchmaking_entries_matched_match_id",
        table_name="quick_matchmaking_entries",
    )
    op.drop_index("ix_quick_matchmaking_entries_status", table_name="quick_matchmaking_entries")
    op.drop_table("quick_matchmaking_entries")
