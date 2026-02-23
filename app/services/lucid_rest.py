"""
app/services/lucid_rest.py — Lucid REST API execution and logging.

All REST API calls flow through execute_rest_call(). It:
  1. Resolves the URL and method for the requested endpoint
  2. Attaches the in-memory Bearer token from app.state
  3. Makes the async HTTP request via httpx
  4. Records the full request/response into app.state (for narrative generation)
  5. Returns a structured result dict the route handler passes back to the frontend
"""

import time
import json
from datetime import datetime, timedelta

import httpx

import app.state as state
from app.config import LUCID_REST_BASE_URL, LUCID_CLIENT_ID, LUCID_CLIENT_SECRET, LUCID_TOKEN_URL

# ── Endpoint registry ──────────────────────────────────────────────────────────
# Maps endpoint keys (matching the frontend ENDPOINTS object) to their
# HTTP method and URL factory. URL factories are callables that accept
# the params dict and return the fully-resolved URL string.

def _url(path: str) -> str:
    return f"{LUCID_REST_BASE_URL}{path}"

ENDPOINT_REGISTRY: dict[str, dict] = {
    "getUser": {
        "method": "GET",
        "url": lambda p: _url(f"/users/{p['userId']}"),
        "token": "user",   # requires user token
    },
    "listUsers": {
        "method": "GET",
        "url": lambda p: _url("/users"),
        "token": "account",  # requires account token
    },
    "userEmailSearch": {
        "method": "GET",
        "url": lambda p: _url(f"/users?email={p['email']}"),
        "token": "user",
    },
    "getUserProfile": {
        "method": "GET",
        "url": lambda p: _url("/users/me/profile"),
        "token": "user",
    },
    "createUser": {
        "method": "POST",
        "url": lambda p: _url("/users"),
        "has_body": True,
        "token": "account",  # requires account token (account-admin scope)
    },

    # ── OAuth Token Management ────────────────────────────────────────────────
    # These endpoints authenticate with client_id + client_secret (no Bearer token).
    # They call Lucid's token endpoint directly, not the REST API user endpoints.

    "refreshAccessToken": {
        "method": "POST",
        "url": lambda p: "https://api.lucid.co/oauth2/token",
        "token": "client_credentials",  # uses client_id/client_secret, not Bearer
        "content_type": "application/json",
    },
    "introspectAccessToken": {
        "method": "POST",
        "url": lambda p: "https://api.lucid.co/oauth2/token/introspect",
        "token": "client_credentials",
        "content_type": "application/x-www-form-urlencoded",
    },
    "revokeAccessToken": {
        "method": "POST",
        "url": lambda p: "https://api.lucid.co/oauth2/token/revoke",
        "token": "client_credentials",
        "content_type": "application/x-www-form-urlencoded",
    },
}


async def execute_rest_call(endpoint_key: str, params: dict) -> dict:
    """
    Execute a Lucid REST API call and return a structured result.

    Args:
        endpoint_key: One of the keys in ENDPOINT_REGISTRY (e.g. 'getUser').
        params: Dict of parameter values collected from the frontend form.

    Returns:
        A dict containing:
          - status_code: HTTP status integer
          - body: Parsed JSON response body (or error detail)
          - request: Logged outbound request (method, url, headers, body)
          - response_headers: Dict of response headers
          - curl_command: Generated cURL string
          - python_snippet: Generated Python requests snippet
          - auth_method: Always 'Bearer token (OAuth 2.0)'
          - latency_ms: Round-trip time in milliseconds
    """
    if endpoint_key not in ENDPOINT_REGISTRY:
        return _error_result(f"Unknown endpoint: {endpoint_key}")

    ep = ENDPOINT_REGISTRY[endpoint_key]
    token_type = ep.get("token", "user")  # 'user' | 'account' | 'client_credentials'

    method = ep["method"]
    url = ep["url"](params)

    # ── Client-credentials endpoints (token management) ───────────────────────
    # These use client_id + client_secret in the body, not a Bearer token.
    if token_type == "client_credentials":
        return await _execute_token_management_call(endpoint_key, ep, url, params)

    # ── Select the correct Bearer token ───────────────────────────────────────
    if token_type == "account":
        if not state.is_rest_account_authenticated():
            return _error_result(
                "This endpoint requires an account token. "
                "Click 'Auth Account' in the topbar to complete the account OAuth flow.",
                status_code=401,
            )
        access_token = state.rest_account_access_token
        auth_method_label = "Bearer token (OAuth 2.0 — Account Token)"
    else:
        if not state.is_rest_authenticated():
            return _error_result(
                "Not authenticated. Click 'Re-auth REST' in the topbar to complete the OAuth flow.",
                status_code=401,
            )
        access_token = state.rest_access_token
        auth_method_label = "Bearer token (OAuth 2.0 Authorization Code — User Token)"

    # Build request headers — auth token is always injected here, never by the frontend
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Lucid-Api-Version": "1",
    }

    # Parse body for POST/PUT/PATCH endpoints
    body = None
    if ep.get("has_body") and params.get("body"):
        try:
            body = json.loads(params["body"])
            headers["Content-Type"] = "application/json"
        except json.JSONDecodeError as e:
            return _error_result(f"Invalid JSON body: {e}")

    # Record the outbound request for terminal display and narrative generation
    request_log = {
        "method": method,
        "url": url,
        "headers": headers,
        "body": body,
        "timestamp": datetime.utcnow().isoformat(),
    }

    start = time.monotonic()

    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=body,
                timeout=15.0,
            )
    except httpx.RequestError as exc:
        return _error_result(f"Network error: {exc}", request_log=request_log)

    latency_ms = int((time.monotonic() - start) * 1000)

    # Parse response body
    try:
        response_body = response.json()
    except Exception:
        response_body = {"raw": response.text}

    result = {
        "status_code": response.status_code,
        "body": response_body,
        "request": request_log,
        "response_headers": dict(response.headers),
        "auth_method": auth_method_label,
        "latency_ms": latency_ms,
        "curl_command": _build_curl(method, url, headers, body),
        "python_snippet": _build_python(method, url, headers, body),
    }

    # Store in state for narrative generation
    state.last_request = request_log
    state.last_response = result

    return result


# ── Token management call handler ─────────────────────────────────────────────

async def _execute_token_management_call(
    endpoint_key: str,
    ep: dict,
    url: str,
    params: dict,
) -> dict:
    """
    Execute one of the three OAuth token management endpoints.

    These differ from regular REST calls in two ways:
      1. Authentication is via client_id + client_secret in the request body,
         not a Bearer token in the Authorization header.
      2. The content type varies: token refresh uses application/json;
         introspect and revoke use application/x-www-form-urlencoded.

    The client_id and client_secret are injected from server config — they
    are never sent to the frontend or accepted from the frontend.
    """
    content_type = ep.get("content_type", "application/x-www-form-urlencoded")

    # Build the body — inject client credentials from server config
    # The frontend supplies the token/grant_type/refresh_token fields only
    if content_type == "application/json":
        # refreshAccessToken: build body from individual param fields.
        # Frontend now sends grant_type, refresh_token, code, redirect_uri as
        # separate params rather than a raw JSON textarea.
        grant_type = params.get("grant_type", "").strip()
        if not grant_type:
            return _error_result("'grant_type' is required. Select 'refresh_token' or 'authorization_code'.")

        user_body: dict = {"grant_type": grant_type}

        if grant_type == "refresh_token":
            rt = params.get("refresh_token", "").strip()
            if not rt:
                return _error_result("'refresh_token' is required when grant_type is 'refresh_token'.")
            user_body["refresh_token"] = rt
        elif grant_type == "authorization_code":
            code = params.get("code", "").strip()
            redirect_uri = params.get("redirect_uri", "").strip()
            if not code:
                return _error_result("'code' is required when grant_type is 'authorization_code'.")
            user_body["code"] = code
            if redirect_uri:
                user_body["redirect_uri"] = redirect_uri

        body_data = {
            "client_id": LUCID_CLIENT_ID,
            "client_secret": LUCID_CLIENT_SECRET,
            **user_body,
        }

        # Build display version — redact client_secret, truncate tokens
        request_body_display: dict = {"grant_type": grant_type}
        if "refresh_token" in user_body:
            rt_val = user_body["refresh_token"]
            request_body_display["refresh_token"] = rt_val[:8] + "•••• (truncated)"
        if "code" in user_body:
            request_body_display["code"] = user_body["code"][:8] + "•••• (truncated)"
        if "redirect_uri" in user_body:
            request_body_display["redirect_uri"] = user_body["redirect_uri"]
        request_body_display["client_id"] = LUCID_CLIENT_ID
        request_body_display["client_secret"] = "•••••••••••• (injected from server config)"
    else:
        # introspect / revoke: form-encoded with token param from frontend
        token_value = params.get("token", "").strip()
        if not token_value:
            return _error_result("'token' parameter is required for this endpoint.")
        body_data = {
            "client_id": LUCID_CLIENT_ID,
            "client_secret": LUCID_CLIENT_SECRET,
            "token": token_value,
        }
        request_body_display = {
            "client_id": LUCID_CLIENT_ID,
            "client_secret": "•••••••••••• (injected from server config)",
            "token": token_value[:8] + "•••• (truncated)",
        }

    headers = {
        "Content-Type": content_type,
        "Accept": "application/json",
    }

    request_log = {
        "method": "POST",
        "url": url,
        "headers": headers,
        "body": request_body_display,
        "timestamp": datetime.utcnow().isoformat(),
        "note": "client_id and client_secret are injected from server config — never from the browser",
    }

    start = time.monotonic()

    try:
        async with httpx.AsyncClient() as client:
            if content_type == "application/json":
                response = await client.post(url, json=body_data, headers=headers, timeout=15.0)
            else:
                response = await client.post(url, data=body_data, headers=headers, timeout=15.0)
    except httpx.RequestError as exc:
        return _error_result(f"Network error: {exc}", request_log=request_log)

    latency_ms = int((time.monotonic() - start) * 1000)

    try:
        response_body = response.json()
    except Exception:
        response_body = {"raw": response.text} if response.text else {"status": "ok (no body)"}

    # ── Post-success handling for refreshAccessToken ──────────────────────────
    # If this was a successful token refresh/exchange, persist the new token
    # data into state so the app stays authenticated with the freshest token.
    # We also show the FULL token object in the response — this is intentional:
    # the educational purpose of this endpoint is to make the token visible.
    if (
        endpoint_key == "refreshAccessToken"
        and response.status_code == 200
        and isinstance(response_body, dict)
        and "access_token" in response_body
    ):
        _update_state_from_token_response(response_body, params)

    # Build the display body — for refreshAccessToken we show the token fully
    # (redacted preview for security-conscious display) but with clear labels.
    # For introspect/revoke, the response never contains a raw token, so no redaction needed.
    display_body = dict(response_body) if isinstance(response_body, dict) else response_body
    if isinstance(display_body, dict) and "access_token" in display_body and endpoint_key == "refreshAccessToken":
        tok = display_body["access_token"]
        # Show enough to verify it changed, but annotate its meaning
        display_body = {
            "access_token": tok,  # full value — intentionally shown for educational use
            "token_type": display_body.get("token_type", "Bearer"),
            "expires_in": display_body.get("expires_in"),
            "refresh_token": display_body.get("refresh_token"),  # full value if present
            "scope": display_body.get("scope"),
            # Friendly annotation keys (not from Lucid — added by this app)
            "_note": "Token saved to server memory. Use 'Use user token' / 'Use account token' buttons to inspect or revoke it.",
        }

    result = {
        "status_code": response.status_code,
        "body": display_body,
        "request": request_log,
        "response_headers": dict(response.headers),
        "auth_method": "Client credentials (client_id + client_secret in request body)",
        "latency_ms": latency_ms,
        "curl_command": _build_curl_form(url, request_body_display, content_type),
        "python_snippet": _build_python_form(url, request_body_display, content_type),
    }

    state.last_request = request_log
    state.last_response = result
    return result


def _update_state_from_token_response(token_data: dict, params: dict) -> None:
    """
    After a successful refreshAccessToken call, persist the new token into
    state. We infer which token slot to update from the grant_type and
    whether the refresh_token in the request matched the user or account token.

    This keeps the app authenticated with the latest token without requiring
    a full OAuth re-flow, and makes the 'Use user/account token' helpers in
    the token-management param fields immediately reflect the updated value.
    """
    # Read individual params (refreshAccessToken now uses per-field params, not a body textarea)
    incoming_refresh = params.get("refresh_token", "").strip()
    grant_type = params.get("grant_type", "").strip()

    # Helper to write fields into state
    def write_user_token(td: dict) -> None:
        state.rest_access_token = td.get("access_token")
        state.rest_refresh_token = td.get("refresh_token", state.rest_refresh_token)  # keep old if not rotated
        state.rest_token_type = td.get("token_type", "Bearer")
        ei = td.get("expires_in")
        if ei:
            state.rest_token_expires_in = int(ei)
            state.rest_token_expires_at = datetime.utcnow() + timedelta(seconds=int(ei))
        raw_scopes = td.get("scope", "")
        if raw_scopes:
            state.rest_token_scopes = raw_scopes.split()

    def write_account_token(td: dict) -> None:
        state.rest_account_access_token = td.get("access_token")
        state.rest_account_refresh_token = td.get("refresh_token", state.rest_account_refresh_token)
        state.rest_account_token_type = td.get("token_type", "Bearer")
        ei = td.get("expires_in")
        if ei:
            state.rest_account_token_expires_in = int(ei)
            state.rest_account_token_expires_at = datetime.utcnow() + timedelta(seconds=int(ei))
        raw_scopes = td.get("scope", "")
        if raw_scopes:
            state.rest_account_token_scopes = raw_scopes.split()

    if grant_type == "refresh_token" and incoming_refresh:
        # Match the incoming refresh token to either the user or account slot
        if incoming_refresh == state.rest_refresh_token:
            write_user_token(token_data)
        elif incoming_refresh == state.rest_account_refresh_token:
            write_account_token(token_data)
        else:
            # Unknown refresh token — write to user slot as a safe default
            write_user_token(token_data)
    elif grant_type == "authorization_code":
        # Brand-new authorization code exchange — treat as a user token
        write_user_token(token_data)
    else:
        # Fallback: update user token slot
        write_user_token(token_data)


# ── Code generation helpers ────────────────────────────────────────────────────

def _build_curl(method: str, url: str, headers: dict, body: dict | None) -> str:
    """Generate a cURL command reproducing the executed request."""
    header_flags = " \\\n     ".join(
        f"-H '{k}: {_redact_auth(k, v)}'" for k, v in headers.items()
    )
    body_flag = ""
    if body:
        body_flag = f" \\\n     -d '{json.dumps(body)}'"
    return f"curl -X {method} '{url}' \\\n     {header_flags}{body_flag}"


def _build_python(method: str, url: str, headers: dict, body: dict | None) -> str:
    """Generate a Python requests snippet reproducing the executed request."""
    safe_headers = {k: _redact_auth(k, v) for k, v in headers.items()}
    lines = [
        "import requests",
        "",
        f"headers = {json.dumps(safe_headers, indent=4)}",
    ]
    if body:
        lines.append(f"\njson_body = {json.dumps(body, indent=4)}")
        body_arg = ", json=json_body"
    else:
        body_arg = ""

    lines += [
        "",
        f"response = requests.{method.lower()}(",
        f"    '{url}',",
        f"    headers=headers{body_arg}",
        ")",
        "",
        "print(response.status_code)",
        "print(response.json())",
    ]
    return "\n".join(lines)


def _build_curl_form(url: str, body: dict, content_type: str) -> str:
    """Generate a cURL command for form-encoded or JSON token management calls."""
    if content_type == "application/json":
        return (
            f"curl -X POST '{url}' \\\n"
            f"     -H 'Content-Type: application/json' \\\n"
            f"     -d '{json.dumps(body)}'"
        )
    fields = " \\\n     ".join(f"-d '{k}={v}'" for k, v in body.items())
    return f"curl -X POST '{url}' \\\n     -H 'Content-Type: application/x-www-form-urlencoded' \\\n     {fields}"


def _build_python_form(url: str, body: dict, content_type: str) -> str:
    """Generate a Python requests snippet for token management calls."""
    if content_type == "application/json":
        return (
            f"import requests\n\n"
            f"payload = {json.dumps(body, indent=4)}\n\n"
            f"response = requests.post(\n    '{url}',\n    json=payload\n)\n\n"
            f"print(response.status_code)\nprint(response.json())"
        )
    return (
        f"import requests\n\n"
        f"payload = {json.dumps(body, indent=4)}\n\n"
        f"response = requests.post(\n    '{url}',\n    data=payload\n)\n\n"
        f"print(response.status_code)\nprint(response.json())"
    )


def _redact_auth(header_name: str, value: str) -> str:
    """Partially redact Bearer tokens so they're safe to display in the UI."""
    if header_name.lower() == "authorization" and value.startswith("Bearer "):
        token = value[7:]
        return f"Bearer {token[:6]}••••••••" if len(token) > 6 else "Bearer ••••••••"
    return value


def _error_result(
    message: str,
    status_code: int = 400,
    request_log: dict | None = None,
) -> dict:
    """Return a standardised error result dict."""
    return {
        "status_code": status_code,
        "body": {"error": message},
        "request": request_log or {},
        "response_headers": {},
        "auth_method": "Bearer token (OAuth 2.0)",
        "latency_ms": 0,
        "curl_command": "",
        "python_snippet": "",
    }
