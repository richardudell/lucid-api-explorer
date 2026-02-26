"""
app/routes/mcp_api.py — Lucid MCP server proxy routes.

Routes:
  GET  /auth/mcp          — Initiate DCR + OAuth flow; returns authorization URL
  GET  /mcp/callback      — Receive OAuth code from Lucid; complete auth handshake
  GET  /auth/mcp/status   — Return MCP auth state (authenticated / not)
  POST /api/mcp/prompt    — Execute a natural language prompt against the MCP server
  GET  /api/mcp/tools     — List available MCP tools (for the capabilities panel)

The /mcp/callback endpoint is separate from /callback (REST OAuth) — MCP uses its
own redirect URI (http://localhost:8000/mcp/callback) to keep the flows distinct.
"""

from fastapi import APIRouter, Query, Request, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from urllib.parse import quote as urlquote

# Import as app_state to avoid collision with FastAPI's `state` query param name
import app.state as app_state
from app.errors import error_response_from_exception, error_response_from_result, success_response
from app.security import require_local_request_dep
from app.services.lucid_mcp import (
    complete_mcp_auth,
    execute_mcp_prompt,
    initiate_mcp_auth,
    list_mcp_tools,
)

router = APIRouter(tags=["MCP"], dependencies=[Depends(require_local_request_dep)])


# ── Auth initiation ────────────────────────────────────────────────────────────

@router.get("/auth/mcp", summary="Initiate MCP OAuth + Dynamic Client Registration flow")
async def auth_mcp(force: bool = False) -> JSONResponse:
    """
    Begin the MCP auth flow. Returns the Lucid authorization URL the frontend
    should redirect the user to. The DCR step (registering client credentials)
    happens in the background before the authorization URL is generated.

    Returns JSON rather than a direct redirect so the frontend can show the URL
    and explain what DCR is before sending the user away.
    """
    auth_url, error, already_authenticated = await initiate_mcp_auth(force_reauth=force)
    if not auth_url:
        if already_authenticated:
            return JSONResponse(content={"already_authenticated": True, "message": error}, status_code=200)
        return JSONResponse(
            content={"error": error or "Failed to generate MCP authorization URL. Check server logs."},
            status_code=500,
        )
    return JSONResponse(content={"auth_url": auth_url})


# ── OAuth callback ─────────────────────────────────────────────────────────────

@router.get("/mcp/callback", summary="MCP OAuth callback — complete auth handshake")
async def mcp_callback(
    code: str | None = None,
    state_param: str | None = Query(default=None, alias="state"),  # alias maps ?state= to state_param
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    """
    Lucid redirects here after the user approves MCP access.

    Signals the waiting OAuth flow (parked inside lucid_mcp.complete_mcp_auth())
    to resume with the authorization code, which it exchanges for a token.
    """
    if error:
        desc = error_description or error
        return RedirectResponse(url=f"/?mcp_auth_error={desc}")

    if not code:
        return RedirectResponse(url="/?mcp_auth_error=no_code_returned")

    authenticated, callback_error = await complete_mcp_auth(code, state_param)
    if authenticated:
        return RedirectResponse(url="/?mcp_auth_success=true")
    return RedirectResponse(url=f"/?mcp_auth_error={urlquote(callback_error or 'token_exchange_failed')}")


# ── Auth status ────────────────────────────────────────────────────────────────

@router.get("/auth/mcp/status", summary="Return MCP authentication status")
async def mcp_auth_status() -> JSONResponse:
    """Return whether the MCP session is currently active."""
    return JSONResponse(content={
        "authenticated": app_state.is_mcp_authenticated(),
        "session_active": app_state.mcp_session_active,
    })


# ── Prompt execution ───────────────────────────────────────────────────────────

class PromptRequest(BaseModel):
    """Natural language prompt from the MCP workspace."""
    prompt: str


@router.post("/api/mcp/prompt", summary="Execute a natural language MCP prompt")
async def mcp_prompt(request: Request, body: PromptRequest) -> JSONResponse:
    """
    Send a natural language prompt to the Lucid MCP server.

    The service layer:
      1. Connects to the MCP server via Streamable HTTP (auth via OAuthClientProvider)
      2. Lists available tools
      3. Uses Claude to plan which tool(s) to call
      4. Executes the tool calls and returns the full log for display
    """
    try:
        result = await execute_mcp_prompt(body.prompt)
    except Exception as exc:  # defensive guard for adapter exceptions
        return error_response_from_exception(request, exc)

    status = int(result.get("status_code", 500) or 500) if isinstance(result, dict) else 500
    if status >= 400:
        return error_response_from_result(request, result)
    return success_response(request, data=result, http_status=200)


# ── Tool listing ───────────────────────────────────────────────────────────────

@router.get("/api/mcp/tools", summary="List available Lucid MCP tools")
async def mcp_tools(request: Request) -> JSONResponse:
    """
    Return the list of tools advertised by the Lucid MCP server.
    Used to populate the capabilities panel in the MCP workspace.
    Returns an empty list if not authenticated.
    """
    try:
        tools = await list_mcp_tools()
        return success_response(request, data={"tools": tools}, http_status=200)
    except Exception as exc:
        return error_response_from_exception(request, exc)
