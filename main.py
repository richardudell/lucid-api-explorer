"""
main.py — Entry point for lucid-api-explorer.

Starts the Uvicorn ASGI server programmatically.
Start command: python main.py
"""

import uvicorn
import uuid
import sys
import os
import warnings
import ipaddress
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import PORT, DEBUG, HOST, ALLOW_REMOTE
from app.routes import auth, rest_api, scim_api, ai, mcp_api, saml

app = FastAPI(title="Lucid API Explorer", version="1.0.0")


def _assert_supported_python() -> None:
    """
    Guardrail for local onboarding.

    We recommend Python 3.12.x to avoid dependency mismatches seen in teammate
    demos on newer runtimes.
    """
    if sys.version_info[:2] == (3, 12):
        return
    found = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    strict = str(os.getenv("STRICT_PYTHON_VERSION", "")).strip().lower() in {"1", "true", "yes", "on"}
    message = (
        "Unsupported Python runtime for local onboarding.\n"
        f"Found: {found}\n"
        "Recommended: Python 3.12.x for this project.\n"
        "Quick fix with pyenv:\n"
        "  pyenv install 3.12.9\n"
        "  pyenv local 3.12.9\n"
    )
    if strict:
        raise RuntimeError(message)
    warnings.warn(message, RuntimeWarning, stacklevel=2)


@app.middleware("http")
async def correlation_id_middleware(request, call_next):
    """
    Correlation ID middleware:
      - accepts inbound X-Correlation-Id (if provided)
      - otherwise generates a UUID
      - stores value on request.state for route/services
      - mirrors value back on response headers
    """
    incoming = request.headers.get("X-Correlation-Id")
    cid = incoming.strip() if incoming and incoming.strip() else str(uuid.uuid4())
    request.state.correlation_id = cid

    response = await call_next(request)
    response.headers["X-Correlation-Id"] = cid
    return response


@app.middleware("http")
async def security_headers_middleware(request, call_next):
    response = await call_next(request)
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "form-action 'self' https://lucid.app https://*.lucid.app; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers.setdefault("Content-Security-Policy", csp)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(rest_api.router)
app.include_router(scim_api.router)
app.include_router(ai.router)
app.include_router(mcp_api.router)
app.include_router(saml.router)

# ── Static files ──────────────────────────────────────────────────────────────
# Serve the frontend (index.html, style.css, app.js) directly from FastAPI.
# The /static mount handles /static/... URLs; the root route serves index.html.
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root() -> FileResponse:
    """Serve the single-page app shell."""
    return FileResponse("static/index.html")


if __name__ == "__main__":
    _assert_supported_python()
    bind_host = HOST
    is_loopback = False
    try:
        is_loopback = ipaddress.ip_address(bind_host).is_loopback
    except ValueError:
        is_loopback = bind_host in {"localhost"}
    if not is_loopback and not ALLOW_REMOTE:
        raise RuntimeError(
            "Refusing non-local bind without ALLOW_REMOTE=true. "
            "Set HOST=127.0.0.1 for default local-only execution."
        )
    # NOTE: reload=False is intentional — uvicorn's reloader spawns a child
    # worker process, and any restart wipes in-memory OAuth state (the CSRF
    # state token) mid-flow, causing state_mismatch errors on the callback.
    # During development, stop and restart manually after code changes.
    uvicorn.run(
        "main:app",
        host=bind_host,
        port=PORT,
        reload=False,
        log_level="debug" if DEBUG else "info",
    )
