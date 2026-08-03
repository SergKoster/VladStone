from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.routes import auth as auth_routes
from app.core.config import get_settings
from app.main import create_app
from app.services import google_oauth
from app.services.google_oauth import GoogleClaims, GoogleOAuthError


@pytest.fixture
def google_configured(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_oauth_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "test-client-secret")
    return settings


def test_providers_without_google() -> None:
    client = TestClient(create_app())
    payload = client.get("/api/auth/providers").json()
    assert payload["google"] is False
    assert payload["dev_login"] is True
    assert payload["email_code"] is True


def test_providers_with_google(google_configured) -> None:
    client = TestClient(create_app())
    assert client.get("/api/auth/providers").json()["google"] is True


def test_google_login_is_hidden_when_unconfigured() -> None:
    client = TestClient(create_app())
    response = client.get("/api/auth/google/login", follow_redirects=False)
    assert response.status_code == 404


def test_google_login_redirects_to_google_with_state(google_configured) -> None:
    client = TestClient(create_app())
    response = client.get("/api/auth/google/login", follow_redirects=False)
    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=test-client-id" in location
    state = response.cookies.get("oauth_state")
    assert state
    assert f"state={state}" in location


def test_google_callback_logs_user_in(google_configured, monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(create_app())
    login = client.get("/api/auth/google/login", follow_redirects=False)
    state = login.cookies["oauth_state"]
    email = f"oauth-{uuid4().hex}@example.com"
    monkeypatch.setattr(
        auth_routes,
        "exchange_code_for_claims",
        lambda settings, code: GoogleClaims(
            subject=f"google-sub-{uuid4().hex}",
            email=email,
            email_verified=True,
        ),
    )

    callback = client.get(
        "/api/auth/google/callback",
        params={"code": "test-code", "state": state},
        follow_redirects=False,
    )

    assert callback.status_code == 307
    assert callback.headers["location"] == google_configured.frontend_url
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["email"] == email


def test_google_callback_rejects_state_mismatch(
    google_configured, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = TestClient(create_app())
    client.get("/api/auth/google/login", follow_redirects=False)

    def _must_not_be_called(settings, code):
        raise AssertionError("code exchange must not run when state mismatches")

    monkeypatch.setattr(auth_routes, "exchange_code_for_claims", _must_not_be_called)

    callback = client.get(
        "/api/auth/google/callback",
        params={"code": "test-code", "state": "forged-state"},
        follow_redirects=False,
    )

    assert callback.status_code == 307
    assert "auth_error=google" in callback.headers["location"]
    assert client.get("/api/me").status_code == 401


def test_google_callback_rejects_unverified_email(
    google_configured, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = TestClient(create_app())
    login = client.get("/api/auth/google/login", follow_redirects=False)
    state = login.cookies["oauth_state"]
    monkeypatch.setattr(
        auth_routes,
        "exchange_code_for_claims",
        lambda settings, code: GoogleClaims(
            subject="google-sub-unverified",
            email="unverified@example.com",
            email_verified=False,
        ),
    )

    callback = client.get(
        "/api/auth/google/callback",
        params={"code": "test-code", "state": state},
        follow_redirects=False,
    )

    assert "auth_error=google" in callback.headers["location"]
    assert client.get("/api/me").status_code == 401


def test_google_callback_handles_exchange_failure(
    google_configured, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = TestClient(create_app())
    login = client.get("/api/auth/google/login", follow_redirects=False)
    state = login.cookies["oauth_state"]

    def _failing_exchange(settings, code):
        raise GoogleOAuthError("boom")

    monkeypatch.setattr(auth_routes, "exchange_code_for_claims", _failing_exchange)

    callback = client.get(
        "/api/auth/google/callback",
        params={"code": "test-code", "state": state},
        follow_redirects=False,
    )

    assert "auth_error=google" in callback.headers["location"]
    assert client.get("/api/me").status_code == 401


def test_exchange_verifies_google_id_token(
    google_configured, monkeypatch: pytest.MonkeyPatch
) -> None:
    class TokenResponse:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {"id_token": "signed.google.jwt"}

    monkeypatch.setattr(google_oauth.httpx, "post", lambda *args, **kwargs: TokenResponse())
    verified: dict[str, object] = {}

    def verify(id_token, request, audience):
        verified.update(id_token=id_token, request=request, audience=audience)
        return {
            "iss": "https://accounts.google.com",
            "sub": "subject",
            "email": "verified@example.com",
            "email_verified": True,
        }

    monkeypatch.setattr(google_oauth, "verify_oauth2_token", verify)

    claims = google_oauth.exchange_code_for_claims(google_configured, "auth-code")

    assert claims == GoogleClaims("subject", "verified@example.com", True)
    assert verified["id_token"] == "signed.google.jwt"
    assert verified["audience"] == "test-client-id"


def test_exchange_rejects_unverifiable_google_id_token(
    google_configured, monkeypatch: pytest.MonkeyPatch
) -> None:
    class TokenResponse:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {"id_token": "forged.jwt"}

    monkeypatch.setattr(google_oauth.httpx, "post", lambda *args, **kwargs: TokenResponse())
    monkeypatch.setattr(
        google_oauth,
        "verify_oauth2_token",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad signature")),
    )

    with pytest.raises(GoogleOAuthError, match="verification failed"):
        google_oauth.exchange_code_for_claims(google_configured, "auth-code")
