"""
app/services/lucid_mcp.py — Lucid MCP server client with Dynamic Client Registration.

This is the most complex auth model in the app. Key distinction from REST:
  - REST:  client_id + client_secret are pre-registered in the Lucid Developer Portal
  - MCP:   client_id + client_secret are issued fresh each session by Lucid's MCP server
            via Dynamic Client Registration (DCR). The mcp package handles this.

How the flow works (narrated for educational value):
  1. On first use, we POST to Lucid's MCP registration endpoint with our client metadata.
     Lucid responds with a freshly issued client_id and client_secret.
  2. We use those dynamic credentials to run a standard OAuth 2.0 Authorization Code Flow
     (same as REST, but with PKCE — Proof Key for Code Exchange — for extra security).
  3. The resulting access token is stored in app.state and used for all MCP requests.
  4. Requests go to the MCP server as Streamable HTTP (the modern MCP transport).
     The mcp package's OAuthClientProvider handles token attachment and refresh.

The mcp package (v1.26.0) exposes:
  - OAuthClientProvider  — httpx.Auth subclass that drives the full DCR + OAuth flow
  - TokenStorage         — Protocol we implement to store tokens in app.state
  - streamablehttp_client — async context manager for the MCP transport connection
  - ClientSession        — MCP session for calling tools and listing capabilities

Because the OAuth redirect requires a browser and a callback endpoint, we run the
auth flow interactively: the user clicks a link, approves in Lucid, and our
/mcp/callback route completes the handshake. Between initiation and callback completion,
we park the PKCE state in module-level storage.
"""

import anyio
import time
import secrets
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage, PKCEParameters
from mcp.client.streamable_http import streamablehttp_client

import app.state as state
from app.config import (
    LUCID_MCP_URL,
    LUCID_MCP_REDIRECT_URI,
)

# ── In-memory token storage implementation ─────────────────────────────────────
# TokenStorage is a Protocol — we implement it backed by app.state.
# Nothing is persisted to disk.

class InMemoryTokenStorage(TokenStorage):
    """
    Stores MCP OAuth tokens and client registration info in app.state.

    The mcp package calls these methods automatically during the OAuth flow.
    We write to app.state so the rest of the app can read auth status.
    """

    async def get_tokens(self) -> dict | None:
        """Return stored token dict or None if not yet authenticated."""
        if state.mcp_access_token is None:
            return None
        return {"access_token": state.mcp_access_token}

    async def set_tokens(self, tokens: dict) -> None:
        """Store the access token returned by the OAuth flow."""
        state.mcp_access_token = tokens.get("access_token")
        state.mcp_session_active = state.mcp_access_token is not None

    async def get_client_info(self) -> dict | None:
        """Return previously registered DCR client info, or None to trigger registration."""
        return _mcp_client_info

    async def set_client_info(self, client_info: dict) -> None:
        """Store the dynamically registered client_id/secret issued by Lucid."""
        global _mcp_client_info
        _mcp_client_info = client_info


# Module-level storage for the DCR-issued client credentials and PKCE state.
# Survives within a server session but is lost on restart (intentional).
_mcp_client_info: dict | None = None
_pending_oauth_state: str | None = None
_pending_pkce: PKCEParameters | None = None
_oauth_provider: OAuthClientProvider | None = None

# anyio event used to signal the callback has completed
_callback_event: anyio.Event | None = None
_callback_code: str | None = None
_callback_state: str | None = None


# ── Auth initiation ────────────────────────────────────────────────────────────

async def initiate_mcp_auth() -> str:
    """
    Begin the MCP OAuth + DCR flow. Returns the authorization URL the user
    must visit to grant consent.

    Called by GET /auth/mcp. After the user approves in Lucid, Lucid redirects
    to /mcp/callback, which calls complete_mcp_auth().
    """
    global _oauth_provider, _pending_oauth_state, _pending_pkce, _callback_event

    _callback_event = anyio.Event()

    storage = InMemoryTokenStorage()

    # OAuthClientProvider drives DCR + Authorization Code + PKCE automatically.
    # We pass redirect_handler and callback_handler to intercept the browser URL
    # and the callback code, rather than letting the SDK open a browser directly.
    auth_url_holder: list[str] = []

    async def redirect_handler(url: str) -> None:
        """Called by the SDK with the authorization URL. We capture it instead of opening a browser."""
        auth_url_holder.append(url)

    async def callback_handler() -> tuple[str, str | None]:
        """
        Called by the SDK to wait for the OAuth callback.
        We block until /mcp/callback posts the code via complete_mcp_auth().
        """
        # Wait for the callback event to be set by the route handler
        await _callback_event.wait()
        return (_callback_code or "", _callback_state)

    from mcp.client.auth.oauth2 import OAuthClientMetadata

    client_metadata = OAuthClientMetadata(
        client_name="lucid-api-explorer",
        redirect_uris=[LUCID_MCP_REDIRECT_URI],
        grant_types=["authorization_code"],
        response_types=["code"],
    )

    _oauth_provider = OAuthClientProvider(
        server_url=LUCID_MCP_URL,
        client_metadata=client_metadata,
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )

    # Kick off the flow in a background task so we can return the URL immediately.
    # The flow will pause inside callback_handler() until the callback arrives.
    async def run_flow() -> None:
        try:
            # Making a dummy request triggers the auth flow
            async with httpx.AsyncClient(auth=_oauth_provider) as client:
                await client.get(LUCID_MCP_URL, timeout=300.0)
        except Exception:
            pass  # Flow completion is signalled via the event; errors are surfaced in status

    # Start the flow without awaiting — it will suspend at callback_handler
    anyio.from_thread.run_sync(lambda: None)  # ensure event loop is running
    import asyncio
    asyncio.create_task(run_flow())

    # Wait briefly for the redirect_handler to be called with the auth URL
    for _ in range(50):  # up to 5 seconds
        await anyio.sleep(0.1)
        if auth_url_holder:
            break

    if not auth_url_holder:
        return ""

    return auth_url_holder[0]


async def complete_mcp_auth(code: str, state_param: str | None) -> None:
    """
    Called by /mcp/callback after Lucid redirects back with the auth code.
    Signals the callback_handler() that is blocking inside the OAuth flow.
    """
    global _callback_code, _callback_state
    _callback_code = code
    _callback_state = state_param
    if _callback_event is not None:
        _callback_event.set()


# ── Prompt execution ───────────────────────────────────────────────────────────

async def execute_mcp_prompt(prompt: str) -> dict:
    """
    Send a natural language prompt to the Lucid MCP server.

    The prompt is not sent directly to Lucid — instead we:
      1. Connect to the MCP server via Streamable HTTP (authenticated via OAuthClientProvider)
      2. List available tools
      3. Use Claude (via ai_client) to decide which tool(s) to call
      4. Execute the tool calls on the MCP server
      5. Return the full tool call log for display in the terminal

    Args:
        prompt: Natural language instruction from the engineer.

    Returns:
        Structured result dict with status, tool_calls, response, request log.
    """
    if not state.is_mcp_authenticated():
        return _error_result(
            "MCP not authenticated. Visit /auth/mcp to begin the OAuth + DCR flow.",
            status_code=401,
        )

    storage = InMemoryTokenStorage()

    from mcp.client.auth.oauth2 import OAuthClientMetadata
    client_metadata = OAuthClientMetadata(
        client_name="lucid-api-explorer",
        redirect_uris=[LUCID_MCP_REDIRECT_URI],
        grant_types=["authorization_code"],
        response_types=["code"],
    )

    provider = OAuthClientProvider(
        server_url=LUCID_MCP_URL,
        client_metadata=client_metadata,
        storage=storage,
    )

    tool_calls_log: list[dict] = []
    start = time.monotonic()

    try:
        async with streamablehttp_client(
            url=LUCID_MCP_URL,
            auth=provider,
            timeout=30.0,
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # List available tools so Claude can decide what to call
                tools_result = await session.list_tools()
                available_tools = [t.model_dump() for t in tools_result.tools]

                # Ask Claude which tool(s) to use for this prompt
                tool_decisions = await _plan_tool_calls(prompt, available_tools)

                # Execute each decided tool call
                for decision in tool_decisions:
                    tool_name = decision.get("tool")
                    tool_args = decision.get("arguments", {})

                    call_start = time.monotonic()
                    result = await session.call_tool(tool_name, tool_args)
                    call_latency = int((time.monotonic() - call_start) * 1000)

                    tool_calls_log.append({
                        "tool": tool_name,
                        "arguments": tool_args,
                        "result": [c.model_dump() for c in result.content],
                        "latency_ms": call_latency,
                        "is_error": result.isError,
                    })

    except Exception as exc:
        return _error_result(f"MCP session error: {exc}")

    latency_ms = int((time.monotonic() - start) * 1000)

    request_log = {
        "method": "POST",
        "url": LUCID_MCP_URL,
        "headers": {"Authorization": "Bearer ••••••••"},
        "body": {"prompt": prompt},
        "timestamp": datetime.utcnow().isoformat(),
    }

    result = {
        "status_code": 200,
        "body": {"tool_calls": tool_calls_log, "prompt": prompt},
        "request": request_log,
        "response_headers": {},
        "auth_method": "OAuth 2.0 + Dynamic Client Registration (MCP)",
        "latency_ms": latency_ms,
        "tool_calls": tool_calls_log,
        "curl_command": _mcp_curl_note(),
        "python_snippet": _mcp_python_note(),
    }

    state.last_request = request_log
    state.last_response = result

    return result


async def _plan_tool_calls(prompt: str, available_tools: list[dict]) -> list[dict]:
    """
    Ask Claude which MCP tools to call for the given prompt.
    Returns a list of {"tool": name, "arguments": {...}} dicts.

    Delegates to ai_client to stay within the single-SDK-caller constraint.
    """
    # Import here to avoid circular imports (ai_client imports nothing from mcp)
    from app.services.ai_client import _client, MODEL, _SYSTEM_PROMPT

    tools_summary = "\n".join(
        f"- {t['name']}: {t.get('description', 'no description')}"
        for t in available_tools
    )

    planning_prompt = f"""The engineer sent this prompt to the Lucid MCP server:
"{prompt}"

Available MCP tools:
{tools_summary}

Respond with a JSON array of tool calls to make. Each item: {{"tool": "tool_name", "arguments": {{...}}}}.
Only include tools that are clearly needed. If no tool fits, return an empty array [].
Respond with ONLY the JSON array, no explanation."""

    message = _client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": planning_prompt}],
    )

    import json
    text = message.content[0].text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return []


# ── List available tools (for the capabilities panel) ─────────────────────────

async def list_mcp_tools() -> list[dict]:
    """
    Connect to the MCP server and return the list of available tools.
    Used to populate the capabilities panel in State C of the workspace.
    """
    if not state.is_mcp_authenticated():
        return []

    storage = InMemoryTokenStorage()
    from mcp.client.auth.oauth2 import OAuthClientMetadata
    client_metadata = OAuthClientMetadata(
        client_name="lucid-api-explorer",
        redirect_uris=[LUCID_MCP_REDIRECT_URI],
        grant_types=["authorization_code"],
        response_types=["code"],
    )
    provider = OAuthClientProvider(
        server_url=LUCID_MCP_URL,
        client_metadata=client_metadata,
        storage=storage,
    )

    try:
        async with streamablehttp_client(url=LUCID_MCP_URL, auth=provider, timeout=15.0) as (
            read_stream, write_stream, _
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()
                return [t.model_dump() for t in result.tools]
    except Exception:
        return []


# ── Code display helpers ───────────────────────────────────────────────────────

def _mcp_curl_note() -> str:
    return (
        "# MCP uses Streamable HTTP — not directly reproducible with plain cURL.\n"
        "# Use the mcp Python package to interact with the MCP server:\n\n"
        "# pip install mcp\n"
        "# See the MCP Python SDK docs for client usage examples."
    )


def _mcp_python_note() -> str:
    return (
        "from mcp import ClientSession\n"
        "from mcp.client.streamable_http import streamablehttp_client\n"
        "from mcp.client.auth import OAuthClientProvider\n\n"
        "# Full example: https://github.com/anthropics/mcp-python\n"
        "# Authentication uses OAuth 2.0 + Dynamic Client Registration.\n"
        "# The OAuthClientProvider handles DCR and token management automatically."
    )


def _error_result(message: str, status_code: int = 400) -> dict:
    return {
        "status_code": status_code,
        "body": {"error": message},
        "request": {},
        "response_headers": {},
        "auth_method": "OAuth 2.0 + Dynamic Client Registration (MCP)",
        "latency_ms": 0,
        "tool_calls": [],
        "curl_command": _mcp_curl_note(),
        "python_snippet": _mcp_python_note(),
    }
