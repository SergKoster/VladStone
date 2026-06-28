from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EmailLoginCode, IdentityProvider, RefreshSession, User
from app.services.accounts import audit, get_or_create_user_for_identity, normalize_email
from app.services.security import generate_code, generate_token, hash_secret

CODE_TTL_MINUTES = 10
REFRESH_TTL_DAYS = 30


def request_email_code(db: Session, email: str) -> str:
    code = generate_code()
    db.add(
        EmailLoginCode(
            email=normalize_email(email),
            code_hash=hash_secret(code),
            expires_at=datetime.now(UTC) + timedelta(minutes=CODE_TTL_MINUTES),
        )
    )
    audit(db, None, "auth.email_code_requested", {"email": normalize_email(email)})
    return code


def verify_email_code(db: Session, email: str, code: str) -> User | None:
    normalized_email = normalize_email(email)
    now = datetime.now(UTC)
    login_code = db.scalar(
        select(EmailLoginCode)
        .where(
            EmailLoginCode.email == normalized_email,
            EmailLoginCode.code_hash == hash_secret(code),
            EmailLoginCode.consumed_at.is_(None),
            EmailLoginCode.expires_at > now,
        )
        .order_by(EmailLoginCode.created_at.desc())
    )
    if login_code is None:
        return None

    login_code.consumed_at = now
    user = get_or_create_user_for_identity(
        db,
        email=normalized_email,
        provider=IdentityProvider.EMAIL,
        provider_user_id=normalized_email,
    )
    audit(db, user.id, "auth.email_login_verified", {"email": normalized_email})
    return user


def create_refresh_session(db: Session, user: User) -> tuple[str, RefreshSession]:
    token = generate_token()
    session = RefreshSession(
        user_id=user.id,
        token_hash=hash_secret(token),
        expires_at=datetime.now(UTC) + timedelta(days=REFRESH_TTL_DAYS),
    )
    db.add(session)
    audit(db, user.id, "auth.session_created", {})
    return token, session


def create_access_token_for_user(user: User) -> str:
    return generate_token()


def get_user_by_refresh_token(db: Session, refresh_token: str) -> User | None:
    session = db.scalar(
        select(RefreshSession).where(
            RefreshSession.token_hash == hash_secret(refresh_token),
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > datetime.now(UTC),
        )
    )
    if session is None:
        return None
    return db.get(User, session.user_id)


def revoke_refresh_token(db: Session, refresh_token: str) -> bool:
    session = db.scalar(
        select(RefreshSession).where(
            RefreshSession.token_hash == hash_secret(refresh_token),
            RefreshSession.revoked_at.is_(None),
        )
    )
    if session is None:
        return False
    session.revoked_at = datetime.now(UTC)
    return True
