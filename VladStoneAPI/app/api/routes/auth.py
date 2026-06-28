from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.schemas import (
    AuthResponse,
    EmailCodeRequest,
    EmailCodeResponse,
    EmailVerifyRequest,
    GoogleDevLoginRequest,
)
from app.core.config import get_settings
from app.db.models import IdentityProvider
from app.db.session import get_db
from app.services.accounts import get_or_create_user_for_identity, normalize_email
from app.services.auth import (
    create_access_token_for_user,
    create_refresh_session,
    request_email_code,
    revoke_refresh_token,
    verify_email_code,
)
from app.services.rate_limit import allow_attempt

router = APIRouter(prefix="/auth", tags=["auth"])
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/email/request", response_model=EmailCodeResponse)
def request_email_login(payload: EmailCodeRequest, db: DbSession) -> EmailCodeResponse:
    if not allow_attempt(f"email-code:{payload.email}"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts",
        )
    code = request_email_code(db, str(payload.email))
    db.commit()
    settings = get_settings()
    return EmailCodeResponse(
        ok=True,
        dev_code=code if settings.environment == "local" else None,
    )


@router.post("/email/verify", response_model=AuthResponse)
def verify_email_login(
    payload: EmailVerifyRequest,
    response: Response,
    db: DbSession,
) -> AuthResponse:
    user = verify_email_code(db, str(payload.email), payload.code)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")

    refresh_token, _ = create_refresh_session(db, user)
    access_token = create_access_token_for_user(user)
    db.commit()
    _set_refresh_cookie(response, refresh_token)
    return AuthResponse(access_token=access_token, user=_user_payload(user))


@router.post("/google/dev-login", response_model=AuthResponse)
def google_dev_login(
    payload: GoogleDevLoginRequest,
    response: Response,
    db: DbSession,
) -> AuthResponse:
    settings = get_settings()
    if settings.environment != "local":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    email = normalize_email(str(payload.email))
    user = get_or_create_user_for_identity(
        db,
        email=email,
        provider=IdentityProvider.GOOGLE,
        provider_user_id=email,
    )
    refresh_token, _ = create_refresh_session(db, user)
    access_token = create_access_token_for_user(user)
    db.commit()
    _set_refresh_cookie(response, refresh_token)
    return AuthResponse(access_token=access_token, user=_user_payload(user))


@router.post("/logout")
def logout(
    response: Response,
    db: DbSession,
    refresh_token: str | None = Cookie(default=None),
) -> dict[str, bool]:
    if refresh_token:
        revoke_refresh_token(db, refresh_token)
        db.commit()
    response.delete_cookie("refresh_token")
    return {"ok": True}


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )


def _user_payload(user) -> dict:
    return {
        "id": user.id,
        "email": user.email,
    }
