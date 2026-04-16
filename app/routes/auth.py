"""
app/routes/auth.py — OAuth 2.0 Authorization Code Flow for the Lucid REST API.

Two endpoints drive each flow:

  User token flow:
    GET /auth/lucid   — Step 1: redirect the browser to Lucid's user authorization URL.
    GET /callback     — Step 2: receive code, exchange for user access token.

  Account token flow (identical logic, different credentials and state slots):
    GET /auth/lucid-account  — Step 1: redirect to Lucid's account authorization URL.
    GET /callback-account    — Step 2: receive code, exchange for account access token.

Additional endpoints:

  GET /auth/status             — Returns current auth state for all three surfaces.
  GET /auth/flow-status        — Full step-by-step user OAuth flow log.
  GET /auth/account-flow-status — Full step-by-step account OAuth flow log.
  POST /auth/logout            — Clears REST token state so the engineer can re-authenticate.

Implementation note — deduplication:
  Both flows are structurally identical (same 5 steps, same CSRF/TTL logic, same
  token exchange). They differ only in which state fields, auth URL, redirect URI,
  and default scopes they use. We capture those differences in OAuthFlowConfig and
  run both flows through shared _run_oauth_initiate() / _run_oauth_callback() helpers.
"""

import secrets
import hashlib
import base64
import httpx
import logging

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable
from urllib.parse import urlencode, quote as urlquote

from fastapi import APIRouter, Query, Depends
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
    LUCID_OAUTH_CONFIGURED,
    SCIM_CONFIGURED,
    PKCE_ENABLED,
)
from app.security import require_local_request_dep

router = APIRouter(dependencies=[Depends(require_local_request_dep)])
log = logging.getLogger(__name__)

# ── OAuth state token TTL ─────────────────────────────────────────────────────
_OAUTH_STATE_TTL = 600  # seconds (10 minutes) — reject callbacks older than this

# ── Flow logs ─────────────────────────────────────────────────────────────────
# Separate lists for user and account flows.
# The frontend fetches these via /auth/flow-status and /auth/account-flow-status.

_oauth_flow_log: list[dict] = []
_account_oauth_flow_log: list[dict] = []


def _append_step(
    log_list: list[dict],
    step: int,
    label: str,
    detail: str,
    status: str,                   # 'ok' | 'error' | 'pending'
    request: dict | None = None,   # {method, url, headers, body} — what we sent
    response: dict | None = None,  # {status_code, body} — what we received
) -> None:
    """Append a richly-detailed step to an OAuth flow log list."""
    log_list.append({
        "step": step,
        "label": label,
        "detail": detail,
        "status": status,
        "request": request,
        "response": response,
    })


# ── OAuthFlowConfig — captures what differs between the two flows ─────────────

@dataclass
class OAuthFlowConfig:
    """
    Encapsulates all the parameters that differ between the user OAuth flow and
    the account OAuth flow. Pass one of the two pre-built instances to the shared
    _run_oauth_initiate() and _run_oauth_callback() helpers.
    """
    flow_name: str                # "user" or "account" — used in log messages
    auth_url: str                 # Lucid authorization endpoint
    redirect_uri: str             # Registered callback URL
    default_scopes: list[str]     # From config; overridden by UI scope selector
    log_list: list[dict]          # Reference to the module-level log list to append to
    store_token: Callable[[dict], None]       # Writes token fields into app.state
    get_oauth_state: Callable[[], str | None] # Reads current CSRF state from app.state
    set_oauth_state: Callable[[str | None], None]  # Writes CSRF state into app.state
    get_oauth_state_created_at: Callable[[], datetime | None]  # Reads TTL timestamp
    set_oauth_state_created_at: Callable[[datetime | None], None]  # Writes TTL timestamp
    get_pkce_verifier: Callable[[], str | None]
    set_pkce_verifier: Callable[[str | None], None]
    success_redirect: str         # URL to redirect to on success (e.g. "/?auth_success=true")
    error_prefix: str             # Query param prefix for error redirects (e.g. "auth_error")


# ── Pre-built configs for each flow ───────────────────────────────────────────

def _user_flow_config() -> OAuthFlowConfig:
    return OAuthFlowConfig(
        flow_name="user",
        auth_url=LUCID_AUTH_URL,
        redirect_uri=LUCID_REDIRECT_URI,
        default_scopes=list(LUCID_OAUTH_SCOPES),
        log_list=_oauth_flow_log,
        store_token=_store_rest_token,
        get_oauth_state=lambda: state.rest_oauth_state,
        set_oauth_state=lambda v: setattr(state, "rest_oauth_state", v),
        get_oauth_state_created_at=lambda: state.rest_oauth_state_created_at,
        set_oauth_state_created_at=lambda v: setattr(state, "rest_oauth_state_created_at", v),
        get_pkce_verifier=lambda: state.rest_pkce_verifier,
        set_pkce_verifier=lambda v: setattr(state, "rest_pkce_verifier", v),
        success_redirect="/?auth_success=true",
        error_prefix="auth_error",
    )


def _account_flow_config() -> OAuthFlowConfig:
    return OAuthFlowConfig(
        flow_name="account",
        auth_url=LUCID_ACCOUNT_AUTH_URL,
        redirect_uri=LUCID_ACCOUNT_REDIRECT_URI,
        default_scopes=list(LUCID_ACCOUNT_OAUTH_SCOPES),
        log_list=_account_oauth_flow_log,
        store_token=_store_rest_account_token,
        get_oauth_state=lambda: state.rest_account_oauth_state,
        set_oauth_state=lambda v: setattr(state, "rest_account_oauth_state", v),
        get_oauth_state_created_at=lambda: state.rest_account_oauth_state_created_at,
        set_oauth_state_created_at=lambda v: setattr(state, "rest_account_oauth_state_created_at", v),
        get_pkce_verifier=lambda: state.rest_account_pkce_verifier,
        set_pkce_verifier=lambda v: setattr(state, "rest_account_pkce_verifier", v),
        success_redirect="/?account_auth_success=true",
        error_prefix="account_auth_error",
    )


# ── Shared OAuth flow logic ───────────────────────────────────────────────────

def _run_oauth_initiate(cfg: OAuthFlowConfig, scopes: str | None) -> RedirectResponse:
    """
    Step 1 of the OAuth flow: generate a CSRF state token and build the
    authorization URL. Identical for user and account flows — cfg supplies
    the flow-specific values.
    """
    # Reset the log for a fresh flow
    cfg.log_list.clear()

    # Fast-fail with a clear UX error instead of sending users into a broken
    # redirect when OAuth client config is missing.
    if not LUCID_OAUTH_CONFIGURED:
        _append_step(
            cfg.log_list,
            step=1,
            label="OAuth config missing",
            detail=(
                "OAuth client settings are not configured. Set LUCID_CLIENT_ID, "
                "LUCID_CLIENT_SECRET, LUCID_REDIRECT_URI, and "
                "LUCID_ACCOUNT_REDIRECT_URI in .env, then restart the app."
            ),
            status="error",
            request=None,
            response={"error": "oauth_config_missing"},
        )
        return RedirectResponse(url=f"/?{cfg.error_prefix}=oauth_config_missing")

    # Generate CSRF state token and record its timestamp for TTL enforcement
    oauth_state = secrets.token_urlsafe(32)
    cfg.set_oauth_state(oauth_state)
    cfg.set_oauth_state_created_at(datetime.utcnow())

    if PKCE_ENABLED:
        pkce_verifier, pkce_challenge = _generate_pkce_pair()
        cfg.set_pkce_verifier(pkce_verifier)
    else:
        pkce_challenge = None

    _append_step(
        cfg.log_list,
        step=1,
        label="State token generated",
        detail=(
            "A cryptographically random value created with secrets.token_urlsafe(32). "
            "Stored in server memory. Lucid will echo it back on the callback — "
            "if it doesn't match, we reject the request as a potential CSRF attack."
            + (
                " A PKCE verifier/challenge pair is also generated for code-exchange binding."
                if PKCE_ENABLED else ""
            )
        ),
        status="ok",
        request=None,
        response={"state_token": oauth_state[:8] + "••••••••  (truncated for display)"},
    )

    # Build the authorization URL
    if scopes:
        scope_list = [s.strip() for s in scopes.split() if s.strip()]
    else:
        scope_list = cfg.default_scopes
    scope_str = " ".join(scope_list)

    auth_url_params: dict = {
        "client_id": LUCID_CLIENT_ID,
        "redirect_uri": cfg.redirect_uri,
        "response_type": "code",
        "state": oauth_state,
    }
    if PKCE_ENABLED and pkce_challenge:
        auth_url_params["code_challenge"] = pkce_challenge
        auth_url_params["code_challenge_method"] = "S256"

    base_params = urlencode(auth_url_params)
    scope_param = "scope=" + urlquote(scope_str, safe=":")
    authorization_url = f"{cfg.auth_url}?{base_params}&{scope_param}"

    log_params: dict = {
        "client_id": LUCID_CLIENT_ID,
        "redirect_uri": cfg.redirect_uri,
        "response_type": "code",
        "scope": scope_str,
        "state": oauth_state[:8] + "•••• (truncated)",
    }
    if PKCE_ENABLED:
        log_params["code_challenge_method"] = "S256"
        log_params["code_challenge"] = "•••• (S256 hash of verifier)"

    _append_step(
        cfg.log_list,
        step=2,
        label="Authorization URL constructed",
        detail=(
            f"The browser will be redirected to Lucid's {cfg.flow_name} authorization endpoint. "
            f"Scopes requested: {scope_str}. "
            "response_type=code tells Lucid we want an Authorization Code, not an implicit token. "
            "The redirect_uri must match exactly what is registered in the Developer Portal."
            + (
                " code_challenge binds this request to the code_verifier sent at token exchange (PKCE)."
                if PKCE_ENABLED else ""
            )
        ),
        status="pending",
        request={
            "method": "GET (browser redirect)",
            "url": authorization_url,
            "params": log_params,
        },
        response=None,
    )

    return RedirectResponse(url=authorization_url)


async def _run_oauth_callback(
    cfg: OAuthFlowConfig,
    code: str | None,
    state_param: str | None,
    error: str | None,
    error_description: str | None,
) -> RedirectResponse:
    """
    Steps 3–5 of the OAuth flow: validate state, exchange code for token, store token.
    Identical for user and account flows — cfg supplies the flow-specific values.
    """
    def err_redirect(reason: str) -> RedirectResponse:
        return RedirectResponse(url=f"/?{cfg.error_prefix}={urlquote(reason)}")

    # Step 3a: Handle explicit OAuth errors from Lucid
    if error:
        _append_step(
            cfg.log_list,
            step=3,
            label=f"Lucid returned an error: {error}",
            detail=_explain_oauth_error(error, error_description, cfg.flow_name),
            status="error",
            request=None,
            response={"error": error, "error_description": error_description or ""},
        )
        cfg.set_pkce_verifier(None)
        return err_redirect(error)

    # Step 3b: No code returned
    if not code:
        account_note = (
            " For the account token flow, make sure http://localhost:8000/callback-account "
            "is registered as a separate Redirect URI in the Lucid Developer Portal "
            "(in addition to /callback — they are two distinct entries)."
            if cfg.flow_name == "account" else ""
        )
        _append_step(
            cfg.log_list,
            step=3,
            label="No authorization code received",
            detail=(
                f"Lucid redirected back to the {cfg.flow_name} callback without a code parameter. "
                "This usually means the user denied consent, or the redirect_uri "
                "registered in the Developer Portal doesn't match the one in .env."
                + account_note
            ),
            status="error",
            request=None,
            response={"error": "no_code", "raw_params": {"state": state_param}},
        )
        cfg.set_pkce_verifier(None)
        return err_redirect("no_code_returned")

    # Step 3c: Code received
    _append_step(
        cfg.log_list,
        step=3,
        label="Authorization code received",
        detail=(
            f"Lucid redirected back to the {cfg.flow_name} callback with a one-time authorization code. "
            "This code is short-lived (valid for approximately 5 minutes) and can only be used once. "
            "It must be exchanged for an access token before it expires."
        ),
        status="ok",
        request=None,
        response={
            "code": code[:8] + "•••• (truncated)",
            "state": state_param[:8] + "•••• (truncated)" if state_param else None,
        },
    )

    # Step 4a: Reject stale CSRF state tokens (> 10 minutes old)
    created_at = cfg.get_oauth_state_created_at()
    if created_at is not None:
        age = (datetime.utcnow() - created_at).total_seconds()
        if age > _OAUTH_STATE_TTL:
            cfg.set_oauth_state(None)
            cfg.set_oauth_state_created_at(None)
            cfg.set_pkce_verifier(None)
            _append_step(
                cfg.log_list,
                step=4,
                label="State token expired — request rejected",
                detail=(
                    f"The OAuth state token was generated {int(age)}s ago, "
                    f"which exceeds the {_OAUTH_STATE_TTL}s TTL. "
                    "Start a new OAuth flow to re-authenticate."
                ),
                status="error",
                request=None,
                response={"error": "state_expired"},
            )
            return err_redirect("state_expired")

    # Step 4b: CSRF state comparison
    if state_param != cfg.get_oauth_state():
        cfg.set_pkce_verifier(None)
        _append_step(
            cfg.log_list,
            step=4,
            label="State mismatch — request rejected",
            detail=(
                "The state parameter returned by Lucid does not match what was stored "
                "when the flow was initiated. This can happen if the server restarted "
                "mid-flow (wiping in-memory state) or if the request was forged. "
                f"Expected: {str(cfg.get_oauth_state())[:8] if cfg.get_oauth_state() else 'None (server restarted)'} "
                f"Received: {str(state_param)[:8] if state_param else 'None'}"
            ),
            status="error",
            request=None,
            response={"error": "state_mismatch"},
        )
        return err_redirect("state_mismatch")

    _append_step(
        cfg.log_list,
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

    # Step 5: Exchange authorization code for access token (server-to-server)
    token_request_body: dict = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg.redirect_uri,
        "client_id": LUCID_CLIENT_ID,
        "client_secret": LUCID_CLIENT_SECRET,
    }

    if PKCE_ENABLED:
        pkce_verifier = cfg.get_pkce_verifier()
        if not pkce_verifier:
            _append_step(
                cfg.log_list,
                step=5,
                label="Missing PKCE verifier — request rejected",
                detail="PKCE verifier was missing from server state. Start a new OAuth flow.",
                status="error",
                request=None,
                response={"error": "missing_pkce_verifier"},
            )
            return err_redirect("missing_pkce_verifier")
        token_request_body["code_verifier"] = pkce_verifier

    log_body: dict = {
        "grant_type": "authorization_code",
        "code": code[:8] + "•••• (truncated)",
        "redirect_uri": cfg.redirect_uri,
        "client_id": LUCID_CLIENT_ID,
        "client_secret": "••••••••••••  (never sent to browser)",
    }
    if PKCE_ENABLED:
        log_body["code_verifier"] = "••••••••••••  (PKCE verifier, never sent to browser)"

    _append_step(
        cfg.log_list,
        step=5,
        label="Token request — POST to Lucid token endpoint",
        detail=(
            f"Server-to-server POST to {LUCID_TOKEN_URL}. "
            "The client_secret is included in this request — it is sent directly "
            "from the backend server to Lucid's servers and never touches the browser. "
            "This is the key security property of the Authorization Code flow."
            + (
                " The code_verifier proves this token request came from the same party "
                "that initiated the authorization request (PKCE binding)."
                if PKCE_ENABLED else ""
            )
        ),
        status="pending",
        request={
            "method": "POST",
            "url": LUCID_TOKEN_URL,
            "headers": {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            "body": log_body,
        },
        response=None,
    )

    token_data, raw_response = await _exchange_code_for_token(token_request_body)

    if token_data is None:
        account_note = (
            " For the account token flow, also confirm that "
            "http://localhost:8000/callback-account is registered as a separate "
            "Redirect URI in the Lucid Developer Portal (distinct from /callback), "
            "and that LUCID_ACCOUNT_OAUTH_SCOPES contains only scopes your OAuth "
            "client is approved for."
            if cfg.flow_name == "account" else ""
        )
        _append_step(
            cfg.log_list,
            step=5,
            label="Token exchange failed",
            detail=(
                "The POST to Lucid's token endpoint failed. "
                "Check that LUCID_CLIENT_ID, LUCID_CLIENT_SECRET, and the redirect_uri "
                "in .env exactly match what is registered in the Lucid Developer Portal."
                + account_note
            ),
            status="error",
            request=None,
            response=raw_response or {"error": "token_exchange_failed"},
        )
        if PKCE_ENABLED:
            cfg.set_pkce_verifier(None)
        return err_redirect("token_exchange_failed")

    if not isinstance(token_data.get("access_token"), str) or not token_data.get("access_token"):
        _append_step(
            cfg.log_list,
            step=5,
            label="Token payload missing access_token",
            detail="Lucid token response did not include a usable access_token.",
            status="error",
            request=None,
            response={"error": "invalid_token_payload"},
        )
        cfg.set_pkce_verifier(None)
        return err_redirect("invalid_token_payload")

    # Store the token and log success
    cfg.store_token(token_data)
    scopes_granted = " ".join(
        state.rest_token_scopes if cfg.flow_name == "user" else state.rest_account_token_scopes
    ) or "unknown"

    display_token_response = dict(token_data)
    if "access_token" in display_token_response:
        raw_tok = display_token_response["access_token"]
        display_token_response["access_token"] = raw_tok[:8] + "•••• (stored in server memory only)"
    if "refresh_token" in display_token_response and display_token_response["refresh_token"]:
        display_token_response["refresh_token"] = "•••••••••••• (stored in server memory only)"

    _append_step(
        cfg.log_list,
        step=5,
        label=f"{'Account token' if cfg.flow_name == 'account' else 'Access token'} acquired",
        detail=(
            f"Token stored in server memory. "
            f"Scopes granted: {scopes_granted}. "
            f"Expires in: {token_data.get('expires_in', 'unknown')}s. "
            f"Token type: {token_data.get('token_type', 'Bearer')}. "
            "Nothing written to disk — token is lost on server restart."
        ),
        status="ok",
        request=None,
        response=display_token_response,
    )

    # Clear the one-time OAuth state now that the flow is complete
    cfg.set_oauth_state(None)
    cfg.set_oauth_state_created_at(None)
    cfg.set_pkce_verifier(None)

    return RedirectResponse(url=cfg.success_redirect)


# ── Route handlers — thin wrappers around the shared flow helpers ─────────────

@router.get("/auth/lucid", summary="Initiate Lucid REST API OAuth flow")
async def auth_lucid(scopes: str | None = None) -> RedirectResponse:
    """
    Redirect the browser to Lucid's authorization URL (user token flow).

    Generates a cryptographically random `state` value (CSRF protection)
    and redirects the user to Lucid's consent screen. On approval, Lucid
    redirects back to /callback.

    Args:
        scopes: Optional space-separated scope string from the UI scope selector.
                If not provided, falls back to LUCID_OAUTH_SCOPES from .env.
    """
    return _run_oauth_initiate(_user_flow_config(), scopes)


@router.get("/callback", summary="OAuth callback — exchange code for user access token")
async def oauth_callback(
    code: str | None = None,
    state_param: str | None = Query(default=None, alias="state"),
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    """
    Lucid redirects here after the user grants (or denies) consent (user token flow).
    Validates state, exchanges the code for an access token, stores it in memory.
    """
    return await _run_oauth_callback(_user_flow_config(), code, state_param, error, error_description)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _explain_oauth_error(error: str, description: str | None, flow_name: str = "user") -> str:
    """Return a plain-English explanation of a Lucid OAuth error code."""
    redirect_uri_label = "LUCID_ACCOUNT_REDIRECT_URI" if flow_name == "account" else "LUCID_REDIRECT_URI"
    callback_path = "/callback-account" if flow_name == "account" else "/callback"
    account_portal_note = (
        f" For the account token flow, {callback_path} must be registered as its own "
        "separate Redirect URI entry in the Developer Portal — it is not covered by /callback."
        if flow_name == "account" else ""
    )

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
            f"The authorization request was malformed. Check that {redirect_uri_label} in .env "
            "is registered exactly in the Lucid Developer Portal — including http vs https, "
            "port number, and no trailing slash."
            + account_portal_note
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
        log.warning("OAuth token exchange failed with status=%s", exc.response.status_code)
        return None, raw_info
    except httpx.RequestError as exc:
        log.warning("OAuth token exchange network error: %s", exc)
        return None, {"error": str(exc)}


def _generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(72)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("utf-8")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge


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


@router.get("/auth/lucid-account", summary="Initiate Lucid REST API account token OAuth flow")
async def auth_lucid_account(scopes: str | None = None) -> RedirectResponse:
    """
    Redirect the browser to Lucid's account authorization URL (account token flow).

    This is structurally identical to the user token flow but uses
    https://lucid.app/oauth2/authorizeAccount instead of /authorize.
    The resulting token has account-admin scope, needed for createUser,
    listUsers, and other account-level operations.

    Args:
        scopes: Optional space-separated scope string from the UI scope selector.
                If not provided, falls back to LUCID_ACCOUNT_OAUTH_SCOPES from .env.
    """
    return _run_oauth_initiate(_account_flow_config(), scopes)


@router.get("/callback-account", summary="Account token OAuth callback")
async def oauth_account_callback(
    code: str | None = None,
    state_param: str | None = Query(default=None, alias="state"),
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    """
    Lucid redirects here after account consent (account token flow).
    Validates state, exchanges the code for an account-level access token, stores it in memory.
    """
    return await _run_oauth_callback(_account_flow_config(), code, state_param, error, error_description)


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
    "account.team:readonly": "Read team membership and structure — requires elevated account entitlement.",
    "account.team": "Read and manage teams — requires elevated account entitlement.",
    "account.auditlog:readonly": "Read account audit logs — requires elevated account entitlement.",
}


# Scopes that require special account entitlements (e.g. Enterprise Shield).
# These are shown in the scope selector unchecked by default with a warning label.
# Sending them to a standard OAuth client causes an invalid_scope error from Lucid.
ENTERPRISE_SCOPES: set[str] = {
    "lucidchart.document.content:admin.readonly",
    "lucidspark.document.content:admin.readonly",
    "lucidscale.document.content:admin.readonly",
    # These require elevated account entitlements — standard OAuth clients
    # get invalid_scope from Lucid if they are included in the scope request.
    "account.team",
    "account.team:readonly",
    "account.auditlog:readonly",
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
    if state.scim_bearer_token is None and SCIM_CONFIGURED and LUCID_SCIM_TOKEN:
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
