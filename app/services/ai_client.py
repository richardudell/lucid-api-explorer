"""
app/services/ai_client.py — Abstracted AI layer for lucid-api-explorer.

ALL Anthropic SDK calls in this project are made here and nowhere else.
This abstraction means a future migration from Claude to Gemini (or any other
model) requires changing only this file — all function signatures stay the same
and no other file touches the SDK.

Three public functions:
  generate_narrative(execution_data)  — four-beat narrative after every API call
  answer_followup(question, context)  — follow-up question in the narrative panel
  interpret_notepad(content)          — reads the notepad and suggests next steps

Model: claude-sonnet-4-6 (latest capable model as of Feb 2026).
All calls use the messages API with a system prompt that establishes Claude's
role as a direct, technically accurate API educator.
"""

import anthropic

from app.config import ANTHROPIC_API_KEY

# Instantiate the client once at module load — it is thread-safe and reusable
_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

MODEL = "claude-sonnet-4-6"

# ── Shared system prompt ───────────────────────────────────────────────────────
# Establishes Claude's voice for all interactions in this app.
# Direct, compact, technically accurate. Treats the engineer as smart.
# Never preachy, never verbose by default.

_SYSTEM_PROMPT = """You are the AI layer of Lucid API Explorer, an internal API workbench
for Lucid Software's enterprise support team. Your job is to narrate what just happened
during an API call — authentication, request, response, and meaning — in plain language
that any support engineer can follow, from complete beginners to senior engineers.

Tone: direct, compact, technically accurate. Treat the engineer as smart. Explanations
are 2-4 sentences per beat unless asked for more. Never be preachy or verbose.
Never hallucinate endpoint details — only describe what you can see in the data provided.

You know Lucid's three API surfaces well:
- REST API: Standard HTTP endpoints at users.lucid.co/v1. OAuth 2.0 Authorization Code Flow.
- SCIM API: User provisioning at users.lucid.app/scim/v2. Static Bearer Token.
- MCP Server: Natural language interface at mcp.lucid.app. OAuth 2.0 with Dynamic Client Registration."""


# ── generate_narrative ─────────────────────────────────────────────────────────

async def generate_narrative(execution_data: dict) -> str:
    """
    Generate Claude's four-beat narrative for a completed API call.

    The four beats — always in this order, always present:
      ✦ AUTHENTICATION  — what auth method was used, what it proved
      THE REQUEST       — what was sent, to where, what it asked for
      THE RESPONSE      — what came back, what it means
      WHAT THIS MEANS   — the bigger picture and what to do next

    Args:
        execution_data: The full result dict from execute_rest_call() or
                        execute_scim_call(), containing status_code, body,
                        request, auth_method, latency_ms.

    Returns:
        A formatted string with the four-beat narrative.
    """
    request = execution_data.get("request", {})
    status_code = execution_data.get("status_code", 0)
    body = execution_data.get("body", {})
    auth_method = execution_data.get("auth_method", "unknown")
    latency_ms = execution_data.get("latency_ms", 0)

    # Redact the actual token value before sending to the AI
    safe_headers = _redact_headers(request.get("headers", {}))

    prompt = f"""An API call just completed. Generate the four-beat narrative.

EXECUTION DATA:
- Method: {request.get('method', 'unknown')}
- URL: {request.get('url', 'unknown')}
- Auth method: {auth_method}
- Request headers: {safe_headers}
- Request body: {request.get('body')}
- Status code: {status_code}
- Response body: {_truncate(body, 800)}
- Latency: {latency_ms}ms

Write exactly four sections in this order, using exactly these labels:
✦ AUTHENTICATION
THE REQUEST
THE RESPONSE
WHAT THIS MEANS

Each section is 2-4 sentences. Be specific about what you see in the data — method, URL,
status code, key fields in the response body. If this is an error response (4xx/5xx),
make WHAT THIS MEANS actionable: explain what likely caused it and what to do next."""

    message = _client.messages.create(
        model=MODEL,
        max_tokens=800,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text


# ── answer_followup ────────────────────────────────────────────────────────────

async def answer_followup(question: str, context: dict) -> str:
    """
    Answer a follow-up question from the engineer in the narrative panel.

    Args:
        question: The engineer's question (e.g. "What does the active field mean?").
        context: The execution_data dict from the last API call, for reference.

    Returns:
        Claude's answer as a plain string (2-4 sentences unless depth is requested).
    """
    request = context.get("request", {}) if context else {}
    status_code = context.get("status_code", "unknown") if context else "unknown"
    body = context.get("body", {}) if context else {}

    context_summary = f"""Last executed call context:
- Method: {request.get('method', 'none')}
- URL: {request.get('url', 'none')}
- Status: {status_code}
- Response (truncated): {_truncate(body, 400)}"""

    message = _client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"{context_summary}\n\nFollow-up question: {question}",
            }
        ],
    )

    return message.content[0].text


# ── interpret_notepad ──────────────────────────────────────────────────────────

async def interpret_notepad(content: str) -> str:
    """
    Read the engineer's notepad and suggest what API surface or endpoint to use next.

    The notepad may contain: user IDs, error codes, email addresses, free-form notes,
    or questions. Claude infers the context and recommends the most relevant next step.

    Args:
        content: The raw text from the notepad textarea.

    Returns:
        Claude's recommendation as a plain string (2-5 sentences).
    """
    prompt = f"""An engineer has pasted the following into their notepad in the Lucid API Explorer:

---
{content}
---

Identify what this is (user ID, error code, email address, question, etc.) and tell them:
1. Which API surface to use (REST, SCIM, or MCP)
2. Which specific endpoint would be most useful
3. What they should expect to learn from it

Be direct. If you recognise a specific Lucid error code or pattern, name it.
If it looks like a user ID, tell them which get-user endpoint to run.
Keep your response to 3-5 sentences."""

    message = _client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text


# ── Helpers ────────────────────────────────────────────────────────────────────

def _redact_headers(headers: dict) -> dict:
    """Return headers with Bearer tokens partially redacted."""
    safe = {}
    for k, v in headers.items():
        if k.lower() == "authorization" and isinstance(v, str) and v.startswith("Bearer "):
            token = v[7:]
            safe[k] = f"Bearer {token[:6]}••••••••" if len(token) > 6 else "Bearer ••••••••"
        else:
            safe[k] = v
    return safe


def _truncate(obj: object, max_chars: int) -> str:
    """Stringify and truncate an object to avoid overwhelming the prompt."""
    text = str(obj)
    if len(text) > max_chars:
        return text[:max_chars] + "…"
    return text
