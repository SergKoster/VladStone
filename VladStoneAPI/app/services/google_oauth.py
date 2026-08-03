from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from google.auth import exceptions as google_auth_exceptions
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.id_token import verify_oauth2_token

from app.core.config import Settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


class GoogleOAuthError(Exception):
    """Raised when the Google OAuth flow cannot be completed."""


@dataclass(frozen=True)
class GoogleClaims:
    subject: str
    email: str
    email_verified: bool


def is_google_oauth_configured(settings: Settings) -> bool:
    return bool(settings.google_oauth_client_id and settings.google_oauth_client_secret)


def build_authorization_url(settings: Settings, state: str) -> str:
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": "openid email",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_code_for_claims(settings: Settings, code: str) -> GoogleClaims:
    try:
        token_response = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.google_oauth_redirect_uri,
            },
            timeout=10,
        )
    except httpx.HTTPError as error:
        raise GoogleOAuthError("Google token endpoint is unreachable") from error
    if token_response.status_code != 200:
        raise GoogleOAuthError(f"Google token exchange failed: {token_response.status_code}")
    id_token = token_response.json().get("id_token")
    if not id_token:
        raise GoogleOAuthError("Google token response has no id_token")

    try:
        # google-auth downloads Google's public certs and validates signature,
        # audience and expiry before exposing claims. TLS alone only protects
        # the transport to token exchange; it does not validate the JWT.
        claims = verify_oauth2_token(
            id_token,
            GoogleRequest(),
            audience=settings.google_oauth_client_id,
        )
    except (ValueError, google_auth_exceptions.GoogleAuthError) as error:
        raise GoogleOAuthError("id_token verification failed") from error
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleOAuthError("id_token issuer mismatch")
    subject = claims.get("sub")
    email = claims.get("email")
    if not subject or not email:
        raise GoogleOAuthError("id_token misses sub/email claims")
    return GoogleClaims(
        subject=subject,
        email=email,
        email_verified=bool(claims.get("email_verified")),
    )
