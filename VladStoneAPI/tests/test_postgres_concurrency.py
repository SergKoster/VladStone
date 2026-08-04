"""PostgreSQL-only proof for row locks used by future matchmaking services."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import CombatActiveSlot, CombatMatchRecord, PlayerProfile, User
from app.db.session import SessionLocal, engine
from app.domain.combat.engine.battle import create_v4_battle
from app.main import create_app
from app.services.battle_admission import BattleAdmissionService
from app.services.combat_matches import create_combat_match_record
from app.services.profiles import HandleUnavailable, set_profile_handle


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
                select(CombatMatchRecord).where(CombatMatchRecord.id == match.id).with_for_update()
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


def test_case_insensitive_handle_race_has_one_owner() -> None:
    if engine.dialect.name != "postgresql":
        pytest.skip("requires TEST_DATABASE_URL pointing to PostgreSQL")

    create_app()
    with SessionLocal.begin() as session:
        users = [User(email=f"handle-race-{uuid4().hex}@example.com") for _ in range(2)]
        session.add_all(users)
        session.flush()
        user_ids = [user.id for user in users]
        session.add_all(PlayerProfile(user_id=user_id) for user_id in user_ids)

    barrier = Barrier(2)

    def choose(user_id: int, display: str) -> str:
        with SessionLocal() as session:
            try:
                barrier.wait(timeout=5)
                set_profile_handle(session, user_id=user_id, handle=display)
                session.commit()
                return "ok"
            except (HandleUnavailable, IntegrityError):
                session.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [
            executor.submit(choose, user_ids[0], "Race_Name"),
            executor.submit(choose, user_ids[1], "race_name"),
        ]
        assert sorted(result.result(timeout=5) for result in outcomes) == ["conflict", "ok"]


def test_parallel_pve_admission_keeps_one_current_match() -> None:
    if engine.dialect.name != "postgresql":
        pytest.skip("requires TEST_DATABASE_URL pointing to PostgreSQL")

    create_app()
    with SessionLocal.begin() as session:
        user = User(email=f"admission-race-{uuid4().hex}@example.com")
        session.add(user)
        session.flush()
        user_id = user.id

    barrier = Barrier(2)

    def start_from_tab() -> tuple[str, bool]:
        with SessionLocal() as session:
            barrier.wait(timeout=5)
            admitted = BattleAdmissionService(session).admit_new_match(
                user_id=user_id,
                owner_user_id=user_id,
                build_state=lambda: create_v4_battle(
                    match_id=f"postgres_admission_{uuid4().hex}",
                    user_id=user_id,
                ),
            )
            session.commit()
            return admitted.record.id, admitted.created

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [executor.submit(start_from_tab), executor.submit(start_from_tab)]
        resolved = [future.result(timeout=5) for future in outcomes]

    assert {match_id for match_id, _ in resolved}
    assert len({match_id for match_id, _ in resolved}) == 1
    assert sorted(created for _, created in resolved) == [False, True]
    with SessionLocal() as session:
        slots = list(
            session.scalars(
                select(CombatActiveSlot).where(CombatActiveSlot.user_id == user_id)
            )
        )
        assert len(slots) == 1 and slots[0].match_id == resolved[0][0]
