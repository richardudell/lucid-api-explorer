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

import json as pyjson

import anthropic

from app.config import ANTHROPIC_API_KEY, ANTHROPIC_CONFIGURED

# Instantiate lazily so the app can boot in demo mode without an Anthropic key.
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """
    Return a reusable Anthropic client or raise a clear config error.

    This keeps AI routes graceful when ANTHROPIC_API_KEY is intentionally absent
    (e.g., local demos focused on REST/SCIM/MCP mechanics).
    """
    global _client
    if _client is not None:
        return _client
    if not ANTHROPIC_CONFIGURED:
        raise RuntimeError(
            "AI features are disabled because ANTHROPIC_API_KEY is not configured."
        )
    _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client

MODEL = "claude-sonnet-4-6"

# ── Token-budget constants ─────────────────────────────────────────────────────
# Named here so they can be tuned in one place without hunting through call sites.
_MAX_TOKENS_NARRATIVE      = 800   # four-beat narrative after every API call
_MAX_TOKENS_FOLLOWUP       = 400   # follow-up Q&A answer
_MAX_TOKENS_NOTEPAD        = 300   # notepad interpretation / next-step recommendation
_MAX_TOKENS_STANDARD_IMPORT = 2200 # Standard Import JSON document generation
_MAX_TOKENS_MCP_PLAN       = 400   # MCP tool-call planning
_MAX_TOKENS_SAML_NARRATIVE = 900   # SAML flow narration (more fields to explain)

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

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=_MAX_TOKENS_NARRATIVE,
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

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=_MAX_TOKENS_FOLLOWUP,
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

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=_MAX_TOKENS_NOTEPAD,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text


async def generate_saml_narrative(execution_data: dict) -> str:
    """
    Generate Claude's narrative for a completed SAML SSO flow.

    The narrative explains what just happened in the SAML exchange:
    who asserted what, what Lucid will check, and what any fault means.

    Uses the same four-beat structure as generate_narrative() for consistency,
    adapted to SAML concepts:
      ✦ THE ASSERTION   — what the IdP claimed about the user
      THE SIGNING       — how the assertion was made tamper-proof
      THE HANDOFF       — how the assertion reached Lucid's ACS
      WHAT LUCID CHECKS — what Lucid validates and what can go wrong

    Args:
        execution_data: Dict from the SAML SSO handler, containing:
            acs_url, idp_entity_id, sp_entity_id, fault, fault_description,
            name_id, email, not_on_or_after, pretty_xml (truncated), step_data.

    Returns:
        A formatted string with the four-beat SAML narrative.
    """
    fault = execution_data.get("fault")
    fault_desc = execution_data.get("fault_description", "")
    fault_section = (
        f"\nFAULT INJECTED: {fault}\n{fault_desc}"
        if fault else "No fault injected — happy path."
    )

    prompt = f"""A SAML 2.0 SSO flow just completed through this app acting as an Identity Provider.
Generate a four-beat narrative explaining what happened.

FLOW DATA:
- IdP Entity ID: {execution_data.get('idp_entity_id', 'unknown')}
- SP Entity ID: {execution_data.get('sp_entity_id', '(not configured)')}
- ACS URL: {execution_data.get('acs_url', 'unknown')}
- NameID (user identifier): {execution_data.get('name_id', 'unknown')}
- User.email attribute: {execution_data.get('email', 'unknown')}
- Assertion valid until: {execution_data.get('not_on_or_after', 'unknown')}
- {fault_section}

Write exactly four sections in this order, using exactly these labels:
✦ THE ASSERTION
THE SIGNING
THE HANDOFF
WHAT LUCID CHECKS

Each section is 2-4 sentences. Explain SAML concepts clearly — treat the reader as
a smart support engineer who may not know SAML yet. Be specific about what you can
see in the data. If a fault was injected, WHAT LUCID CHECKS must explain exactly
which validation will fail and what error Lucid will likely return."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=_MAX_TOKENS_SAML_NARRATIVE,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


async def generate_standard_import_json(prompt: str, context: dict | None = None) -> dict:
    """
    Generate Lucid Standard Import JSON from a prompt and optional app context.
    Returns a parsed JSON object.
    """
    ctx = context or {}
    ctx_text = _truncate(pyjson.dumps(ctx, ensure_ascii=True), 2500)

    user_prompt = f"""Generate a Lucid Standard Import JSON document.

User intent:
{prompt}

Live app context:
{ctx_text}

Requirements:
- Return VALID JSON only (no markdown or prose).
- Top-level object must include "version": 1 and "pages": [ ... ].
- Every page must include: id, title, shapes.
- Build an educational diagram about Lucid API Explorer internals and/or recent usage.
- Use one page with readable labels and connections.
- Keep structure practical: 6-18 shapes.
- For shape geometry, use shape.boundingBox with numeric x,y,w,h.
- For each shape include: id, type, text, boundingBox.
- Prefer compact canvas layout (roughly within x: 0-1200, y: 0-900), avoid ultra-tall single-column stacks.
- Use "process" for normal blocks.
- Do not include shape.style.
- Optional: include page.lines using source/target (shape IDs) to express flow.
- Do not create line objects inside shapes.

Return only the raw JSON object."""

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=_MAX_TOKENS_STANDARD_IMPORT,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = message.content[0].text.strip()
    data = _parse_json_object_loose(raw)
    if data is None:
        repaired = _repair_json_with_model(raw)
        data = _parse_json_object_loose(repaired)

    if data is None:
        raise ValueError("Model returned malformed JSON that could not be repaired.")
    if not isinstance(data, dict):
        raise ValueError("Model response was not a JSON object.")
    if data.get("version") != 1 or not isinstance(data.get("pages"), list):
        raise ValueError("Generated JSON missing required Standard Import fields (version/pages).")
    return data


# ── plan_mcp_tool_calls ────────────────────────────────────────────────────────

async def plan_mcp_tool_calls(prompt: str, available_tools: list[dict]) -> list[dict]:
    """
    Ask Claude which MCP tools to invoke for a given natural-language prompt.

    Called by lucid_mcp._plan_tool_calls() to keep all Anthropic SDK usage
    inside this file (per CLAUDE.md architecture constraint).

    Args:
        prompt: The engineer's natural-language instruction.
        available_tools: List of tool dicts from MCP session.list_tools(),
                         each having at minimum 'name' and 'description'.

    Returns:
        List of {"tool": str, "arguments": dict} dicts for each tool to call.
        Returns [] if no tool fits or if the model returns unparseable output.
    """
    import logging as _logging
    _plan_log = _logging.getLogger(__name__)

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

    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=_MAX_TOKENS_MCP_PLAN,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": planning_prompt}],
    )

    text = message.content[0].text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return pyjson.loads(text)
    except pyjson.JSONDecodeError:
        _plan_log.warning(
            "plan_mcp_tool_calls: model returned unparseable JSON — no tools will be called. "
            "Raw response: %s", text[:200]
        )
        return []


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


def _parse_json_object_loose(raw: str) -> dict | None:
    """
    Parse JSON object from model output with light cleanup:
    - strips code fences
    - extracts text between first '{' and last '}'
    """
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.replace("json\n", "", 1).strip()

    # direct parse first
    try:
        data = pyjson.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start:end + 1]
    try:
        data = pyjson.loads(candidate)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _repair_json_with_model(raw: str) -> str:
    """
    Ask the model to repair malformed JSON with strict output constraints.
    """
    repair_prompt = f"""The following is intended to be JSON but is malformed.
Return ONLY valid JSON (no markdown, no commentary), preserving intent.

Malformed JSON:
{_truncate(raw, 12000)}"""
    client = _get_client()
    repaired = client.messages.create(
        model=MODEL,
        max_tokens=2200,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": repair_prompt}],
    )
    return repaired.content[0].text.strip()
