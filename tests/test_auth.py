"""
tests/test_auth.py — Tests for app/routes/auth.py.

Covers:
  - CSRF state token generation (GET /auth/lucid sets state in memory)
  - CSRF state token validation (wrong state → auth_error=state_mismatch redirect)
  - OAuth state expiry (state older than 10 min → auth_error=state_expired redirect)
  - Same cases for the account flow (/auth/lucid-account and /callback-account)
"""

from datetime import datetime, timedelta

import pytest
import app.state as state


class TestUserOAuthInitiation:
    """GET /auth/lucid should generate a CSRF state token and store it in memory."""

    def test_initiation_redirects(self, client):
        """GET /auth/lucid must return a redirect (3xx) to Lucid's auth URL."""
        response = client.get("/auth/lucid", follow_redirects=False)
        assert response.status_code in (301, 302, 307, 308)
        assert "lucid.app" in response.headers.get("location", "")

    def test_csrf_state_stored(self, client):
        """After GET /auth/lucid, state.rest_oauth_state must be set."""
        client.get("/auth/lucid", follow_redirects=False)
        assert state.rest_oauth_state is not None
        assert len(state.rest_oauth_state) > 10  # token_urlsafe(32) → ≥32 chars

    def test_csrf_state_timestamp_stored(self, client):
        """After GET /auth/lucid, state.rest_oauth_state_created_at must be set."""
        client.get("/auth/lucid", follow_redirects=False)
        assert state.rest_oauth_state_created_at is not None
        assert isinstance(state.rest_oauth_state_created_at, datetime)


class TestUserOAuthCallback:
    """GET /callback validates CSRF state and rejects bad/expired tokens."""

    def _seed_user_state(self, token: str, age_seconds: int = 0) -> None:
        """Directly plant a state token in memory (bypassing the initiation route)."""
        state.rest_oauth_state = token
        state.rest_oauth_state_created_at = datetime.utcnow() - timedelta(seconds=age_seconds)

    def test_wrong_state_rejected(self, client):
        """Callback with wrong state must redirect with auth_error=state_mismatch."""
        self._seed_user_state("correct-state-token")
        response = client.get(
            "/callback?code=fakecode&state=wrong-state-token",
            follow_redirects=False,
        )
        location = response.headers.get("location", "")
        assert "state_mismatch" in location

    def test_expired_state_rejected(self, client):
        """Callback with an expired state (> 10 min old) must redirect with state_expired."""
        self._seed_user_state("valid-token", age_seconds=601)
        response = client.get(
            "/callback?code=fakecode&state=valid-token",
            follow_redirects=False,
        )
        location = response.headers.get("location", "")
        assert "state_expired" in location

    def test_expired_state_clears_memory(self, client):
        """After an expired-state rejection, state.rest_oauth_state should be cleared."""
        self._seed_user_state("valid-token", age_seconds=601)
        client.get(
            "/callback?code=fakecode&state=valid-token",
            follow_redirects=False,
        )
        assert state.rest_oauth_state is None
        assert state.rest_oauth_state_created_at is None

    def test_fresh_state_passes_csrf_check(self, client):
        """A fresh state token must pass the expiry gate (and then hit the code exchange)."""
        self._seed_user_state("fresh-token", age_seconds=0)
        response = client.get(
            "/callback?code=fakecode&state=fresh-token",
            follow_redirects=False,
        )
        location = response.headers.get("location", "")
        # Should NOT fail with state_mismatch or state_expired — it will fail at
        # the token exchange step (no real Lucid server), so we accept either
        # auth_success or token_exchange errors but not CSRF errors.
        assert "state_mismatch" not in location
        assert "state_expired" not in location

    def test_no_code_returns_error(self, client):
        """Callback with no code parameter must redirect with a descriptive error."""
        self._seed_user_state("any-token")
        response = client.get("/callback?state=any-token", follow_redirects=False)
        location = response.headers.get("location", "")
        assert response.status_code in (301, 302, 307, 308)
        assert "no_code" in location or "error" in location


class TestAccountOAuthInitiation:
    """GET /auth/lucid-account should generate a CSRF state token."""

    def test_initiation_redirects(self, client):
        response = client.get("/auth/lucid-account", follow_redirects=False)
        assert response.status_code in (301, 302, 307, 308)
        assert "lucid.app" in response.headers.get("location", "")

    def test_csrf_state_stored(self, client):
        client.get("/auth/lucid-account", follow_redirects=False)
        assert state.rest_account_oauth_state is not None

    def test_csrf_state_timestamp_stored(self, client):
        client.get("/auth/lucid-account", follow_redirects=False)
        assert state.rest_account_oauth_state_created_at is not None


class TestAccountOAuthCallback:
    """GET /callback-account validates CSRF state and rejects bad/expired tokens."""

    def _seed_account_state(self, token: str, age_seconds: int = 0) -> None:
        state.rest_account_oauth_state = token
        state.rest_account_oauth_state_created_at = datetime.utcnow() - timedelta(seconds=age_seconds)

    def test_wrong_state_rejected(self, client):
        self._seed_account_state("correct-account-token")
        response = client.get(
            "/callback-account?code=fakecode&state=wrong-token",
            follow_redirects=False,
        )
        location = response.headers.get("location", "")
        assert "state_mismatch" in location

    def test_expired_state_rejected(self, client):
        self._seed_account_state("account-token", age_seconds=601)
        response = client.get(
            "/callback-account?code=fakecode&state=account-token",
            follow_redirects=False,
        )
        location = response.headers.get("location", "")
        assert "state_expired" in location

    def test_expired_state_clears_memory(self, client):
        self._seed_account_state("account-token", age_seconds=601)
        client.get(
            "/callback-account?code=fakecode&state=account-token",
            follow_redirects=False,
        )
        assert state.rest_account_oauth_state is None
        assert state.rest_account_oauth_state_created_at is None

    def test_fresh_state_passes_csrf_check(self, client):
        self._seed_account_state("fresh-account-token", age_seconds=0)
        response = client.get(
            "/callback-account?code=fakecode&state=fresh-account-token",
            follow_redirects=False,
        )
        location = response.headers.get("location", "")
        assert "state_mismatch" not in location
        assert "state_expired" not in location
