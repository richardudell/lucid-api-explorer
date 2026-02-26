"""
app/routes/ai.py — AI narrative and notepad routes.

Three endpoints that the frontend calls after every execution:
  POST /ai/narrative  — generate four-beat narrative for the last API call
  POST /ai/followup   — answer a follow-up question in the narrative panel
  POST /ai/notepad    — interpret notepad content and suggest next steps

All three delegate exclusively to app/services/ai_client.py.
No other file in this project calls the Anthropic SDK.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.errors import error_response, error_response_from_exception, success_response
from app.services.ai_client import (
    generate_narrative,
    answer_followup,
    interpret_notepad,
    generate_standard_import_json,
)

router = APIRouter(prefix="/ai", tags=["AI"])


# ── Request models ─────────────────────────────────────────────────────────────

class NarrativeRequest(BaseModel):
    """Payload from the frontend after an API call completes."""
    execution_data: dict


class FollowupRequest(BaseModel):
    """Payload from the Ask More input in the narrative panel."""
    question: str
    context: dict | None = None


class NotepadRequest(BaseModel):
    """Payload from the Ask Claude button in the sidebar notepad."""
    content: str


class StandardImportRequest(BaseModel):
    """Prompt + context used to generate Standard Import JSON."""
    prompt: str
    context: dict | None = None


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/narrative", summary="Generate four-beat Claude narrative for a completed API call")
async def narrative(request: Request, body: NarrativeRequest) -> JSONResponse:
    """
    Called automatically by the frontend after every successful or failed execution.
    Returns Claude's four-beat narrative (AUTHENTICATION / REQUEST / RESPONSE / MEANING).
    """
    try:
        text = await generate_narrative(body.execution_data)
        return success_response(request, data={"narrative": text}, http_status=200)
    except Exception as exc:
        return error_response_from_exception(request, exc)


@router.post("/followup", summary="Answer a follow-up question in the narrative panel")
async def followup(request: Request, body: FollowupRequest) -> JSONResponse:
    """
    Called when the engineer types a question in the Ask More input.
    Context is the execution_data from the last call, included for reference.
    """
    try:
        answer = await answer_followup(body.question, body.context or {})
        return success_response(request, data={"answer": answer}, http_status=200)
    except Exception as exc:
        return error_response_from_exception(request, exc)


@router.post("/notepad", summary="Interpret notepad content and suggest next steps")
async def notepad(request: Request, body: NotepadRequest) -> JSONResponse:
    """
    Called when the engineer clicks Ask Claude in the sidebar notepad.
    Claude reads the notepad content and recommends a surface, endpoint, and action.
    """
    try:
        response = await interpret_notepad(body.content)
        return success_response(request, data={"response": response}, http_status=200)
    except Exception as exc:
        return error_response_from_exception(request, exc)


@router.post("/standard-import", summary="Generate Standard Import JSON for educational Lucid diagrams")
async def standard_import(request: Request, body: StandardImportRequest) -> JSONResponse:
    """
    Uses Claude to generate a Lucid Standard Import JSON document from an
    instructional prompt and optional live app context.
    """
    try:
        document = await generate_standard_import_json(body.prompt, body.context or {})
        return success_response(request, data={"document": document}, http_status=200)
    except Exception as exc:
        message = str(exc)
        low = message.lower()
        if "policy" in low or "refus" in low:
            return error_response(
                request,
                category="model_policy_error",
                message=message or "Model policy refusal while generating SI JSON.",
                http_status=422,
                details={"surface": "standard_import_generation"},
                retryable=False,
                recommended_action="escalate_safety",
            )
        if "json" in low or "schema" in low or "malformed" in low:
            return error_response(
                request,
                category="model_output_error",
                message=message or "Model returned malformed/invalid JSON.",
                http_status=422,
                details={"surface": "standard_import_generation"},
                retryable=True,
                recommended_action="retry",
            )
        return error_response_from_exception(request, exc)
