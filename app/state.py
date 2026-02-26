"""
app/state.py — In-memory runtime state for lucid-api-explorer.

All state lives here as module-level variables. Nothing is persisted to disk.
State is lost on server restart — this is intentional. Re-authenticating takes
seconds and keeps the auth flow visible and educational rather than silently cached.

Import individual variables directly:
    from app.state import rest_access_token
Or import the module to mutate state from route handlers:
    import app.state as state
    state.rest_access_token = token
"""

from datetime import datetime


# ── REST API — OAuth 2.0 Authorization Code Flow (User Token) ────────────────
# Token is acquired via the /auth/lucid → /callback flow and stored here.
# Used for user-context endpoints: getUser, getUserProfile, etc.

rest_access_token: str | None = None
rest_refresh_token: str | None = None     # present if Lucid issues one
rest_token_expires_at: datetime | None = None
rest_token_scopes: list[str] = []
rest_token_type: str | None = None        # e.g. "Bearer"
rest_token_expires_in: int | None = None  # raw seconds from last token response

# PKCE / state parameter stored during the OAuth redirect to prevent CSRF.
# Set when the flow is initiated; cleared after the callback succeeds.
rest_oauth_state: str | None = None
rest_oauth_state_created_at: datetime | None = None  # expiry guard: reject callbacks > 10 min old


# ── REST API — OAuth 2.0 Authorization Code Flow (Account Token) ─────────────
# Token is acquired via the /auth/lucid-account → /callback-account flow.
# Used for account-admin endpoints: createUser, listUsers, etc.

rest_account_access_token: str | None = None
rest_account_refresh_token: str | None = None
rest_account_token_expires_at: datetime | None = None
rest_account_token_scopes: list[str] = []
rest_account_token_type: str | None = None
rest_account_token_expires_in: int | None = None

# CSRF state for the account token flow
rest_account_oauth_state: str | None = None
rest_account_oauth_state_created_at: datetime | None = None  # expiry guard: reject callbacks > 10 min old


# ── SCIM API — Static Bearer Token ───────────────────────────────────────────
# Loaded from config (which reads it from .env) on first use.
# Never changes at runtime unless the server restarts with a new .env.

scim_bearer_token: str | None = None


# ── MCP Server — Dynamic Client Registration ──────────────────────────────────
# The mcp package manages its own internal session, but we track top-level
# status here so the UI auth indicator stays accurate.

mcp_session_active: bool = False
mcp_access_token: str | None = None


# ── Last executed call — used for narrative generation ────────────────────────
# Populated by route handlers after every successful (or failed) API call.
# ai_client.py reads these to build the four-beat Claude narrative.

last_request: dict | None = None   # method, url, headers, body, timestamp
last_response: dict | None = None  # status_code, headers, body, latency_ms


# ── Helper functions ──────────────────────────────────────────────────────────

def is_rest_authenticated() -> bool:
    """Return True if a valid, non-expired REST user token is held."""
    if rest_access_token is None:
        return False
    if rest_token_expires_at is None:
        return True  # No expiry recorded — assume valid
    return datetime.utcnow() < rest_token_expires_at


def is_rest_account_authenticated() -> bool:
    """Return True if a valid, non-expired REST account token is held."""
    if rest_account_access_token is None:
        return False
    if rest_account_token_expires_at is None:
        return True
    return datetime.utcnow() < rest_account_token_expires_at


def is_scim_authenticated() -> bool:
    """Return True if a SCIM bearer token is loaded."""
    return scim_bearer_token is not None


def is_mcp_authenticated() -> bool:
    """Return True if an active MCP session exists."""
    return mcp_session_active and mcp_access_token is not None


def get_auth_status() -> dict:
    """
    Return a summary of all three auth surfaces.
    Called by GET /auth/status so the frontend can update status indicators.
    """
    return {
        "rest": {
            "authenticated": is_rest_authenticated(),
            "scopes": rest_token_scopes,
            "expires_at": rest_token_expires_at.isoformat() if rest_token_expires_at else None,
        },
        "rest_account": {
            "authenticated": is_rest_account_authenticated(),
            "scopes": rest_account_token_scopes,
            "expires_at": rest_account_token_expires_at.isoformat() if rest_account_token_expires_at else None,
        },
        "scim": {
            "authenticated": is_scim_authenticated(),
        },
        "mcp": {
            "authenticated": is_mcp_authenticated(),
        },
    }


def clear_rest_auth() -> None:
    """Wipe REST user token state (e.g. on explicit logout or token error)."""
    global rest_access_token, rest_refresh_token, rest_token_expires_at
    global rest_token_scopes, rest_token_type, rest_token_expires_in
    global rest_oauth_state, rest_oauth_state_created_at
    rest_access_token = None
    rest_refresh_token = None
    rest_token_expires_at = None
    rest_token_scopes = []
    rest_token_type = None
    rest_token_expires_in = None
    rest_oauth_state = None
    rest_oauth_state_created_at = None


def clear_rest_account_auth() -> None:
    """Wipe REST account token state."""
    global rest_account_access_token, rest_account_refresh_token, rest_account_token_expires_at
    global rest_account_token_scopes, rest_account_token_type, rest_account_token_expires_in
    global rest_account_oauth_state, rest_account_oauth_state_created_at
    rest_account_access_token = None
    rest_account_refresh_token = None
    rest_account_token_expires_at = None
    rest_account_token_scopes = []
    rest_account_token_type = None
    rest_account_token_expires_in = None
    rest_account_oauth_state = None
    rest_account_oauth_state_created_at = None


def clear_mcp_auth() -> None:
    """Wipe MCP session state."""
    global mcp_session_active, mcp_access_token
    mcp_session_active = False
    mcp_access_token = None
