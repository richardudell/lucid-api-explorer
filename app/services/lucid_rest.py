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
import io
import zipfile
from datetime import datetime, timedelta

import httpx

import app.state as state
from app.config import LUCID_REST_BASE_URL, LUCID_CLIENT_ID, LUCID_CLIENT_SECRET

# ── Endpoint registry ──────────────────────────────────────────────────────────
# Maps endpoint keys (matching the frontend ENDPOINTS object) to their
# HTTP method and URL factory. URL factories are callables that accept
# the params dict and return the fully-resolved URL string.
#
# ENDPOINT_REGISTRY schema — each entry is a dict with these fields:
#   method       (str, required)            HTTP verb: "GET" | "POST" | "PUT" | "PATCH"
#   url          (Callable[[dict], str])    lambda(params) → fully-resolved URL string
#   token        (str, required)            Auth slot: "user" | "account" | "client_credentials"
#   scope        (str, optional)            OAuth scope required for this endpoint
#   has_body     (bool, optional)           True if the endpoint accepts a JSON request body
#   import_mode  (str, optional)            Special handling flag: "standard_import"
#   content_type (str, optional)            Overrides the default Content-Type header

def _url(path: str) -> str:
    return f"{LUCID_REST_BASE_URL}{path}"

# ── Request timeout constants ─────────────────────────────────────────────────
REST_REQUEST_TIMEOUT    = 15.0  # seconds: default httpx timeout for REST API calls
STANDARD_IMPORT_TIMEOUT = 30.0  # seconds: httpx timeout for Standard Import file upload

ENDPOINT_REGISTRY: dict[str, dict] = {
    "getUser": {
        "method": "GET",
        "url": lambda p: _url(f"/users/{p['userId']}"),
        "token": "user",
        "scope": "account.user:readonly",
    },
    "listUsers": {
        "method": "GET",
        "url": lambda p: _url("/users"),
        "token": "account",
        "scope": "account.user:readonly",
    },
    "userEmailSearch": {
        "method": "GET",
        "url": lambda p: _url(f"/users?email={p['email']}"),
        "token": "user",
        "scope": "account.user:readonly",
    },
    "getUserProfile": {
        "method": "GET",
        "url": lambda p: _url("/users/me/profile"),
        "token": "user",
        "scope": "account.user:readonly",
    },
    "createUser": {
        "method": "POST",
        "url": lambda p: _url("/users"),
        "has_body": True,
        "token": "account",
        "scope": "account.user",
    },

    # ── Accounts ──────────────────────────────────────────────────────────────

    "getAccountInfo": {
        "method": "GET",
        "url": lambda p: _url("/accounts/me"),
        "token": "user",
        "scope": "account.info",
    },

    # ── Documents ─────────────────────────────────────────────────────────────

    "searchAccountDocuments": {
        # Enterprise Shield accounts only — requires account token + admin doc scope
        "method": "POST",
        "url": lambda p: _url("/accounts/me/documents/search"),
        "has_body": True,
        "token": "account",
        "scope": "lucidchart.document.content:admin.readonly",
    },
    "searchDocuments": {
        "method": "POST",
        "url": lambda p: _url("/documents/search"),
        "has_body": True,
        "token": "user",
        "scope": "lucidchart.document.content:readonly",
    },
    "createDocument": {
        "method": "POST",
        "url": lambda p: _url("/documents"),
        "has_body": True,
        "token": "user",
        "scope": "lucidchart.document.content",
    },
    "importStandardImport": {
        "method": "POST",
        "url": lambda p: _url("/documents"),
        "token": "user",
        "scope": "lucidchart.document.content",
        "import_mode": "standard_import",
    },
    "getDocument": {
        "method": "GET",
        "url": lambda p: _url(f"/documents/{p['documentId']}"),
        "token": "user",
        "scope": "lucidchart.document.content:readonly",
    },
    "getDocumentContents": {
        "method": "GET",
        "url": lambda p: _url(f"/documents/{p['documentId']}/contents"),
        "token": "user",
        "scope": "lucidchart.document.content:readonly",
    },
    "trashDocument": {
        # POST to /trash — no body required; document ID is in the URL
        "method": "POST",
        "url": lambda p: _url(f"/documents/{p['documentId']}/trash"),
        "token": "user",
        "scope": "lucidchart.document.content",
    },

    # ── Folders ───────────────────────────────────────────────────────────────

    "getFolder": {
        "method": "GET",
        "url": lambda p: _url(f"/folders/{p['folderId']}"),
        "token": "user",
        "scope": "folder:readonly",
    },
    "createFolder": {
        "method": "POST",
        "url": lambda p: _url("/folders"),
        "has_body": True,
        "token": "user",
        "scope": "folder",
    },
    "updateFolder": {
        "method": "PATCH",
        "url": lambda p: _url(f"/folders/{p['folderId']}"),
        "has_body": True,
        "token": "user",
        "scope": "folder",
    },
    "trashFolder": {
        # POST to /trash — no body required
        "method": "POST",
        "url": lambda p: _url(f"/folders/{p['folderId']}/trash"),
        "token": "user",
        "scope": "folder",
    },
    "restoreFolder": {
        # POST to /restore — no body required
        "method": "POST",
        "url": lambda p: _url(f"/folders/{p['folderId']}/restore"),
        "token": "user",
        "scope": "folder",
    },
    "listFolderContents": {
        "method": "GET",
        "url": lambda p: _url(f"/folders/{p['folderId']}/contents"),
        "token": "user",
        "scope": "folder:readonly",
    },
    "listRootFolderContents": {
        # 'root' is a literal path segment, not a parameter
        "method": "GET",
        "url": lambda p: _url("/folders/root/contents"),
        "token": "user",
        "scope": "folder:readonly",
    },

    # ── Collaboration — Document (user) ──────────────────────────────────────
    # Docs: https://developer.lucid.co/reference/collaboration

    "listDocumentUserCollaborators": {
        "method": "GET",
        "url": lambda p: _url(f"/documents/{p['documentId']}/collaborators/users"),
        "token": "user",
        "scope": "lucidchart.document.content:readonly",
    },
    "getDocumentUserCollaborator": {
        "method": "GET",
        "url": lambda p: _url(f"/documents/{p['documentId']}/collaborators/users/{p['userId']}"),
        "token": "user",
        "scope": "lucidchart.document.content:readonly",
    },
    "putDocumentUserCollaborator": {
        "method": "PUT",
        "url": lambda p: _url(f"/documents/{p['documentId']}/collaborators/users/{p['userId']}"),
        "has_body": True,
        "token": "user",
        "scope": "lucidchart.document.content",
    },
    "deleteDocumentUserCollaborator": {
        "method": "DELETE",
        "url": lambda p: _url(f"/documents/{p['documentId']}/collaborators/users/{p['userId']}"),
        "token": "user",
        "scope": "lucidchart.document.content",
    },

    # ── Collaboration — Document (team) ───────────────────────────────────────

    "getDocumentTeamCollaborator": {
        "method": "GET",
        "url": lambda p: _url(f"/documents/{p['documentId']}/collaborators/teams/{p['teamId']}"),
        "token": "user",
        "scope": "lucidchart.document.content:readonly",
    },
    "putDocumentTeamCollaborator": {
        "method": "PUT",
        "url": lambda p: _url(f"/documents/{p['documentId']}/collaborators/teams/{p['teamId']}"),
        "has_body": True,
        "token": "user",
        "scope": "lucidchart.document.content",
    },
    "deleteDocumentTeamCollaborator": {
        "method": "DELETE",
        "url": lambda p: _url(f"/documents/{p['documentId']}/collaborators/teams/{p['teamId']}"),
        "token": "user",
        "scope": "lucidchart.document.content",
    },

    # ── Collaboration — Folder (user) ─────────────────────────────────────────

    "listFolderUserCollaborators": {
        "method": "GET",
        "url": lambda p: _url(f"/folders/{p['folderId']}/collaborators/users"),
        "token": "user",
        "scope": "folder:readonly",
    },
    "putFolderUserCollaborator": {
        "method": "PUT",
        "url": lambda p: _url(f"/folders/{p['folderId']}/collaborators/users/{p['userId']}"),
        "has_body": True,
        "token": "user",
        "scope": "folder",
    },
    "deleteFolderUserCollaborator": {
        "method": "DELETE",
        "url": lambda p: _url(f"/folders/{p['folderId']}/collaborators/users/{p['userId']}"),
        "token": "user",
        "scope": "folder",
    },

    # ── Collaboration — Folder (group / team) ─────────────────────────────────

    "listFolderGroupCollaborators": {
        "method": "GET",
        "url": lambda p: _url(f"/folders/{p['folderId']}/collaborators/groups"),
        "token": "user",
        "scope": "folder:readonly",
    },
    "putFolderGroupCollaborator": {
        "method": "PUT",
        "url": lambda p: _url(f"/folders/{p['folderId']}/collaborators/groups/{p['groupId']}"),
        "has_body": True,
        "token": "user",
        "scope": "folder",
    },
    "deleteFolderGroupCollaborator": {
        "method": "DELETE",
        "url": lambda p: _url(f"/folders/{p['folderId']}/collaborators/groups/{p['groupId']}"),
        "token": "user",
        "scope": "folder",
    },

    # ── Sharing — Document share links ────────────────────────────────────────
    # Docs: https://developer.lucid.co/reference/sharing

    "getDocumentShareLink": {
        "method": "GET",
        "url": lambda p: _url(f"/documents/{p['documentId']}/sharelink"),
        "token": "user",
        "scope": "lucidchart.document.content:readonly",
    },
    "createDocumentShareLink": {
        "method": "POST",
        "url": lambda p: _url(f"/documents/{p['documentId']}/sharelink"),
        "has_body": True,
        "token": "user",
        "scope": "lucidchart.document.content",
    },
    "updateDocumentShareLink": {
        "method": "PATCH",
        "url": lambda p: _url(f"/documents/{p['documentId']}/sharelink"),
        "has_body": True,
        "token": "user",
        "scope": "lucidchart.document.content",
    },
    "deleteDocumentShareLink": {
        "method": "DELETE",
        "url": lambda p: _url(f"/documents/{p['documentId']}/sharelink"),
        "token": "user",
        "scope": "lucidchart.document.content",
    },

    # ── Sharing — Folder share links ──────────────────────────────────────────

    "getFolderShareLink": {
        "method": "GET",
        "url": lambda p: _url(f"/folders/{p['folderId']}/sharelink"),
        "token": "user",
        "scope": "folder:readonly",
    },
    "createFolderShareLink": {
        "method": "POST",
        "url": lambda p: _url(f"/folders/{p['folderId']}/sharelink"),
        "has_body": True,
        "token": "user",
        "scope": "folder",
    },
    "updateFolderShareLink": {
        "method": "PATCH",
        "url": lambda p: _url(f"/folders/{p['folderId']}/sharelink"),
        "has_body": True,
        "token": "user",
        "scope": "folder",
    },
    "deleteFolderShareLink": {
        "method": "DELETE",
        "url": lambda p: _url(f"/folders/{p['folderId']}/sharelink"),
        "token": "user",
        "scope": "folder",
    },

    # ── Sharing — Accept share link ───────────────────────────────────────────

    "acceptShareLink": {
        "method": "POST",
        "url": lambda p: _url("/sharelinks/accept"),
        "has_body": True,
        "token": "user",
        "scope": "lucidchart.document.content",
    },

    # ── Teams ─────────────────────────────────────────────────────────────────
    # Docs: https://developer.lucid.co/reference/teams

    "listTeams": {
        "method": "GET",
        "url": lambda p: _url("/teams"),
        "token": "account",
        "scope": "account.team:readonly",
    },
    "createTeam": {
        "method": "POST",
        "url": lambda p: _url("/teams"),
        "has_body": True,
        "token": "account",
        "scope": "account.team",
    },
    "getTeam": {
        "method": "GET",
        "url": lambda p: _url(f"/teams/{p['teamId']}"),
        "token": "account",
        "scope": "account.team:readonly",
    },
    "updateTeam": {
        "method": "PATCH",
        "url": lambda p: _url(f"/teams/{p['teamId']}"),
        "has_body": True,
        "token": "account",
        "scope": "account.team",
    },
    "archiveTeam": {
        "method": "POST",
        "url": lambda p: _url(f"/teams/{p['teamId']}/archive"),
        "token": "account",
        "scope": "account.team",
    },
    "restoreTeam": {
        "method": "POST",
        "url": lambda p: _url(f"/teams/{p['teamId']}/restore"),
        "token": "account",
        "scope": "account.team",
    },
    "listUsersOnTeam": {
        "method": "GET",
        "url": lambda p: _url(f"/teams/{p['teamId']}/users"),
        "token": "account",
        "scope": "account.team:readonly",
    },
    "addUsersToTeam": {
        "method": "POST",
        "url": lambda p: _url(f"/teams/{p['teamId']}/users"),
        "has_body": True,
        "token": "account",
        "scope": "account.team",
    },
    "removeUsersFromTeam": {
        "method": "POST",
        "url": lambda p: _url(f"/teams/{p['teamId']}/users/remove"),
        "has_body": True,
        "token": "account",
        "scope": "account.team",
    },

    # ── Audit Logs ────────────────────────────────────────────────────────────
    # Docs: https://developer.lucid.co/reference/audit-logs

    "getAuditLogs": {
        "method": "GET",
        "url": lambda p: _url("/auditlog"),
        "token": "account",
        "scope": "account.auditlog:readonly",
    },
    "queryAuditLogs": {
        "method": "POST",
        "url": lambda p: _url("/auditlog/query"),
        "has_body": True,
        "token": "account",
        "scope": "account.auditlog:readonly",
    },

    # ── Folders — additional utility ──────────────────────────────────────────

    "searchFolders": {
        "method": "POST",
        "url": lambda p: _url("/folders/search"),
        "has_body": True,
        "token": "user",
        "scope": "folder:readonly",
    },

    # ── Users — content transfer ──────────────────────────────────────────────

    "transferUserContent": {
        "method": "POST",
        "url": lambda p: _url(f"/users/{p['userId']}/transfercontent"),
        "has_body": True,
        "token": "account",
        "scope": "account.user",
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
                "Use the 'Auth Account Token' button in the topbar to complete the OAuth flow.",
                status_code=401,
            )
        access_token = state.rest_account_access_token
        auth_method_label = "Bearer token (OAuth 2.0 — Account Token)"
    else:
        if not state.is_rest_authenticated():
            return _error_result(
                "Not authenticated. Use the auth buttons in the topbar to complete the OAuth flow.",
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

    # ── Standard Import multipart call ───────────────────────────────────────
    if ep.get("import_mode") == "standard_import":
        return await _execute_standard_import_call(
            url=url,
            params=params,
            headers=headers,
            auth_method_label=auth_method_label,
        )

    # Parse body for POST/PUT/PATCH endpoints
    body = None
    if ep.get("has_body") and params.get("body"):
        try:
            body = json.loads(params["body"])
            headers["Content-Type"] = "application/json"
        except json.JSONDecodeError as e:
            return _error_result(f"Invalid JSON body: {e}")

    # Record the outbound request for terminal display and narrative generation
    request_headers_log = {k: _redact_auth(k, v) for k, v in headers.items()}
    request_log = {
        "method": method,
        "url": url,
        "headers": request_headers_log,
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
                timeout=REST_REQUEST_TIMEOUT,
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

async def _execute_standard_import_call(
    url: str,
    params: dict,
    headers: dict,
    auth_method_label: str,
) -> dict:
    """
    Execute a Lucid Standard Import by uploading a generated .lucid zip file.

    Expected params from the frontend:
      - body: required Standard Import JSON text (document.json contents)
      - product: required ('lucidchart' or 'lucidspark')
      - title: optional
      - parent: optional folder ID
    """
    raw_body = (params.get("body") or "").strip()
    product = (params.get("product") or "").strip().lower()
    title = (params.get("title") or "").strip()
    parent = (params.get("parent") or "").strip()

    if not raw_body:
        return _error_result(
            "Standard Import JSON is required. Provide it in the 'body' field."
        )
    if product not in {"lucidchart", "lucidspark"}:
        return _error_result(
            "Invalid 'product'. Use 'lucidchart' or 'lucidspark'."
        )

    # Validate JSON and serialize in a stable format before packaging into .lucid.
    try:
        doc_json = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        return _error_result(f"Invalid Standard Import JSON: {exc}")

    # Backward-compatible normalization:
    # - fill missing page/shape IDs
    # - normalize label/type aliases from model output
    # - allow simple x/y/width/height geometry and convert to boundingBox
    # - convert simple page.lines references into line shapes
    _normalize_standard_import_document(doc_json)
    _normalize_standard_import_shapes(doc_json)
    _normalize_standard_import_lines_to_shapes(doc_json)

    def _build_lucid_bytes(payload: dict) -> bytes:
        lucid_buf = io.BytesIO()
        with zipfile.ZipFile(lucid_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("document.json", json.dumps(payload, separators=(",", ":")))
        return lucid_buf.getvalue()

    lucid_bytes = _build_lucid_bytes(doc_json)

    form_data = {
        "type": "x-application/vnd.lucid.standardImport",
        "product": product,
    }
    if title:
        form_data["title"] = title
    if parent:
        form_data["parent"] = parent

    async def _upload_once(payload_bytes: bytes):
        files = {
            "file": (
                "import.lucid",
                payload_bytes,
                "x-application/vnd.lucid.standardImport",
            )
        }
        request_log_local = {
            "method": "POST",
            "url": url,
            "headers": {k: _redact_auth(k, v) for k, v in headers.items()},
            "body": {
                **form_data,
                "file": {
                    "name": "import.lucid",
                    "content_type": "x-application/vnd.lucid.standardImport",
                    "bytes": len(payload_bytes),
                    "entries": ["document.json"],
                },
                "document_json_chars": len(raw_body),
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

        start = time.monotonic()
        try:
            async with httpx.AsyncClient() as client:
                response_local = await client.post(
                    url=url,
                    headers=headers,
                    data=form_data,
                    files=files,
                    timeout=STANDARD_IMPORT_TIMEOUT,
                )
        except httpx.RequestError as exc:
            return None, 0, {"error": f"Network error: {exc}"}, request_log_local

        latency_ms_local = int((time.monotonic() - start) * 1000)
        try:
            response_body_local = response_local.json()
        except Exception:
            response_body_local = {"raw": response_local.text}
        return response_local, latency_ms_local, response_body_local, request_log_local

    response, latency_ms, response_body, request_log = await _upload_once(lucid_bytes)
    if response is None:
        return _error_result(response_body.get("error", "Network error"), request_log=request_log)

    # Fallback path: if SI rejects connector payloads, retry once with all lines removed.
    # This preserves a successful document import while we keep improving line fidelity.
    details = response_body.get("details") if isinstance(response_body, dict) else {}
    import_error_code = details.get("import_error_code") if isinstance(details, dict) else None
    if response.status_code == 400 and import_error_code == "invalid_file":
        retry_doc = json.loads(json.dumps(doc_json))
        _strip_line_artifacts(retry_doc)
        retry_bytes = _build_lucid_bytes(retry_doc)
        retry_response, retry_latency, retry_body, retry_request_log = await _upload_once(retry_bytes)
        if retry_response is not None and retry_response.status_code < 400:
            response = retry_response
            latency_ms = retry_latency
            response_body = retry_body
            request_log = retry_request_log
            request_log["body"]["line_fallback"] = "retry_without_lines"

    result = {
        "status_code": response.status_code,
        "body": response_body,
        "request": request_log,
        "response_headers": dict(response.headers),
        "auth_method": auth_method_label,
        "latency_ms": latency_ms,
        "curl_command": _build_curl_standard_import(url, headers, form_data),
        "python_snippet": _build_python_standard_import(url, headers, form_data),
    }
    state.last_request = request_log
    state.last_response = result
    return result


def _normalize_standard_import_shapes(doc_json: dict) -> None:
    """
    Normalize shapes in-place to Standard Import format.

    Converts legacy/simple coordinates:
      x, y, width, height
    into:
      boundingBox: {x, y, w, h}
    """
    pages = doc_json.get("pages")
    if not isinstance(pages, list):
        return

    for page in pages:
        if not isinstance(page, dict):
            continue
        shapes = page.get("shapes")
        if not isinstance(shapes, list):
            continue
        for shape in shapes:
            if not isinstance(shape, dict):
                continue
            # Use the most stable schema subset for broad compatibility.
            # "style" payloads from AI are often diagram-engine-specific and can
            # invalidate imports, so we strip them server-side.
            shape.pop("style", None)
            if isinstance(shape.get("boundingBox"), dict):
                continue
            x = shape.get("x")
            y = shape.get("y")
            w = shape.get("w", shape.get("width"))
            h = shape.get("h", shape.get("height"))
            if all(isinstance(v, (int, float)) for v in (x, y, w, h)):
                shape["boundingBox"] = {
                    "x": x,
                    "y": y,
                    "w": w,
                    "h": h,
                }
                shape.pop("x", None)
                shape.pop("y", None)
                shape.pop("width", None)
                shape.pop("height", None)


def _normalize_standard_import_document(doc_json: dict) -> None:
    """
    Fill common missing fields and alias names from model/template output.
    """
    if not isinstance(doc_json, dict):
        return

    if "version" not in doc_json:
        doc_json["version"] = 1

    pages = doc_json.get("pages")
    if not isinstance(pages, list):
        return

    for p_idx, page in enumerate(pages):
        if not isinstance(page, dict):
            continue
        if not page.get("id"):
            page["id"] = f"page-{p_idx + 1}"
        if not page.get("title"):
            page["title"] = f"Page {p_idx + 1}"
        if not isinstance(page.get("shapes"), list):
            page["shapes"] = []

        for s_idx, shape in enumerate(page["shapes"]):
            if not isinstance(shape, dict):
                continue
            if not shape.get("id"):
                shape["id"] = f"{page['id']}-shape-{s_idx + 1}"
            # Common alias from model output
            if "label" in shape and "text" not in shape:
                shape["text"] = shape.get("label")
            shape.pop("label", None)
            # Coerce generic/fragile type variants into stable block shapes.
            shape_type = str(shape.get("type") or "").lower()
            if shape_type in {"", "shape"}:
                shape["type"] = "process"
            elif shape_type not in {"process", "terminator", "decision", "data", "line"}:
                shape["type"] = "process"


def _normalize_standard_import_lines_to_shapes(doc_json: dict) -> None:
    """
    Normalize page.lines to Lucid Standard Import line schema.

    Supported input forms:
    - simplified: {id, source, target, text?}
    - explicit: {id, lineType, endpoint1, endpoint2, ...}
    """
    pages = doc_json.get("pages")
    if not isinstance(pages, list):
        return

    for page in pages:
        if not isinstance(page, dict):
            continue
        lines = page.get("lines")
        shapes = page.get("shapes")
        if not isinstance(lines, list) or not isinstance(shapes, list):
            page.pop("lines", None)
            continue

        shape_by_id: dict[str, dict] = {}
        for s in shapes:
            if isinstance(s, dict) and isinstance(s.get("id"), str):
                shape_by_id[s["id"]] = s

        normalized_lines: list[dict] = []
        for idx, line in enumerate(lines):
            if not isinstance(line, dict):
                continue
            source = line.get("source")
            target = line.get("target")
            line_id = line.get("id") or f"{page.get('id', 'page')}-line-{idx + 1}"

            # Already explicit endpoint form
            if isinstance(line.get("endpoint1"), dict) and isinstance(line.get("endpoint2"), dict):
                endpoint1 = dict(line["endpoint1"])
                endpoint2 = dict(line["endpoint2"])
                if endpoint1.get("type") == "shapeEndpoint" and isinstance(endpoint1.get("shapeId"), str):
                    if endpoint1["shapeId"] not in shape_by_id:
                        continue
                    endpoint1.setdefault("style", "none")
                if endpoint2.get("type") == "shapeEndpoint" and isinstance(endpoint2.get("shapeId"), str):
                    if endpoint2["shapeId"] not in shape_by_id:
                        continue
                    endpoint2.setdefault("style", "arrow")
            else:
                # Simple source/target form
                if not (isinstance(source, str) and isinstance(target, str)):
                    continue
                if source not in shape_by_id or target not in shape_by_id:
                    continue
                endpoint1 = {
                    "type": "shapeEndpoint",
                    "style": "none",
                    "shapeId": source,
                }
                endpoint2 = {
                    "type": "shapeEndpoint",
                    "style": "arrow",
                    "shapeId": target,
                }

            normalized_line = {
                "id": line_id,
                "lineType": line.get("lineType") or "straight",
                "endpoint1": endpoint1,
                "endpoint2": endpoint2,
            }

            # SI expects line text as an array of text-area objects.
            line_text = line.get("text")
            if isinstance(line_text, str) and line_text.strip():
                normalized_line["text"] = [{
                    "text": line_text.strip(),
                    "position": 0.5,
                    "side": "middle",
                }]
            elif isinstance(line_text, list):
                normalized_line["text"] = line_text

            normalized_lines.append(normalized_line)

        if normalized_lines:
            page["lines"] = normalized_lines
        else:
            page.pop("lines", None)


def _strip_line_artifacts(doc_json: dict) -> None:
    """
    Remove all line primitives from an SI document (both page.lines and shape.type=line).
    Used as a retry fallback when Lucid rejects connector payloads.
    """
    pages = doc_json.get("pages")
    if not isinstance(pages, list):
        return
    for page in pages:
        if not isinstance(page, dict):
            continue
        page.pop("lines", None)
        shapes = page.get("shapes")
        if not isinstance(shapes, list):
            continue
        page["shapes"] = [
            s for s in shapes
            if not (isinstance(s, dict) and str(s.get("type", "")).lower() == "line")
        ]


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
                response = await client.post(url, json=body_data, headers=headers, timeout=REST_REQUEST_TIMEOUT)
            else:
                response = await client.post(url, data=body_data, headers=headers, timeout=REST_REQUEST_TIMEOUT)
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
        _update_state_from_token_response(
            response_body,
            params,
            token_type=params.get("token_slot", "user"),
        )

    # Build the display body — for refreshAccessToken we show the token fully
    # (redacted preview for security-conscious display) but with clear labels.
    # For introspect/revoke, the response never contains a raw token, so no redaction needed.
    display_body = dict(response_body) if isinstance(response_body, dict) else response_body
    if isinstance(display_body, dict) and "access_token" in display_body and endpoint_key == "refreshAccessToken":
        tok = str(display_body.get("access_token") or "")
        refresh_tok = str(display_body.get("refresh_token") or "")
        tok_preview = (tok[:12] + "••••") if tok else None
        refresh_preview = (refresh_tok[:12] + "••••") if refresh_tok else None
        # Preserve educational metadata without returning raw tokens.
        display_body = {
            "access_token_preview": tok_preview,
            "token_type": display_body.get("token_type", "Bearer"),
            "expires_in": display_body.get("expires_in"),
            "refresh_token_preview": refresh_preview,
            "scope": display_body.get("scope"),
            "_note": (
                "Tokens were saved to server memory. "
                "Use the token-source buttons in params to populate token fields."
            ),
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


def _update_state_from_token_response(
    token_data: dict,
    params: dict,
    token_type: str = "user",
) -> None:
    """
    After a successful refreshAccessToken call, persist the new token into state.

    Args:
        token_data: The parsed JSON body from Lucid's token endpoint.
        params:     The original request params dict (used only to read grant_type).
        token_type: Which slot to write — "user" or "account". Supplied explicitly
                    by the caller via the token_slot param on the frontend form.
                    This replaces the previous approach of inferring the slot by
                    comparing the incoming refresh token to values in memory, which
                    failed silently after a server restart (both slots empty).

    This keeps the app authenticated with the latest token without requiring
    a full OAuth re-flow, and makes the 'Use user/account token' helpers in
    the token-management param fields immediately reflect the updated value.
    """
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

    if grant_type == "authorization_code":
        # Brand-new authorization code exchange — always a user token regardless of token_type
        write_user_token(token_data)
    elif token_type == "account":
        write_account_token(token_data)
    else:
        # Default: user slot (covers refresh_token grant and any other grant types)
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


def _build_curl_standard_import(url: str, headers: dict, form_data: dict) -> str:
    """Generate a cURL snippet for Standard Import using a local import.lucid file."""
    auth = _redact_auth("Authorization", headers.get("Authorization", "Bearer ••••••••"))
    lines = [
        f"curl -X POST '{url}' \\",
        f"     -H 'Authorization: {auth}' \\",
        "     -H 'Lucid-Api-Version: 1' \\",
        "     -F 'file=@import.lucid;type=x-application/vnd.lucid.standardImport' \\",
        f"     -F 'type={form_data['type']}' \\",
        f"     -F 'product={form_data['product']}'",
    ]
    if form_data.get("title"):
        lines[-1] += " \\"
        lines.append(f"     -F 'title={form_data['title']}'")
    if form_data.get("parent"):
        lines[-1] += " \\"
        lines.append(f"     -F 'parent={form_data['parent']}'")
    return "\n".join(lines)


def _build_python_standard_import(url: str, headers: dict, form_data: dict) -> str:
    """Generate a Python requests snippet for Standard Import."""
    safe_auth = _redact_auth("Authorization", headers.get("Authorization", "Bearer ••••••••"))
    data = {"type": form_data["type"], "product": form_data["product"]}
    if form_data.get("title"):
        data["title"] = form_data["title"]
    if form_data.get("parent"):
        data["parent"] = form_data["parent"]
    return (
        "import json\n"
        "import io\n"
        "import zipfile\n"
        "import requests\n\n"
        "# Build import.lucid from Standard Import JSON\n"
        "document = {\"version\": 1, \"pages\": []}  # replace with your Standard Import JSON\n"
        "buf = io.BytesIO()\n"
        "with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:\n"
        "    zf.writestr('document.json', json.dumps(document, separators=(',', ':')))\n"
        "buf.seek(0)\n\n"
        f"headers = {{'Authorization': '{safe_auth}', 'Lucid-Api-Version': '1'}}\n"
        f"data = {json.dumps(data, indent=4)}\n"
        "files = {'file': ('import.lucid', buf.getvalue(), 'x-application/vnd.lucid.standardImport')}\n\n"
        f"response = requests.post('{url}', headers=headers, data=data, files=files)\n"
        "print(response.status_code)\n"
        "print(response.json())\n"
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
