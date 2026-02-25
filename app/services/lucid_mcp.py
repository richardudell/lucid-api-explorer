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
we park the OAuth state in module-level storage so the callback can signal the waiting task.

Type alignment: the mcp package's TokenStorage Protocol requires:
  - get_tokens() -> OAuthToken | None
  - set_tokens(tokens: OAuthToken) -> None
  - get_client_info() -> OAuthClientInformationFull | None
  - set_client_info(client_info: OAuthClientInformationFull) -> None
We use the actual Pydantic model types, not plain dicts.
"""

import asyncio
import time
from datetime import datetime
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthToken, OAuthClientInformationFull, OAuthClientMetadata

import app.state as state
from app.config import (
    LUCID_MCP_URL,
    LUCID_MCP_REDIRECT_URI,
)

# ── In-memory token storage implementation ─────────────────────────────────────
# TokenStorage is a Protocol — we implement it backed by app.state.
# Nothing is persisted to disk.
#
# IMPORTANT: The mcp package requires the actual Pydantic model types here,
# not plain dicts. OAuthToken and OAuthClientInformationFull are Pydantic
# models from mcp.shared.auth — they validate and serialize the token data.

class InMemoryTokenStorage(TokenStorage):
    """
    Stores MCP OAuth tokens and client registration info in module-level state.

    The mcp package calls these methods automatically during the OAuth flow:
    - get_tokens() / set_tokens() manage the access/refresh token
    - get_client_info() / set_client_info() manage the DCR-issued client_id/secret

    We store the actual Pydantic models (OAuthToken, OAuthClientInformationFull)
    rather than plain dicts — the mcp package requires these types exactly.
    """

    async def get_tokens(self) -> OAuthToken | None:
        """Return stored OAuthToken or None if not yet authenticated."""
        return _mcp_token

    async def set_tokens(self, tokens: OAuthToken) -> None:
        """Store the OAuthToken returned by the OAuth flow."""
        global _mcp_token
        _mcp_token = tokens
        # Mirror the access token into app.state for the auth status indicator
        state.mcp_access_token = tokens.access_token
        state.mcp_session_active = True

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        """Return previously registered DCR client info, or None to trigger registration."""
        return _mcp_client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        """Store the dynamically registered client_id/secret issued by Lucid."""
        global _mcp_client_info
        _mcp_client_info = client_info


# Module-level storage for typed MCP auth objects.
# Survives within a server session but is lost on restart (intentional).
_mcp_token: OAuthToken | None = None
_mcp_client_info: OAuthClientInformationFull | None = None

# The shared OAuthClientProvider instance — created during initiate_mcp_auth()
# and reused for subsequent prompt execution. This ensures the DCR client_info
# is preserved across the auth handshake and prompt calls.
_oauth_provider: OAuthClientProvider | None = None

# asyncio.Event used to signal between the callback route and the waiting flow task
_callback_event: asyncio.Event | None = None
_callback_code: str | None = None
_callback_state: str | None = None

# Track the background auth task so we can check its status
_auth_task: asyncio.Task | None = None


# ── Auth initiation ────────────────────────────────────────────────────────────

def _make_client_metadata() -> OAuthClientMetadata:
    """Build the OAuthClientMetadata used for DCR registration."""
    return OAuthClientMetadata(
        client_name="lucid-api-explorer",
        redirect_uris=[LUCID_MCP_REDIRECT_URI],  # type: ignore[arg-type]
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    )


async def initiate_mcp_auth() -> str:
    """
    Begin the MCP OAuth + DCR flow. Returns the authorization URL the user
    must visit to grant consent.

    How this works:
    1. We create an OAuthClientProvider with our client metadata.
    2. We start a background task that makes a dummy request to the MCP server.
       The provider intercepts the 401 response and kicks off DCR + OAuth.
    3. The provider calls our redirect_handler with the authorization URL.
       We capture it and return it to the frontend.
    4. The provider then calls our callback_handler and waits for the code.
       We block on an asyncio.Event until /mcp/callback delivers the code.
    5. The provider exchanges the code for a token, calling set_tokens() on
       our InMemoryTokenStorage to persist the result.

    Called by GET /auth/mcp.
    """
    global _oauth_provider, _callback_event, _callback_code, _callback_state, _auth_task

    # Reset callback state for a fresh flow
    _callback_event = asyncio.Event()
    _callback_code = None
    _callback_state = None

    storage = InMemoryTokenStorage()
    auth_url_holder: list[str] = []
    auth_error_holder: list[str] = []

    async def redirect_handler(url: str) -> None:
        """
        Called by OAuthClientProvider with the Lucid authorization URL.
        Instead of opening a browser (which we can't do server-side), we
        capture the URL and return it to the frontend.
        """
        auth_url_holder.append(url)

    async def callback_handler() -> tuple[str, str | None]:
        """
        Called by OAuthClientProvider after redirect_handler — it blocks here
        waiting for the user to approve in Lucid and for /mcp/callback to deliver
        the authorization code.

        This is the bridge between the browser redirect and the server flow.
        The asyncio.Event is set by complete_mcp_auth() when the callback arrives.
        """
        assert _callback_event is not None
        await _callback_event.wait()
        return (_callback_code or "", _callback_state)

    _oauth_provider = OAuthClientProvider(
        server_url=LUCID_MCP_URL,
        client_metadata=_make_client_metadata(),
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )

    async def run_flow() -> None:
        """
        Trigger the OAuth flow by making a request to the MCP server.
        The OAuthClientProvider intercepts the 401 and starts DCR + OAuth.
        We use a short timeout on the HTTP call since we only need it to
        receive the 401 — the real work happens via the event system.
        """
        try:
            async with httpx.AsyncClient(auth=_oauth_provider) as client:
                # HEAD request to the MCP URL — we only need the 401 to trigger the flow.
                # The provider's async_auth_flow generator handles the 401 response,
                # runs DCR, builds the auth URL, and calls redirect_handler.
                # Then it parks at callback_handler waiting for the code.
                # Allow long timeout since callback_handler waits for user interaction.
                await client.get(LUCID_MCP_URL, timeout=600.0)
        except Exception as exc:
            # Most errors here are expected (the MCP endpoint may return non-200
            # after auth succeeds, or the task is cancelled). We only care about
            # capturing the auth URL and the token — both happen via storage callbacks.
            if "auth" in str(exc).lower() or "dcr" in str(exc).lower():
                auth_error_holder.append(str(exc))

    # Launch the flow as a background task. It will suspend inside callback_handler
    # until the OAuth callback arrives. We must not await it here — we return first.
    _auth_task = asyncio.create_task(run_flow())

    # Poll briefly for redirect_handler to be called with the auth URL.
    # DCR registration + building the auth URL takes ~1-3 seconds.
    import anyio
    for _ in range(100):  # up to 10 seconds
        await anyio.sleep(0.1)
        if auth_url_holder:
            break
        # Check if the task died early (unexpected error)
        if _auth_task.done():
            exc = _auth_task.exception()
            if exc:
                return ""
            break

    if not auth_url_holder:
        return ""

    return auth_url_holder[0]


async def complete_mcp_auth(code: str, state_param: str | None) -> None:
    """
    Called by /mcp/callback after Lucid redirects back with the auth code.
    Signals the callback_handler() that is blocking inside the OAuth flow.

    After this returns, the background task resumes, exchanges the code for
    a token, and calls InMemoryTokenStorage.set_tokens() to persist it.
    We wait briefly for the token exchange to complete before returning.
    """
    global _callback_code, _callback_state
    _callback_code = code
    _callback_state = state_param
    if _callback_event is not None:
        _callback_event.set()

    # Wait for the background task to finish the token exchange
    if _auth_task is not None and not _auth_task.done():
        try:
            import anyio
            await anyio.sleep(0.1)  # small grace period for the exchange to start
            # Wait up to 15s for the token exchange to complete
            await asyncio.wait_for(asyncio.shield(_auth_task), timeout=15.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            pass  # Token may still have been stored — check state


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

    # Reuse the provider that was created during auth — it holds the stored token
    # and registered client info. Creating a new one would lose DCR credentials.
    provider = _oauth_provider
    if provider is None:
        # Fallback: build a new provider with existing stored credentials
        storage = InMemoryTokenStorage()
        provider = OAuthClientProvider(
            server_url=LUCID_MCP_URL,
            client_metadata=_make_client_metadata(),
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
    Used to populate the capabilities panel in the MCP workspace.
    """
    if not state.is_mcp_authenticated():
        return []

    provider = _oauth_provider
    if provider is None:
        storage = InMemoryTokenStorage()
        provider = OAuthClientProvider(
            server_url=LUCID_MCP_URL,
            client_metadata=_make_client_metadata(),
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
