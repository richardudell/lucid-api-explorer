"""
app/routes/auth.py — OAuth 2.0 Authorization Code Flow for the Lucid REST API.

Two endpoints drive the flow:

  GET /auth/lucid   — Step 1: redirect the browser to Lucid's authorization URL.
                      A random `state` param is stored in app.state to prevent CSRF.

  GET /callback     — Step 2: Lucid redirects here with ?code=... after user consent.
                      We exchange the code for an access token (server-to-server POST),
                      store the token in app.state, then redirect back to the app UI.

Additional endpoints:

  GET /auth/status      — Returns current auth state for all three surfaces (REST/SCIM/MCP).
  GET /auth/flow-status — Returns the full step-by-step OAuth flow log with request/response
                          details so the frontend can render a complete educational timeline.
  POST /auth/logout     — Clears REST token state so the engineer can re-authenticate.
"""

import secrets
import httpx

from datetime import datetime, timedelta
from urllib.parse import urlencode, quote as urlquote

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

import app.state as state
from app.config import (
    LUCID_AUTH_URL,
    LUCID_ACCOUNT_AUTH_URL,
    LUCID_CLIENT_ID,
    LUCID_CLIENT_SECRET,
    LUCID_OAUTH_SCOPES,
    LUCID_ACCOUNT_OAUTH_SCOPES,
    LUCID_REDIRECT_URI,
    LUCID_ACCOUNT_REDIRECT_URI,
    LUCID_TOKEN_URL,
    LUCID_SCIM_TOKEN,
)

router = APIRouter()

# ── Flow logs ─────────────────────────────────────────────────────────────────
# Separate logs for user token and account token flows.
# The frontend fetches these via /auth/flow-status and /auth/account-flow-status.

_oauth_flow_log: list[dict] = []
_account_oauth_flow_log: list[dict] = []


def _reset_flow_log() -> None:
    global _oauth_flow_log
    _oauth_flow_log = []


def _reset_account_flow_log() -> None:
    global _account_oauth_flow_log
    _account_oauth_flow_log = []


def _log_step(
    step: int,
    label: str,
    detail: str,
    status: str,                   # 'ok' | 'error' | 'pending'
    request: dict | None = None,   # {method, url, headers, body} — what we sent
    response: dict | None = None,  # {status_code, body} — what we received
) -> None:
    """Append a richly-detailed step to the OAuth flow log."""
    _oauth_flow_log.append({
        "step": step,
        "label": label,
        "detail": detail,
        "status": status,
        "request": request,
        "response": response,
    })


# ── Step 1 — Initiate the OAuth flow ─────────────────────────────────────────

@router.get("/auth/lucid", summary="Initiate Lucid REST API OAuth flow")
async def auth_lucid(scopes: str | None = None) -> RedirectResponse:
    """
    Redirect the browser to Lucid's authorization URL.

    Generates a cryptographically random `state` value and stores it in
    app.state.rest_oauth_state. Lucid will echo it back on the callback so
    we can verify the request wasn't forged (CSRF protection).

    Args:
        scopes: Optional space-separated scope string from the UI scope selector.
                If not provided, falls back to LUCID_OAUTH_SCOPES from .env.
    """
    _reset_flow_log()

    # ── Step 1: Generate CSRF state token ────────────────────────────────────
    oauth_state = secrets.token_urlsafe(32)
    state.rest_oauth_state = oauth_state

    _log_step(
        step=1,
        label="State token generated",
        detail=(
            "A cryptographically random value created with secrets.token_urlsafe(32). "
            "Stored in server memory. Lucid will echo it back on the callback — "
            "if it doesn't match, we reject the request as a potential CSRF attack."
        ),
        status="ok",
        request=None,
        response={"state_token": oauth_state[:8] + "••••••••  (truncated for display)"},
    )

    # ── Step 2: Build the authorization URL ───────────────────────────────────
    # Use UI-selected scopes if provided; fall back to .env defaults.
    # Scopes must be space-separated (RFC 6749 §3.3).
    # We encode all params except scope with urlencode(), then append scope
    # separately so spaces become %20 — some servers reject + encoding.
    if scopes:
        scope_list = [s.strip() for s in scopes.split() if s.strip()]
    else:
        scope_list = list(LUCID_OAUTH_SCOPES)
    scope_str = " ".join(scope_list)

    base_params = urlencode({
        "client_id": LUCID_CLIENT_ID,
        "redirect_uri": LUCID_REDIRECT_URI,
        "response_type": "code",
        "state": oauth_state,
    })
    scope_param = "scope=" + urlquote(scope_str, safe=":")
    authorization_url = f"{LUCID_AUTH_URL}?{base_params}&{scope_param}"

    _log_step(
        step=2,
        label="Authorization URL constructed",
        detail=(
            f"The browser will be redirected to Lucid's authorization endpoint. "
            f"Scopes requested: {scope_str}. "
            f"response_type=code tells Lucid we want an Authorization Code, not an implicit token. "
            f"The redirect_uri must match exactly what is registered in the Developer Portal."
        ),
        status="pending",
        request={
            "method": "GET (browser redirect)",
            "url": authorization_url,
            "params": {
                "client_id": LUCID_CLIENT_ID,
                "redirect_uri": LUCID_REDIRECT_URI,
                "response_type": "code",
                "scope": scope_str,
                "state": oauth_state[:8] + "•••• (truncated)",
            },
        },
        response=None,
    )

    return RedirectResponse(url=authorization_url)


# ── Step 2 — Receive the authorization code and exchange for a token ──────────

@router.get("/callback", summary="OAuth callback — exchange code for access token")
async def oauth_callback(
    code: str | None = None,
    state_param: str | None = Query(default=None, alias="state"),
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    """
    Lucid redirects here after the user grants (or denies) consent.

    On success:
      1. Validate the `state` param (CSRF check).
      2. POST to Lucid's token endpoint — server-to-server, client_secret stays backend-only.
      3. Store the access token in app.state.
      4. Redirect back to / with auth_success=true.

    On failure:
      Redirect to / with auth_error=<reason>.
    """
    # ── Handle explicit OAuth errors from Lucid ───────────────────────────────
    if error:
        _log_step(
            step=3,
            label=f"Lucid returned an error: {error}",
            detail=_explain_oauth_error(error, error_description),
            status="error",
            request=None,
            response={"error": error, "error_description": error_description or ""},
        )
        return RedirectResponse(url=f"/?auth_error={urlquote(error)}")

    # ── No code returned ──────────────────────────────────────────────────────
    if not code:
        _log_step(
            step=3,
            label="No authorization code received",
            detail=(
                "Lucid redirected back to /callback without a code parameter. "
                "This usually means the user denied consent, or the redirect_uri "
                "registered in the Developer Portal doesn't match LUCID_REDIRECT_URI in .env."
            ),
            status="error",
            request=None,
            response={"error": "no_code", "raw_params": {"state": state_param}},
        )
        return RedirectResponse(url="/?auth_error=no_code_returned")

    # ── Step 3: Authorization code received ───────────────────────────────────
    _log_step(
        step=3,
        label="Authorization code received",
        detail=(
            "Lucid redirected back to /callback with a one-time authorization code. "
            "This code is short-lived (typically 60s) and can only be used once. "
            "It must be exchanged for an access token before it expires."
        ),
        status="ok",
        request=None,
        response={
            "code": code[:8] + "•••• (truncated)",
            "state": state_param[:8] + "•••• (truncated)" if state_param else None,
        },
    )

    # ── Step 4: Validate state (CSRF check) ───────────────────────────────────
    if state_param != state.rest_oauth_state:
        _log_step(
            step=4,
            label="State mismatch — request rejected",
            detail=(
                "The state parameter returned by Lucid does not match what was stored "
                "when the flow was initiated. This can happen if the server restarted "
                "mid-flow (wiping in-memory state) or if the request was forged. "
                f"Expected: {str(state.rest_oauth_state)[:8] if state.rest_oauth_state else 'None (server restarted)'} "
                f"Received: {str(state_param)[:8] if state_param else 'None'}"
            ),
            status="error",
            request=None,
            response={"error": "state_mismatch"},
        )
        return RedirectResponse(url="/?auth_error=state_mismatch")

    _log_step(
        step=4,
        label="State token validated — CSRF check passed",
        detail=(
            "The state parameter returned by Lucid matches what was stored in "
            "server memory when the flow started. This confirms the redirect is "
            "genuine and not a cross-site request forgery attempt."
        ),
        status="ok",
        request=None,
        response={"csrf_check": "passed"},
    )

    # ── Step 5: Exchange authorization code for access token ──────────────────
    # Build the token request body. This is a server-to-server POST — the
    # client_secret is included here but never sent to the browser.
    token_request_body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": LUCID_REDIRECT_URI,
        "client_id": LUCID_CLIENT_ID,
        "client_secret": LUCID_CLIENT_SECRET,
    }

    _log_step(
        step=5,
        label="Token request — POST to Lucid token endpoint",
        detail=(
            f"Server-to-server POST to {LUCID_TOKEN_URL}. "
            "The client_secret is included in this request — it is sent directly "
            "from the backend server to Lucid's servers and never touches the browser. "
            "This is the key security property of the Authorization Code flow."
        ),
        status="pending",
        request={
            "method": "POST",
            "url": LUCID_TOKEN_URL,
            "headers": {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            "body": {
                "grant_type": "authorization_code",
                "code": code[:8] + "•••• (truncated)",
                "redirect_uri": LUCID_REDIRECT_URI,
                "client_id": LUCID_CLIENT_ID,
                "client_secret": "••••••••••••  (never sent to browser)",
            },
        },
        response=None,
    )

    token_data, raw_response = await _exchange_code_for_token(token_request_body)

    if token_data is None:
        _log_step(
            step=5,
            label="Token exchange failed",
            detail=(
                "The POST to Lucid's token endpoint failed. "
                "Check that LUCID_CLIENT_ID, LUCID_CLIENT_SECRET, and LUCID_REDIRECT_URI "
                "in .env exactly match what is registered in the Lucid Developer Portal."
            ),
            status="error",
            request=None,
            response=raw_response or {"error": "token_exchange_failed"},
        )
        return RedirectResponse(url="/?auth_error=token_exchange_failed")

    # ── Store the token and log success ───────────────────────────────────────
    _store_rest_token(token_data)
    scopes_granted = " ".join(state.rest_token_scopes) or "unknown"

    # Build a display-safe version of the token response (redact the token itself)
    display_token_response = dict(token_data)
    if "access_token" in display_token_response:
        raw_token = display_token_response["access_token"]
        display_token_response["access_token"] = raw_token[:8] + "•••• (stored in server memory only)"

    _log_step(
        step=5,
        label="Access token acquired",
        detail=(
            f"Token stored in server memory. "
            f"Scopes granted: {scopes_granted}. "
            f"Expires in: {token_data.get('expires_in', 'unknown')}s. "
            f"Token type: {token_data.get('token_type', 'Bearer')}. "
            f"Nothing written to disk — token is lost on server restart."
        ),
        status="ok",
        request=None,
        response=display_token_response,
    )

    # Clear the one-time oauth state now that the flow is complete
    state.rest_oauth_state = None

    return RedirectResponse(url="/?auth_success=true")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _explain_oauth_error(error: str, description: str | None) -> str:
    """Return a plain-English explanation of a Lucid OAuth error code."""
    explanations = {
        "invalid_scope": (
            "Lucid rejected the requested scopes. The scope values in LUCID_OAUTH_SCOPES "
            "don't match what your OAuth client is authorised for. "
            "Valid Lucid scopes follow dot-notation: account.user:readonly, user.profile, "
            "lucidchart.document.content, etc. — NOT users:read or users:write. "
            "See: https://developer.lucid.co/reference/access-scopes"
        ),
        "access_denied": (
            "The user clicked Cancel on Lucid's consent screen, or the OAuth client "
            "is not authorised for this Lucid account."
        ),
        "invalid_client": (
            "Lucid doesn't recognise the client_id. Check that LUCID_CLIENT_ID in .env "
            "matches exactly what is shown in your Lucid Developer Portal app settings."
        ),
        "invalid_request": (
            "The authorization request was malformed. Check that LUCID_REDIRECT_URI in .env "
            "is registered exactly in the Lucid Developer Portal — including http vs https, "
            "port number, and no trailing slash."
        ),
    }
    base = explanations.get(error, f"Lucid returned error code '{error}'.")
    if description and description != error:
        return f"{base}  Lucid's message: \"{description}\""
    return base


async def _exchange_code_for_token(payload: dict) -> tuple[dict | None, dict | None]:
    """
    POST to Lucid's token endpoint to exchange an authorization code for an
    access token. Returns (parsed_json, raw_response_info) — raw_response_info
    is always populated so it can be logged even on failure.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                LUCID_TOKEN_URL,
                data=payload,
                headers={"Accept": "application/json"},
                timeout=10.0,
            )

        raw_info = {
            "status_code": response.status_code,
            "body": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text,
        }

        response.raise_for_status()
        return response.json(), raw_info

    except httpx.HTTPStatusError as exc:
        raw_info = {
            "status_code": exc.response.status_code,
            "body": exc.response.text,
        }
        print(f"[auth] Token exchange failed: {exc.response.status_code} {exc.response.text}")
        return None, raw_info
    except httpx.RequestError as exc:
        print(f"[auth] Token exchange network error: {exc}")
        return None, {"error": str(exc)}


def _log_account_step(
    step: int,
    label: str,
    detail: str,
    status: str,
    request: dict | None = None,
    response: dict | None = None,
) -> None:
    """Append a step to the account OAuth flow log."""
    _account_oauth_flow_log.append({
        "step": step,
        "label": label,
        "detail": detail,
        "status": status,
        "request": request,
        "response": response,
    })


def _store_rest_token(token_data: dict) -> None:
    """Write the user token response fields into app.state — including refresh token."""
    state.rest_access_token = token_data.get("access_token")
    state.rest_refresh_token = token_data.get("refresh_token")  # may be None
    state.rest_token_type = token_data.get("token_type", "Bearer")

    expires_in = token_data.get("expires_in")
    if expires_in:
        state.rest_token_expires_in = int(expires_in)
        state.rest_token_expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))
    else:
        state.rest_token_expires_in = None
        state.rest_token_expires_at = None

    raw_scopes = token_data.get("scope", "")
    state.rest_token_scopes = raw_scopes.split() if raw_scopes else []


def _store_rest_account_token(token_data: dict) -> None:
    """Write the account token response fields into app.state — including refresh token."""
    state.rest_account_access_token = token_data.get("access_token")
    state.rest_account_refresh_token = token_data.get("refresh_token")
    state.rest_account_token_type = token_data.get("token_type", "Bearer")

    expires_in = token_data.get("expires_in")
    if expires_in:
        state.rest_account_token_expires_in = int(expires_in)
        state.rest_account_token_expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))
    else:
        state.rest_account_token_expires_in = None
        state.rest_account_token_expires_at = None

    raw_scopes = token_data.get("scope", "")
    state.rest_account_token_scopes = raw_scopes.split() if raw_scopes else []


# ── Account token OAuth flow ──────────────────────────────────────────────────

@router.get("/auth/lucid-account", summary="Initiate Lucid REST API account token OAuth flow")
async def auth_lucid_account(scopes: str | None = None) -> RedirectResponse:
    """
    Redirect the browser to Lucid's account authorization URL.

    This is identical to the user token flow except it uses
    https://lucid.app/oauth2/authorizeAccount instead of /authorize.
    The resulting token has account-admin scope, needed for createUser,
    listUsers, and other account-level operations.

    Args:
        scopes: Optional space-separated scope string from the UI scope selector.
                If not provided, falls back to LUCID_ACCOUNT_OAUTH_SCOPES from .env.
    """
    _reset_account_flow_log()

    oauth_state = secrets.token_urlsafe(32)
    state.rest_account_oauth_state = oauth_state

    _log_account_step(
        step=1,
        label="State token generated",
        detail=(
            "A cryptographically random value created with secrets.token_urlsafe(32). "
            "Stored in server memory. Lucid will echo it back on the callback — "
            "if it doesn't match, we reject the request as a potential CSRF attack."
        ),
        status="ok",
        request=None,
        response={"state_token": oauth_state[:8] + "••••••••  (truncated for display)"},
    )

    # Use UI-selected scopes if provided; fall back to .env defaults.
    if scopes:
        scope_list = [s.strip() for s in scopes.split() if s.strip()]
    else:
        scope_list = list(LUCID_ACCOUNT_OAUTH_SCOPES)
    scope_str = " ".join(scope_list)

    base_params = urlencode({
        "client_id": LUCID_CLIENT_ID,
        "redirect_uri": LUCID_ACCOUNT_REDIRECT_URI,
        "response_type": "code",
        "state": oauth_state,
    })
    scope_param = "scope=" + urlquote(scope_str, safe=":")
    authorization_url = f"{LUCID_ACCOUNT_AUTH_URL}?{base_params}&{scope_param}"

    _log_account_step(
        step=2,
        label="Authorization URL constructed",
        detail=(
            f"The browser will be redirected to Lucid's ACCOUNT authorization endpoint. "
            f"This URL (oauth2/authorizeAccount) produces an account-level token — "
            f"required for admin operations like createUser. "
            f"Scopes requested: {scope_str}."
        ),
        status="pending",
        request={
            "method": "GET (browser redirect)",
            "url": authorization_url,
            "params": {
                "client_id": LUCID_CLIENT_ID,
                "redirect_uri": LUCID_ACCOUNT_REDIRECT_URI,
                "response_type": "code",
                "scope": scope_str,
                "state": oauth_state[:8] + "•••• (truncated)",
            },
        },
        response=None,
    )

    return RedirectResponse(url=authorization_url)


@router.get("/callback-account", summary="Account token OAuth callback")
async def oauth_account_callback(
    code: str | None = None,
    state_param: str | None = Query(default=None, alias="state"),
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    """
    Lucid redirects here after account consent. Mirrors /callback exactly
    but writes into the account token state fields and uses the account redirect URI.
    """
    if error:
        _log_account_step(
            step=3,
            label=f"Lucid returned an error: {error}",
            detail=_explain_oauth_error(error, error_description),
            status="error",
            request=None,
            response={"error": error, "error_description": error_description or ""},
        )
        return RedirectResponse(url=f"/?account_auth_error={urlquote(error)}")

    if not code:
        _log_account_step(
            step=3,
            label="No authorization code received",
            detail=(
                "Lucid redirected back without a code parameter. "
                "Check that LUCID_ACCOUNT_REDIRECT_URI is registered in the Developer Portal."
            ),
            status="error",
            request=None,
            response={"error": "no_code"},
        )
        return RedirectResponse(url="/?account_auth_error=no_code_returned")

    _log_account_step(
        step=3,
        label="Authorization code received",
        detail=(
            "Lucid redirected back to /callback-account with a one-time authorization code. "
            "This will be exchanged for an account-level access token."
        ),
        status="ok",
        request=None,
        response={
            "code": code[:8] + "•••• (truncated)",
            "state": state_param[:8] + "•••• (truncated)" if state_param else None,
        },
    )

    if state_param != state.rest_account_oauth_state:
        _log_account_step(
            step=4,
            label="State mismatch — request rejected",
            detail=(
                "The state parameter returned by Lucid does not match what was stored. "
                f"Expected: {str(state.rest_account_oauth_state)[:8] if state.rest_account_oauth_state else 'None (server restarted)'} "
                f"Received: {str(state_param)[:8] if state_param else 'None'}"
            ),
            status="error",
            request=None,
            response={"error": "state_mismatch"},
        )
        return RedirectResponse(url="/?account_auth_error=state_mismatch")

    _log_account_step(
        step=4,
        label="State token validated — CSRF check passed",
        detail="The state parameter matches. This is a genuine redirect from Lucid.",
        status="ok",
        request=None,
        response={"csrf_check": "passed"},
    )

    token_request_body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": LUCID_ACCOUNT_REDIRECT_URI,
        "client_id": LUCID_CLIENT_ID,
        "client_secret": LUCID_CLIENT_SECRET,
    }

    _log_account_step(
        step=5,
        label="Token request — POST to Lucid token endpoint",
        detail=(
            f"Server-to-server POST to {LUCID_TOKEN_URL}. "
            "Requesting an account-level token. "
            "The client_secret is sent directly from the backend — never via the browser."
        ),
        status="pending",
        request={
            "method": "POST",
            "url": LUCID_TOKEN_URL,
            "body": {
                "grant_type": "authorization_code",
                "code": code[:8] + "•••• (truncated)",
                "redirect_uri": LUCID_ACCOUNT_REDIRECT_URI,
                "client_id": LUCID_CLIENT_ID,
                "client_secret": "•••••••••••• (never sent to browser)",
            },
        },
        response=None,
    )

    token_data, raw_response = await _exchange_code_for_token(token_request_body)

    if token_data is None:
        _log_account_step(
            step=5,
            label="Token exchange failed",
            detail=(
                "The POST to Lucid's token endpoint failed. "
                "Check LUCID_ACCOUNT_REDIRECT_URI matches the Developer Portal exactly."
            ),
            status="error",
            request=None,
            response=raw_response or {"error": "token_exchange_failed"},
        )
        return RedirectResponse(url="/?account_auth_error=token_exchange_failed")

    _store_rest_account_token(token_data)
    scopes_granted = " ".join(state.rest_account_token_scopes) or "unknown"

    display_token_response = dict(token_data)
    if "access_token" in display_token_response:
        raw_token = display_token_response["access_token"]
        display_token_response["access_token"] = raw_token[:8] + "•••• (stored in server memory only)"

    _log_account_step(
        step=5,
        label="Account token acquired",
        detail=(
            f"Account token stored in server memory. "
            f"Scopes granted: {scopes_granted}. "
            f"Expires in: {token_data.get('expires_in', 'unknown')}s. "
            f"This token unlocks account-admin operations like createUser."
        ),
        status="ok",
        request=None,
        response=display_token_response,
    )

    state.rest_account_oauth_state = None
    return RedirectResponse(url="/?account_auth_success=true")


# ── Required scopes ───────────────────────────────────────────────────────────

# Plain-English descriptions shown in the scope selector UI.
# Keys match the scope strings used in ENDPOINT_REGISTRY.
SCOPE_DESCRIPTIONS: dict[str, str] = {
    "account.user:readonly": "Read user accounts, emails, and profile data",
    "account.user": "Read and manage user accounts (create, modify)",
    "account.info": "Read basic account information (name, plan, ID)",
    "user.profile": "Read the authenticated user's own extended profile",
    "lucidchart.document.content:readonly": "Read Lucidchart document metadata and content",
    "lucidchart.document.content": "Read and modify Lucidchart documents (create, trash)",
    "lucidchart.document.content:admin.readonly": "Read all account documents — Enterprise Shield accounts only. Standard OAuth clients will get invalid_scope.",
    "lucidspark.document.content:readonly": "Read Lucidspark board content",
    "lucidspark.document.content": "Read and modify Lucidspark boards",
    "folder:readonly": "List folders and read their contents",
    "folder": "Create, rename, trash, and restore folders",
    "offline_access": "Receive a refresh token — allows renewing access without re-authenticating",
}


# Scopes that require special account entitlements (e.g. Enterprise Shield).
# These are shown in the scope selector unchecked by default with a warning label.
# Sending them to a standard OAuth client causes an invalid_scope error from Lucid.
ENTERPRISE_SCOPES: set[str] = {
    "lucidchart.document.content:admin.readonly",
    "lucidspark.document.content:admin.readonly",
    "lucidscale.document.content:admin.readonly",
}


@router.get("/auth/required-scopes", summary="Return scopes required by registered REST endpoints")
async def required_scopes() -> JSONResponse:
    """
    Compute the set of OAuth scopes required by all registered REST endpoints
    and return them grouped by token type (user / account).

    Each entry includes:
      - scope: the scope string
      - description: plain-English label for the UI
      - endpoints: list of endpoint keys that require this scope
      - enterprise_only: True if this scope requires a special Lucid entitlement
        (e.g. Enterprise Shield). These are shown unchecked by default in the UI
        because standard OAuth clients will get an invalid_scope error if they
        include them.

    This endpoint is the source of truth for the frontend scope selector —
    adding a new endpoint to ENDPOINT_REGISTRY automatically surfaces its
    scope here without any manual configuration.
    """
    from app.services.lucid_rest import ENDPOINT_REGISTRY

    user_scopes: dict[str, set[str]] = {}
    account_scopes: dict[str, set[str]] = {}

    for key, ep in ENDPOINT_REGISTRY.items():
        token_type = ep.get("token", "user")
        scope = ep.get("scope")
        # client_credentials endpoints use client_id/secret — no Bearer scope
        if not scope or token_type == "client_credentials":
            continue
        target = account_scopes if token_type == "account" else user_scopes
        if scope not in target:
            target[scope] = set()
        target[scope].add(key)

    # offline_access gives a refresh token — always include it for user tokens.
    # It's not tied to a specific endpoint but is essential for long-running sessions.
    user_scopes.setdefault("offline_access", set()).add("(refresh token — not endpoint-specific)")

    def format_group(group: dict[str, set[str]]) -> list[dict]:
        return [
            {
                "scope": scope,
                "description": SCOPE_DESCRIPTIONS.get(scope, ""),
                "endpoints": sorted(group[scope]),
                # enterprise_only scopes are shown unchecked in the UI by default —
                # standard OAuth clients don't have access to them.
                "enterprise_only": scope in ENTERPRISE_SCOPES,
            }
            for scope in sorted(group)
        ]

    return JSONResponse({
        "user": format_group(user_scopes),
        "account": format_group(account_scopes),
    })


# ── Auth status ───────────────────────────────────────────────────────────────

@router.get("/auth/status", summary="Return auth state for all three API surfaces")
async def auth_status() -> JSONResponse:
    """Return current authentication status for REST, SCIM, and MCP."""
    if state.scim_bearer_token is None and LUCID_SCIM_TOKEN:
        state.scim_bearer_token = LUCID_SCIM_TOKEN
    return JSONResponse(content=state.get_auth_status())


# ── Flow status endpoints ─────────────────────────────────────────────────────

@router.get("/auth/flow-status", summary="Return full OAuth flow log with request/response details")
async def auth_flow_status() -> JSONResponse:
    """
    Return the complete OAuth flow log including request bodies and response
    data at each step. The frontend renders this as a rich educational timeline
    in the Terminal tab after every auth attempt.
    """
    return JSONResponse(content={
        "steps": _oauth_flow_log,
        "authenticated": state.is_rest_authenticated(),
        "scopes": state.rest_token_scopes,
        "expires_at": state.rest_token_expires_at.isoformat() if state.rest_token_expires_at else None,
    })


@router.get("/auth/account-flow-status", summary="Return account token OAuth flow log")
async def auth_account_flow_status() -> JSONResponse:
    """Return the complete account OAuth flow log for the Terminal tab."""
    return JSONResponse(content={
        "steps": _account_oauth_flow_log,
        "authenticated": state.is_rest_account_authenticated(),
        "scopes": state.rest_account_token_scopes,
        "expires_at": state.rest_account_token_expires_at.isoformat() if state.rest_account_token_expires_at else None,
    })


# ── Token peek ────────────────────────────────────────────────────────────────

@router.get("/auth/token-peek", summary="Return current access tokens for manual use in token-management endpoints")
async def auth_token_peek() -> JSONResponse:
    """
    Return the currently stored access tokens so engineers can paste them
    into the introspect / revoke endpoints.

    Tokens are stored in server memory only — they are never sent to the
    browser during normal API calls. This endpoint is the deliberate escape
    hatch for token-management workflows where you need the raw value.

    Returns a partial redaction for display plus the full value for copy.
    """
    result = {}

    if state.is_rest_authenticated():
        tok = state.rest_access_token
        result["user_token"] = {
            # Full values for populating param fields
            "value": tok,
            "refresh_token": state.rest_refresh_token,
            # Display helpers
            "preview": tok[:12] + "••••" if tok else None,
            "refresh_token_preview": (state.rest_refresh_token[:12] + "••••") if state.rest_refresh_token else None,
            # Token metadata — the full educational picture
            "token_type": state.rest_token_type or "Bearer",
            "scopes": state.rest_token_scopes,
            "expires_at": state.rest_token_expires_at.isoformat() if state.rest_token_expires_at else None,
            "expires_in_seconds": state.rest_token_expires_in,
            "has_refresh_token": state.rest_refresh_token is not None,
        }
    else:
        result["user_token"] = None

    if state.is_rest_account_authenticated():
        tok = state.rest_account_access_token
        result["account_token"] = {
            "value": tok,
            "refresh_token": state.rest_account_refresh_token,
            "preview": tok[:12] + "••••" if tok else None,
            "refresh_token_preview": (state.rest_account_refresh_token[:12] + "••••") if state.rest_account_refresh_token else None,
            "token_type": state.rest_account_token_type or "Bearer",
            "scopes": state.rest_account_token_scopes,
            "expires_at": state.rest_account_token_expires_at.isoformat() if state.rest_account_token_expires_at else None,
            "expires_in_seconds": state.rest_account_token_expires_in,
            "has_refresh_token": state.rest_account_refresh_token is not None,
        }
    else:
        result["account_token"] = None

    return JSONResponse(content=result)


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/auth/logout", summary="Clear REST API token")
async def auth_logout() -> JSONResponse:
    """Wipe the in-memory REST token so the engineer can re-authenticate."""
    state.clear_rest_auth()
    return JSONResponse(content={"message": "REST auth cleared."})
