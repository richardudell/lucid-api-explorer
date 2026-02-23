"""
app/config.py — Environment variable loading and validation.

Loads all variables from .env on import via python-dotenv.
Raises a descriptive error at startup if any required variable is missing,
so engineers see a clear message rather than a cryptic KeyError later.
"""

import os
from dotenv import load_dotenv

# Load .env from the project root.
# override=True ensures .env values win even if empty env vars are already set
# in the shell environment (e.g. from a previous session that exported blanks).
load_dotenv(override=True)


def _require(name: str) -> str:
    """Return the value of a required env variable, or raise on startup."""
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(
            f"Missing required environment variable: {name}\n"
            f"Copy .env.example to .env and fill in your values."
        )
    return value


# ── Lucid REST API — OAuth 2.0 Authorization Code Flow ──────────────────────
LUCID_CLIENT_ID: str = _require("LUCID_CLIENT_ID")
LUCID_CLIENT_SECRET: str = _require("LUCID_CLIENT_SECRET")
LUCID_REDIRECT_URI: str = _require("LUCID_REDIRECT_URI")

# Scopes are space- or comma-separated in .env; stored as a list for easy iteration.
# Valid Lucid OAuth scope strings: account.user, account.user:readonly, user.profile,
# lucidchart.document.content, lucidchart.document.content:readonly, offline_access, etc.
# See: https://developer.lucid.co/reference/access-scopes
_raw_scopes = os.getenv("LUCID_OAUTH_SCOPES", "account.user:readonly user.profile")
LUCID_OAUTH_SCOPES: list[str] = [s.strip() for s in _raw_scopes.replace(",", " ").split() if s.strip()]

# Lucid OAuth endpoints (not in .env — they are stable public URLs)
# User token: standard Authorization Code flow — for user-context endpoints
LUCID_AUTH_URL: str = "https://lucid.app/oauth2/authorize"
# Account token: same flow but different auth URL — for account-admin endpoints (createUser, listUsers, etc.)
LUCID_ACCOUNT_AUTH_URL: str = "https://lucid.app/oauth2/authorizeAccount"
LUCID_TOKEN_URL: str = "https://api.lucid.co/oauth2/token"

# Redirect URI for the account token callback — must be registered in the Developer Portal
LUCID_ACCOUNT_REDIRECT_URI: str = os.getenv("LUCID_ACCOUNT_REDIRECT_URI", "http://localhost:8000/callback-account")

# Scopes for the account token flow — account-admin level operations
_raw_account_scopes = os.getenv("LUCID_ACCOUNT_OAUTH_SCOPES", "account.user")
LUCID_ACCOUNT_OAUTH_SCOPES: list[str] = [s.strip() for s in _raw_account_scopes.replace(",", " ").split() if s.strip()]

# ── Lucid REST API base URL ──────────────────────────────────────────────────
LUCID_REST_BASE_URL: str = "https://api.lucid.co"

# ── Lucid SCIM API — Static Bearer Token ────────────────────────────────────
LUCID_SCIM_TOKEN: str = _require("LUCID_SCIM_TOKEN")
LUCID_SCIM_BASE_URL: str = "https://users.lucid.app/scim/v2"

# ── Lucid MCP Server ─────────────────────────────────────────────────────────
# No credentials here — Dynamic Client Registration is handled by the mcp package.
LUCID_MCP_URL: str = "https://mcp.lucid.app/mcp"
LUCID_MCP_REGISTER_URL: str = "https://mcp.lucid.app/oauth/register"
LUCID_MCP_REDIRECT_URI: str = "http://localhost:8000/mcp/callback"

# ── Anthropic API ────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = _require("ANTHROPIC_API_KEY")

# ── App settings ─────────────────────────────────────────────────────────────
PORT: int = int(os.getenv("PORT", "8000"))
DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
