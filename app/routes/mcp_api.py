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

from fastapi import APIRouter
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

# Import as app_state to avoid collision with FastAPI's `state` query param name
import app.state as app_state
from app.services.lucid_mcp import (
    complete_mcp_auth,
    execute_mcp_prompt,
    initiate_mcp_auth,
    list_mcp_tools,
)

router = APIRouter(tags=["MCP"])


# ── Auth initiation ────────────────────────────────────────────────────────────

@router.get("/auth/mcp", summary="Initiate MCP OAuth + Dynamic Client Registration flow")
async def auth_mcp() -> JSONResponse:
    """
    Begin the MCP auth flow. Returns the Lucid authorization URL the frontend
    should redirect the user to. The DCR step (registering client credentials)
    happens in the background before the authorization URL is generated.

    Returns JSON rather than a direct redirect so the frontend can show the URL
    and explain what DCR is before sending the user away.
    """
    auth_url = await initiate_mcp_auth()
    if not auth_url:
        return JSONResponse(
            content={"error": "Failed to generate MCP authorization URL. Check server logs."},
            status_code=500,
        )
    return JSONResponse(content={"auth_url": auth_url})


# ── OAuth callback ─────────────────────────────────────────────────────────────

@router.get("/mcp/callback", summary="MCP OAuth callback — complete auth handshake")
async def mcp_callback(
    code: str | None = None,
    state_param: str | None = None,  # named state_param to avoid shadowing app_state import
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

    await complete_mcp_auth(code, state_param)
    return RedirectResponse(url="/?mcp_auth_success=true")


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
async def mcp_prompt(body: PromptRequest) -> JSONResponse:
    """
    Send a natural language prompt to the Lucid MCP server.

    The service layer:
      1. Connects to the MCP server via Streamable HTTP (auth via OAuthClientProvider)
      2. Lists available tools
      3. Uses Claude to plan which tool(s) to call
      4. Executes the tool calls and returns the full log for display
    """
    result = await execute_mcp_prompt(body.prompt)
    return JSONResponse(content=result, status_code=200)


# ── Tool listing ───────────────────────────────────────────────────────────────

@router.get("/api/mcp/tools", summary="List available Lucid MCP tools")
async def mcp_tools() -> JSONResponse:
    """
    Return the list of tools advertised by the Lucid MCP server.
    Used to populate the capabilities panel in the MCP workspace.
    Returns an empty list if not authenticated.
    """
    tools = await list_mcp_tools()
    return JSONResponse(content={"tools": tools})
