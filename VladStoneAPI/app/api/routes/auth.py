from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
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
from app.services.google_oauth import (
    GoogleOAuthError,
    build_authorization_url,
    exchange_code_for_claims,
    is_google_oauth_configured,
)
from app.services.rate_limit import allow_attempt
from app.services.security import generate_token

router = APIRouter(prefix="/auth", tags=["auth"])
DbSession = Annotated[Session, Depends(get_db)]
OAUTH_STATE_COOKIE = "oauth_state"
OAUTH_STATE_TTL_SECONDS = 600


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


@router.get("/providers")
def auth_providers() -> dict[str, bool]:
    settings = get_settings()
    return {
        "google": is_google_oauth_configured(settings),
        "dev_login": settings.environment == "local",
        # Codes are only visible in the dev response for now; until a real
        # email provider sends them, this login method is dev-only.
        "email_code": settings.environment == "local",
    }


@router.get("/google/login")
def google_login() -> RedirectResponse:
    settings = get_settings()
    if not is_google_oauth_configured(settings):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    # The state round-trips through Google and back; the cookie copy proves the
    # callback belongs to a flow this browser started (CSRF protection).
    state = generate_token()
    response = RedirectResponse(build_authorization_url(settings, state))
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=OAUTH_STATE_TTL_SECONDS,
    )
    return response


@router.get("/google/callback")
def google_callback(
    db: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth_state: str | None = Cookie(default=None),
) -> RedirectResponse:
    settings = get_settings()
    if not is_google_oauth_configured(settings):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if error or not code or not state or not oauth_state or state != oauth_state:
        return _google_failure_redirect(settings.frontend_url)
    try:
        claims = exchange_code_for_claims(settings, code)
    except GoogleOAuthError:
        return _google_failure_redirect(settings.frontend_url)
    if not claims.email_verified:
        return _google_failure_redirect(settings.frontend_url)

    user = get_or_create_user_for_identity(
        db,
        email=normalize_email(claims.email),
        provider=IdentityProvider.GOOGLE,
        provider_user_id=claims.subject,
    )
    refresh_token, _ = create_refresh_session(db, user)
    db.commit()
    response = RedirectResponse(settings.frontend_url)
    response.delete_cookie(OAUTH_STATE_COOKIE)
    _set_refresh_cookie(response, refresh_token)
    return response


def _google_failure_redirect(frontend_url: str) -> RedirectResponse:
    response = RedirectResponse(f"{frontend_url}/?auth_error=google")
    response.delete_cookie(OAUTH_STATE_COOKIE)
    return response


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
        secure=get_settings().cookie_secure,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )


def _user_payload(user) -> dict:
    return {
        "id": user.id,
        "email": user.email,
    }
