"""
tests/conftest.py — Shared fixtures for the lucid-api-explorer test suite.

All required environment variables are set here using monkeypatch (or os.environ
directly for module-level fixtures) so that app modules can be imported without
a real .env file present.

Pattern:
  - Use `env_setup` autouse fixture (session-scoped) to set env vars before
    any module is imported in tests.
  - Use `client` fixture for FastAPI route tests (synchronous TestClient).
  - Use `reset_state` fixture to wipe in-memory token state between tests.
"""

import os
import pytest

# ── Minimal env vars required by app/config.py ───────────────────────────────
# Set these before any app module is imported (session scope = runs once).
_REQUIRED_ENV = {
    "LUCID_CLIENT_ID": "test-client-id",
    "LUCID_CLIENT_SECRET": "test-client-secret",
    "LUCID_REDIRECT_URI": "http://localhost:8000/callback",
    "LUCID_ACCOUNT_REDIRECT_URI": "http://localhost:8000/callback-account",
    "ANTHROPIC_API_KEY": "test-anthropic-key",
    # Optional vars with defaults — set explicitly to avoid surprises
    "LUCID_SCIM_TOKEN": "test-scim-token",
    "LUCID_MCP_URL": "https://mcp.lucid.app",
    "LUCID_OAUTH_SCOPES": "account.user:readonly",
    "LUCID_ACCOUNT_OAUTH_SCOPES": "account.user",
}

# Apply env vars at import time so config.py can be imported cleanly.
for _k, _v in _REQUIRED_ENV.items():
    os.environ.setdefault(_k, _v)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture()
def client():
    """FastAPI TestClient with the full app mounted. Synchronous."""
    from fastapi.testclient import TestClient
    from main import app  # noqa: PLC0415
    with TestClient(app, raise_server_exceptions=True) as tc:
        yield tc


@pytest.fixture(autouse=True)
def reset_state():
    """
    Wipe all in-memory auth state before each test so tests don't bleed
    into each other. Autouse=True means it runs for every test automatically.
    """
    import app.state as state  # noqa: PLC0415
    state.clear_rest_auth()
    state.clear_rest_account_auth()
    state.clear_mcp_auth()
    state.scim_bearer_token = None
    state.last_request = None
    state.last_response = None
    yield
    # Teardown: wipe again for cleanliness
    state.clear_rest_auth()
    state.clear_rest_account_auth()
    state.clear_mcp_auth()
