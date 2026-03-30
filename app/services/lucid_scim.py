"""
app/services/lucid_scim.py — Lucid SCIM API execution and logging.

Mirrors the structure of lucid_rest.py but uses the static SCIM bearer token
loaded from .env rather than an OAuth-acquired token.

Key difference from REST: there is no auth flow. The token is pre-loaded from
.env into app.state.scim_bearer_token on the first /auth/status poll. Every
SCIM request simply attaches it as a Bearer token — same wire format, different
source.

SCIM-specific notes:
- Content-Type for POST/PUT/PATCH must be 'application/scim+json' per the spec,
  though Lucid also accepts 'application/json'.
- PATCH uses the SCIM PatchOp schema, not a standard JSON merge patch.
- All responses follow the SCIM 2.0 schema with 'schemas' arrays.
"""

import time
import json
from datetime import datetime

import httpx

import app.state as state
from app.config import LUCID_SCIM_BASE_URL

# ── Endpoint registry ──────────────────────────────────────────────────────────

def _url(path: str) -> str:
    return f"{LUCID_SCIM_BASE_URL}{path}"

ENDPOINT_REGISTRY: dict[str, dict] = {
    "scimGetUser": {
        "method": "GET",
        "url": lambda p: _url(f"/Users/{p['userId']}"),
    },
    "scimGetAllUsers": {
        "method": "GET",
        "url": lambda p: _url("/Users"),
    },
    "scimCreateUser": {
        "method": "POST",
        "url": lambda p: _url("/Users"),
        "has_body": True,
    },
    "scimModifyUserPut": {
        "method": "PUT",
        "url": lambda p: _url(f"/Users/{p['userId']}"),
        "has_body": True,
    },
    "scimModifyUserPatch": {
        "method": "PATCH",
        "url": lambda p: _url(f"/Users/{p['userId']}"),
        "has_body": True,
    },

    # ── User — delete ─────────────────────────────────────────────────────────
    "scimDeleteUser": {
        "method": "DELETE",
        "url": lambda p: _url(f"/Users/{p['userId']}"),
    },

    # ── Groups ────────────────────────────────────────────────────────────────
    "scimGetGroup": {
        "method": "GET",
        "url": lambda p: _url(f"/Groups/{p['groupId']}"),
    },
    "scimGetAllGroups": {
        "method": "GET",
        "url": lambda p: _url("/Groups"),
    },
    "scimCreateGroup": {
        "method": "POST",
        "url": lambda p: _url("/Groups"),
        "has_body": True,
    },
    "scimModifyGroupPatch": {
        "method": "PATCH",
        "url": lambda p: _url(f"/Groups/{p['groupId']}"),
        "has_body": True,
    },
    "scimDeleteGroup": {
        "method": "DELETE",
        "url": lambda p: _url(f"/Groups/{p['groupId']}"),
    },

    # ── SCIM metadata endpoints ───────────────────────────────────────────────
    "scimServiceProviderConfig": {
        "method": "GET",
        "url": lambda p: _url("/ServiceProviderConfig"),
    },
    "scimResourceTypes": {
        "method": "GET",
        "url": lambda p: _url("/ResourceTypes"),
    },
    "scimSchemas": {
        "method": "GET",
        "url": lambda p: _url("/Schemas"),
    },
}


async def execute_scim_call(endpoint_key: str, params: dict) -> dict:
    """
    Execute a Lucid SCIM API call and return a structured result.

    Args:
        endpoint_key: One of the keys in ENDPOINT_REGISTRY (e.g. 'scimGetUser').
        params: Dict of parameter values from the frontend form.

    Returns:
        Same structure as lucid_rest.execute_rest_call() for consistency:
          status_code, body, request, response_headers, auth_method,
          latency_ms, curl_command, python_snippet.
    """
    if endpoint_key not in ENDPOINT_REGISTRY:
        return _error_result(f"Unknown SCIM endpoint: {endpoint_key}")

    if not state.is_scim_authenticated():
        return _error_result(
            "SCIM token not loaded. Ensure LUCID_SCIM_TOKEN is set in .env and the server has been started.",
            status_code=401,
        )

    ep = ENDPOINT_REGISTRY[endpoint_key]
    method = ep["method"]
    url = ep["url"](params)

    # SCIM uses the same Bearer token scheme as REST — different token, same header
    headers = {
        "Authorization": f"Bearer {state.scim_bearer_token}",
        "Accept": "application/scim+json",
    }

    # Parse and attach body for write operations
    body = None
    if ep.get("has_body") and params.get("body"):
        try:
            body = json.loads(params["body"])
            # SCIM spec requires application/scim+json for write operations
            headers["Content-Type"] = "application/scim+json"
        except (json.JSONDecodeError, TypeError) as e:
            return _error_result(f"Invalid JSON body: {e}")

    request_log = {
        "method": method,
        "url": url,
        "headers": {k: _redact_auth(k, v) for k, v in headers.items()},
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

    try:
        response_body = response.json()
    except Exception:
        response_body = {"raw": response.text}

    result = {
        "status_code": response.status_code,
        "body": response_body,
        "request": request_log,
        "response_headers": dict(response.headers),
        "auth_method": "Static Bearer Token (SCIM)",
        "latency_ms": latency_ms,
        "curl_command": _build_curl(method, url, headers, body),
        "python_snippet": _build_python(method, url, headers, body),
    }

    state.last_request = request_log
    state.last_response = result

    return result


# ── Code generation helpers ────────────────────────────────────────────────────

def _build_curl(method: str, url: str, headers: dict, body: dict | None) -> str:
    """Generate a cURL command reproducing the executed SCIM request."""
    header_flags = " \\\n     ".join(
        f"-H '{k}: {_redact_auth(k, v)}'" for k, v in headers.items()
    )
    body_flag = ""
    if body:
        body_flag = f" \\\n     -d '{json.dumps(body)}'"
    return f"curl -X {method} '{url}' \\\n     {header_flags}{body_flag}"


def _build_python(method: str, url: str, headers: dict, body: dict | None) -> str:
    """Generate a Python requests snippet reproducing the executed SCIM request."""
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


def _redact_auth(header_name: str, value: str) -> str:
    """Partially redact Bearer tokens for safe display."""
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
        "auth_method": "Static Bearer Token (SCIM)",
        "latency_ms": 0,
        "curl_command": "",
        "python_snippet": "",
    }
