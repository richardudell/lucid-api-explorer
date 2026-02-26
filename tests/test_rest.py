"""
tests/test_rest.py — Unit tests for app/services/lucid_rest.py.

Covers:
  - Token slot routing in _update_state_from_token_response:
      - token_type="user"    → writes user slot
      - token_type="account" → writes account slot
      - token_type absent     → defaults to user slot
      - grant_type="authorization_code" always → user slot (ignores token_type)
      - After server restart (both slots empty), explicit token_type routes correctly

The function is tested as a unit (called directly), not through the HTTP layer.
"""

from datetime import datetime

import pytest
import app.state as state
from app.services.lucid_rest import _update_state_from_token_response


# Minimal token response Lucid would return from /oauth2/token
_FAKE_TOKEN_RESPONSE = {
    "access_token": "new-access-token",
    "refresh_token": "new-refresh-token",
    "token_type": "Bearer",
    "expires_in": 3600,
    "scope": "account.user:readonly",
}


class TestTokenSlotUser:
    """token_type='user' must write to the user (REST) slot."""

    def test_access_token_written_to_user_slot(self):
        params = {"grant_type": "refresh_token", "refresh_token": "old-rt"}
        _update_state_from_token_response(_FAKE_TOKEN_RESPONSE, params, token_type="user")
        assert state.rest_access_token == "new-access-token"
        assert state.rest_account_access_token is None  # account slot untouched

    def test_refresh_token_updated_in_user_slot(self):
        params = {"grant_type": "refresh_token", "refresh_token": "old-rt"}
        _update_state_from_token_response(_FAKE_TOKEN_RESPONSE, params, token_type="user")
        assert state.rest_refresh_token == "new-refresh-token"

    def test_scopes_written_to_user_slot(self):
        params = {"grant_type": "refresh_token", "refresh_token": "old-rt"}
        _update_state_from_token_response(_FAKE_TOKEN_RESPONSE, params, token_type="user")
        assert "account.user:readonly" in state.rest_token_scopes

    def test_expiry_set_in_user_slot(self):
        params = {"grant_type": "refresh_token", "refresh_token": "old-rt"}
        _update_state_from_token_response(_FAKE_TOKEN_RESPONSE, params, token_type="user")
        assert state.rest_token_expires_at is not None
        assert state.rest_token_expires_at > datetime.utcnow()


class TestTokenSlotAccount:
    """token_type='account' must write to the account slot."""

    def test_access_token_written_to_account_slot(self):
        params = {"grant_type": "refresh_token", "refresh_token": "old-account-rt"}
        _update_state_from_token_response(_FAKE_TOKEN_RESPONSE, params, token_type="account")
        assert state.rest_account_access_token == "new-access-token"
        assert state.rest_access_token is None  # user slot untouched

    def test_refresh_token_updated_in_account_slot(self):
        params = {"grant_type": "refresh_token", "refresh_token": "old-account-rt"}
        _update_state_from_token_response(_FAKE_TOKEN_RESPONSE, params, token_type="account")
        assert state.rest_account_refresh_token == "new-refresh-token"

    def test_scopes_written_to_account_slot(self):
        params = {"grant_type": "refresh_token", "refresh_token": "old-account-rt"}
        _update_state_from_token_response(_FAKE_TOKEN_RESPONSE, params, token_type="account")
        assert "account.user:readonly" in state.rest_account_token_scopes

    def test_expiry_set_in_account_slot(self):
        params = {"grant_type": "refresh_token", "refresh_token": "old-account-rt"}
        _update_state_from_token_response(_FAKE_TOKEN_RESPONSE, params, token_type="account")
        assert state.rest_account_token_expires_at is not None
        assert state.rest_account_token_expires_at > datetime.utcnow()


class TestTokenSlotDefault:
    """Omitting token_type must default to the user slot."""

    def test_default_writes_user_slot(self):
        params = {"grant_type": "refresh_token", "refresh_token": "some-rt"}
        _update_state_from_token_response(_FAKE_TOKEN_RESPONSE, params)
        assert state.rest_access_token == "new-access-token"
        assert state.rest_account_access_token is None


class TestTokenSlotAfterRestart:
    """
    After a server restart both slots are empty. With the old inference logic
    (comparing incoming refresh token to stored tokens), the account slot could
    never be correctly identified. With explicit token_type, this is a non-issue.
    """

    def test_user_slot_after_restart(self):
        """Both slots empty + token_type='user' → writes user slot correctly."""
        # State is already wiped by the reset_state autouse fixture
        assert state.rest_refresh_token is None
        assert state.rest_account_refresh_token is None

        params = {"grant_type": "refresh_token", "refresh_token": "any-refresh-token"}
        _update_state_from_token_response(_FAKE_TOKEN_RESPONSE, params, token_type="user")
        assert state.rest_access_token == "new-access-token"
        assert state.rest_account_access_token is None

    def test_account_slot_after_restart(self):
        """Both slots empty + token_type='account' → writes account slot correctly."""
        assert state.rest_refresh_token is None
        assert state.rest_account_refresh_token is None

        params = {"grant_type": "refresh_token", "refresh_token": "any-refresh-token"}
        _update_state_from_token_response(_FAKE_TOKEN_RESPONSE, params, token_type="account")
        assert state.rest_account_access_token == "new-access-token"
        assert state.rest_access_token is None


class TestAuthorizationCodeAlwaysUserSlot:
    """grant_type=authorization_code must always write the user slot, regardless of token_type."""

    def test_auth_code_ignores_account_token_type(self):
        """Even if token_type='account', a new auth code exchange writes the user slot."""
        params = {"grant_type": "authorization_code", "code": "fake-code"}
        _update_state_from_token_response(_FAKE_TOKEN_RESPONSE, params, token_type="account")
        # auth code flows always produce user tokens — per Lucid's OAuth model
        assert state.rest_access_token == "new-access-token"
        assert state.rest_account_access_token is None

    def test_auth_code_writes_user_slot(self):
        params = {"grant_type": "authorization_code", "code": "fake-code"}
        _update_state_from_token_response(_FAKE_TOKEN_RESPONSE, params, token_type="user")
        assert state.rest_access_token == "new-access-token"
