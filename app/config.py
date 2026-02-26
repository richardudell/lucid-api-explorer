"""
app/config.py — Environment variable loading and validation.

Loads all variables from .env on import via python-dotenv.

Production/dev mode:
  - Missing required variables raise at startup.

Demo mode (DEMO_MODE=true or APP_ENV=demo):
  - Missing required OAuth vars fall back to non-secret placeholders so the UI
    can boot for walkthroughs.
  - AI/SCIM features are allowed to be disabled cleanly when keys are absent.
"""

import os
from dotenv import load_dotenv

# Load .env from the project root.
# override=True ensures .env values win even if empty env vars are already set
# in the shell environment (e.g. from a previous session that exported blanks).
load_dotenv(override=True)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "demo"}


DEMO_MODE: bool = (
    _truthy(os.getenv("DEMO_MODE"))
    or os.getenv("APP_ENV", "").strip().lower() == "demo"
)


def _require(name: str, demo_default: str | None = None) -> str:
    """
    Return the value of a required env variable, or raise on startup.

    In DEMO_MODE only, missing vars can fall back to a placeholder so the app
    starts without secrets.
    """
    value = os.getenv(name)
    if not value:
        if DEMO_MODE and demo_default is not None:
            return demo_default
        raise EnvironmentError(
            f"Missing required environment variable: {name}\n"
            f"Copy .env.example to .env and fill in your values."
        )
    return value


def _is_placeholder(value: str | None) -> bool:
    val = str(value or "").strip()
    if not val:
        return True
    return (
        val.endswith("_here")
        or val.startswith("__DEMO_")
        or val.startswith("your_")
    )


# ── Lucid REST API — OAuth 2.0 Authorization Code Flow ──────────────────────
LUCID_CLIENT_ID: str = _require("LUCID_CLIENT_ID", "__DEMO_CLIENT_ID__")
LUCID_CLIENT_SECRET: str = _require("LUCID_CLIENT_SECRET", "__DEMO_CLIENT_SECRET__")
LUCID_REDIRECT_URI: str = _require("LUCID_REDIRECT_URI", "http://localhost:8000/callback")

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
LUCID_SCIM_TOKEN: str = os.getenv("LUCID_SCIM_TOKEN", "")
LUCID_SCIM_BASE_URL: str = "https://users.lucid.app/scim/v2"

# ── Lucid MCP Server ─────────────────────────────────────────────────────────
# No credentials here — Dynamic Client Registration is handled by the mcp package.
LUCID_MCP_URL: str = "https://mcp.lucid.app/mcp"
LUCID_MCP_REGISTER_URL: str = "https://mcp.lucid.app/oauth/register"
LUCID_MCP_REDIRECT_URI: str = "http://localhost:8000/mcp/callback"

# ── Anthropic API ────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# ── Feature readiness flags ───────────────────────────────────────────────────
LUCID_OAUTH_CONFIGURED: bool = (
    not _is_placeholder(LUCID_CLIENT_ID)
    and not _is_placeholder(LUCID_CLIENT_SECRET)
    and not _is_placeholder(LUCID_REDIRECT_URI)
    and not _is_placeholder(LUCID_ACCOUNT_REDIRECT_URI)
)
SCIM_CONFIGURED: bool = not _is_placeholder(LUCID_SCIM_TOKEN)
ANTHROPIC_CONFIGURED: bool = not _is_placeholder(ANTHROPIC_API_KEY)

# ── App settings ─────────────────────────────────────────────────────────────
PORT: int = int(os.getenv("PORT", "8000"))
DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
