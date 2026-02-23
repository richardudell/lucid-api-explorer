"""
main.py — Entry point for lucid-api-explorer.

Starts the Uvicorn ASGI server programmatically.
Start command: python main.py
"""

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import PORT, DEBUG
from app.routes import auth, rest_api, scim_api, ai, mcp_api

app = FastAPI(title="Lucid API Explorer", version="1.0.0")

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(rest_api.router)
app.include_router(scim_api.router)
app.include_router(ai.router)
app.include_router(mcp_api.router)

# ── Static files ──────────────────────────────────────────────────────────────
# Serve the frontend (index.html, style.css, app.js) directly from FastAPI.
# The /static mount handles /static/... URLs; the root route serves index.html.
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root() -> FileResponse:
    """Serve the single-page app shell."""
    return FileResponse("static/index.html")


if __name__ == "__main__":
    # NOTE: reload=False is intentional — uvicorn's reloader spawns a child
    # worker process, and any restart wipes in-memory OAuth state (the CSRF
    # state token) mid-flow, causing state_mismatch errors on the callback.
    # During development, stop and restart manually after code changes.
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="debug" if DEBUG else "info",
    )
