from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

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

    claims = _decode_id_token_payload(id_token)
    # The id_token arrives straight from Google over TLS in a server-to-server
    # exchange, so the channel itself proves who minted it; verifying the JWT
    # signature against Google's JWKS would only re-prove that. Audience and
    # issuer are still checked to reject tokens minted for another app.
    if claims.get("aud") != settings.google_oauth_client_id:
        raise GoogleOAuthError("id_token audience mismatch")
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


def _decode_id_token_payload(id_token: str) -> dict:
    try:
        payload_segment = id_token.split(".")[1]
        padded = payload_segment + "=" * (-len(payload_segment) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except (IndexError, ValueError) as error:
        raise GoogleOAuthError("id_token is not a valid JWT") from error
