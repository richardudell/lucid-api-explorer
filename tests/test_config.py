"""
tests/test_config.py — Unit tests for app/config.py.

Verifies that:
  - Config raises EnvironmentError when required env vars are missing.
  - Config loads correctly when all required vars are present.

Implementation note:
  config.py calls load_dotenv(override=True) at module level, which would
  re-load values from the local .env file and override any monkeypatched
  env vars. To prevent this, _reimport_config() patches load_dotenv to a
  no-op before re-importing the module. This isolates the tests from the
  local .env file so we test only the _require() guard logic.
"""

import importlib
import sys
from unittest.mock import patch

import pytest


def _reimport_config(remove_vars: list | None = None, extra_vars: dict | None = None):
    """
    Helper: clear the cached config module, patch load_dotenv to a no-op,
    apply env overrides via monkeypatch, then re-import app.config.

    remove_vars: env var names to unset before import
    extra_vars:  env var names/values to set before import
    """
    import os

    # Remove cached module so module-level code runs again on re-import
    for mod in list(sys.modules.keys()):
        if mod == "app.config" or mod.startswith("app.config."):
            del sys.modules[mod]

    # Build the env we want to test with, starting from a clean baseline
    # that has all required vars set, then removing/adding as requested.
    base_env = {
        "LUCID_CLIENT_ID": "test-client-id",
        "LUCID_CLIENT_SECRET": "test-client-secret",
        "LUCID_REDIRECT_URI": "http://localhost:8000/callback",
        "LUCID_ACCOUNT_REDIRECT_URI": "http://localhost:8000/callback-account",
        "ANTHROPIC_API_KEY": "test-anthropic-key",
        "LUCID_SCIM_TOKEN": "test-scim-token",
    }
    if remove_vars:
        for k in remove_vars:
            base_env.pop(k, None)
    if extra_vars:
        base_env.update(extra_vars)

    # Patch load_dotenv to a no-op and replace os.environ with our test env
    with patch("dotenv.load_dotenv"), patch.dict(os.environ, base_env, clear=True):
        return importlib.import_module("app.config")


class TestConfigValidation:
    """Config must raise EnvironmentError for each missing required variable."""

    def test_missing_client_id_raises(self):
        with pytest.raises(EnvironmentError, match="LUCID_CLIENT_ID"):
            _reimport_config(remove_vars=["LUCID_CLIENT_ID"])

    def test_missing_client_secret_raises(self):
        with pytest.raises(EnvironmentError, match="LUCID_CLIENT_SECRET"):
            _reimport_config(remove_vars=["LUCID_CLIENT_SECRET"])

    def test_missing_redirect_uri_raises(self):
        with pytest.raises(EnvironmentError, match="LUCID_REDIRECT_URI"):
            _reimport_config(remove_vars=["LUCID_REDIRECT_URI"])

    def test_missing_anthropic_key_raises(self):
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            _reimport_config(remove_vars=["ANTHROPIC_API_KEY"])

    def test_missing_scim_token_raises(self):
        with pytest.raises(EnvironmentError, match="LUCID_SCIM_TOKEN"):
            _reimport_config(remove_vars=["LUCID_SCIM_TOKEN"])

    def test_error_message_is_actionable(self):
        """The error message should mention .env.example so engineers know what to do."""
        with pytest.raises(EnvironmentError, match=".env.example"):
            _reimport_config(remove_vars=["LUCID_CLIENT_ID"])


class TestConfigLoads:
    """Config should expose expected attributes when all vars are set."""

    def test_client_id_loaded(self):
        cfg = _reimport_config()
        assert cfg.LUCID_CLIENT_ID == "test-client-id"

    def test_client_secret_loaded(self):
        cfg = _reimport_config()
        assert cfg.LUCID_CLIENT_SECRET == "test-client-secret"

    def test_redirect_uri_loaded(self):
        cfg = _reimport_config()
        assert cfg.LUCID_REDIRECT_URI == "http://localhost:8000/callback"

    def test_anthropic_key_loaded(self):
        cfg = _reimport_config()
        assert cfg.ANTHROPIC_API_KEY == "test-anthropic-key"

    def test_scim_token_loaded(self):
        cfg = _reimport_config()
        assert cfg.LUCID_SCIM_TOKEN == "test-scim-token"

    def test_scopes_parsed_as_list(self):
        """LUCID_OAUTH_SCOPES should be a list, not a raw string."""
        cfg = _reimport_config()
        assert isinstance(cfg.LUCID_OAUTH_SCOPES, list)

    def test_port_defaults_to_8000(self):
        """PORT should default to 8000 when not set in env."""
        cfg = _reimport_config()
        assert cfg.PORT == 8000

    def test_static_urls_present(self):
        """Well-known Lucid API URLs should be hard-coded (not from env)."""
        cfg = _reimport_config()
        assert "lucid.app" in cfg.LUCID_AUTH_URL
        assert "lucid.co" in cfg.LUCID_TOKEN_URL
