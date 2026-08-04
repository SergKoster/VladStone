"""PostgreSQL-only proof for row locks used by future matchmaking services."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models import CombatMatchRecord
from app.db.session import SessionLocal, engine
from app.domain.combat.engine.battle import create_v4_battle
from app.main import create_app
from app.services.combat_matches import create_combat_match_record


def test_skip_locked_uses_two_real_postgres_transactions() -> None:
    """A second worker must skip a record locked by the first transaction."""
    if engine.dialect.name != "postgresql":
        pytest.skip("requires TEST_DATABASE_URL pointing to PostgreSQL")

    create_app()
    match = create_v4_battle(match_id=f"postgres_lock_{uuid4().hex}")
    with SessionLocal() as session:
        create_combat_match_record(session, match=match, owner_user_id=None)
        session.commit()

    lock_acquired = Event()
    release_lock = Event()

    def hold_lock() -> None:
        with SessionLocal.begin() as session:
            locked = session.scalar(
                select(CombatMatchRecord)
                .where(CombatMatchRecord.id == match.id)
                .with_for_update()
            )
            assert locked is not None
            lock_acquired.set()
            assert release_lock.wait(timeout=5)

    def skip_locked_record() -> CombatMatchRecord | None:
        assert lock_acquired.wait(timeout=5)
        with SessionLocal.begin() as session:
            return session.scalar(
                select(CombatMatchRecord)
                .where(CombatMatchRecord.id == match.id)
                .with_for_update(skip_locked=True)
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        holder = executor.submit(hold_lock)
        skipped = executor.submit(skip_locked_record)
        assert skipped.result(timeout=5) is None
        release_lock.set()
        holder.result(timeout=5)
