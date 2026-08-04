"""public profile handles and onboarding state

Revision ID: 0004_profile_handles
Revises: 0003_pvp_invites
Create Date: 2026-08-04 00:00:00
"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0004_profile_handles"
down_revision: str | None = "0003_pvp_invites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{3,25}$")


def upgrade() -> None:
    op.add_column(
        "player_profiles",
        sa.Column("onboarding_required", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_table(
        "profile_handles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("handle_key", sa.String(length=25), nullable=False),
        sa.Column("display_handle", sa.String(length=25), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_profile_handles_user_id", "profile_handles", ["user_id"])
    op.create_index("ix_profile_handles_handle_key", "profile_handles", ["handle_key"], unique=True)
    op.create_index(
        "uq_profile_handles_current_user",
        "profile_handles",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current = 1"),
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, user_id, nickname FROM player_profiles ORDER BY id")
    ).mappings()
    reserved: set[str] = set()
    now = datetime.now(UTC)
    handles = sa.table(
        "profile_handles",
        sa.column("user_id", sa.Integer()),
        sa.column("handle_key", sa.String()),
        sa.column("display_handle", sa.String()),
        sa.column("is_current", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    for row in rows:
        display = row["nickname"]
        key = display.lower() if display else ""
        if display and display != "Player" and HANDLE_RE.fullmatch(display) and key not in reserved:
            bind.execute(
                handles.insert().values(
                    user_id=row["user_id"],
                    handle_key=key,
                    display_handle=display,
                    is_current=True,
                    created_at=now,
                )
            )
            bind.execute(
                sa.text(
                    "UPDATE player_profiles SET onboarding_required = :required WHERE id = :id"
                ),
                {"required": False, "id": row["id"]},
            )
            reserved.add(key)


def downgrade() -> None:
    op.drop_index("uq_profile_handles_current_user", table_name="profile_handles")
    op.drop_index("ix_profile_handles_handle_key", table_name="profile_handles")
    op.drop_index("ix_profile_handles_user_id", table_name="profile_handles")
    op.drop_table("profile_handles")
    op.drop_column("player_profiles", "onboarding_required")
