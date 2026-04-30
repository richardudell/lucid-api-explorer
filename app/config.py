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
from urllib.parse import urlparse
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

ALLOW_REMOTE: bool = _truthy(os.getenv("ALLOW_REMOTE"))


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

# Fallback OAuth scopes — used only if /auth/lucid or /auth/lucid-account is called
# with no ?scopes= query param (i.e., the UI scope selector was bypassed).
# These are NOT configurable via .env — scope selection happens in the UI via
# /auth/required-scopes, which builds the list dynamically from ENDPOINT_REGISTRY.
# See: https://developer.lucid.co/reference/access-scopes
LUCID_OAUTH_SCOPES: list[str] = ["account.user:readonly", "user.profile"]
LUCID_ACCOUNT_OAUTH_SCOPES: list[str] = ["account.user"]

# Lucid OAuth endpoints (not in .env — they are stable public URLs)
# User token: standard Authorization Code flow — for user-context endpoints
LUCID_AUTH_URL: str = "https://lucid.app/oauth2/authorize"
# Account token: same flow but different auth URL — for account-admin endpoints (createUser, listUsers, etc.)
LUCID_ACCOUNT_AUTH_URL: str = "https://lucid.app/oauth2/authorizeAccount"
LUCID_TOKEN_URL: str = "https://api.lucid.co/oauth2/token"

# Redirect URI for the account token callback — must be registered in the Developer Portal
LUCID_ACCOUNT_REDIRECT_URI: str = os.getenv("LUCID_ACCOUNT_REDIRECT_URI", "http://localhost:8000/callback-account")

# ── Lucid REST API base URL ──────────────────────────────────────────────────
LUCID_REST_BASE_URL: str = "https://api.lucid.co"

# ── Lucid SCIM API — Static Bearer Token ────────────────────────────────────
LUCID_SCIM_TOKEN: str = _require("LUCID_SCIM_TOKEN", "__DEMO_SCIM_DISABLED__")
LUCID_SCIM_BASE_URL: str = "https://users.lucid.app/scim/v2"

# ── Lucid MCP Server ─────────────────────────────────────────────────────────
# No credentials here — Dynamic Client Registration is handled by the mcp package.
LUCID_MCP_URL: str = "https://mcp.lucid.app/mcp"
LUCID_MCP_REGISTER_URL: str = "https://mcp.lucid.app/oauth/register"
LUCID_MCP_REDIRECT_URI: str = "http://localhost:8000/mcp/callback"

# ── Anthropic API ────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = _require("ANTHROPIC_API_KEY", "__DEMO_AI_DISABLED__")

# ── Feature readiness flags ───────────────────────────────────────────────────
LUCID_OAUTH_CONFIGURED: bool = (
    not _is_placeholder(LUCID_CLIENT_ID)
    and not _is_placeholder(LUCID_CLIENT_SECRET)
    and not _is_placeholder(LUCID_REDIRECT_URI)
    and not _is_placeholder(LUCID_ACCOUNT_REDIRECT_URI)
)
SCIM_CONFIGURED: bool = not _is_placeholder(LUCID_SCIM_TOKEN)
ANTHROPIC_CONFIGURED: bool = not _is_placeholder(ANTHROPIC_API_KEY)

# ── PKCE toggle ───────────────────────────────────────────────────────────────
# When False (default), the OAuth flows run as plain Authorization Code without
# PKCE. This is the correct mode for training and demos — PKCE adds security
# value in public/mobile clients but is not required for a confidential server-
# side client, and the extra parameters distract from the core flow concepts.
#
# Set PKCE_ENABLED=true in .env to re-enable PKCE (code_challenge + code_verifier).
PKCE_ENABLED: bool = _truthy(os.getenv("PKCE_ENABLED", "false"))

# ── App settings ─────────────────────────────────────────────────────────────
PORT: int = int(os.getenv("PORT", "8000"))
HOST: str = os.getenv("HOST", "127.0.0.1").strip() or "127.0.0.1"
DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"


def _parse_csv_hosts(value: str) -> list[str]:
    return [h.strip().lower() for h in value.split(",") if h.strip()]


_raw_acs_hosts = os.getenv("SAML_ALLOWED_ACS_HOSTS", "lucid.app,localhost,127.0.0.1")
SAML_ALLOWED_ACS_HOSTS: list[str] = _parse_csv_hosts(_raw_acs_hosts)


def is_allowed_acs_url(url: str) -> tuple[bool, str]:
    """
    Validate ACS target URL.

    - Requires absolute URL.
    - Production hosts must use https.
    - Host must match configured allowlist (exact or subdomain).
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "ACS URL could not be parsed."

    if parsed.scheme not in {"http", "https"}:
        return False, "ACS URL must use http or https."
    if not parsed.netloc:
        return False, "ACS URL must be absolute."

    host = (parsed.hostname or "").lower()
    if not host:
        return False, "ACS URL host is missing."

    is_local = host in {"localhost", "127.0.0.1", "::1"}
    if not is_local and parsed.scheme != "https":
        return False, "ACS URL must use https for non-local hosts."

    allowed = False
    for allowed_host in SAML_ALLOWED_ACS_HOSTS:
        if host == allowed_host or host.endswith(f".{allowed_host}"):
            allowed = True
            break
    if not allowed:
        return (
            False,
            "ACS URL host is not in allowlist. "
            f"Allowed hosts: {', '.join(SAML_ALLOWED_ACS_HOSTS)}",
        )
    return True, ""
