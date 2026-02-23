"""
app/routes/ai.py — AI narrative and notepad routes.

Three endpoints that the frontend calls after every execution:
  POST /ai/narrative  — generate four-beat narrative for the last API call
  POST /ai/followup   — answer a follow-up question in the narrative panel
  POST /ai/notepad    — interpret notepad content and suggest next steps

All three delegate exclusively to app/services/ai_client.py.
No other file in this project calls the Anthropic SDK.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services.ai_client import generate_narrative, answer_followup, interpret_notepad

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


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/narrative", summary="Generate four-beat Claude narrative for a completed API call")
async def narrative(body: NarrativeRequest) -> JSONResponse:
    """
    Called automatically by the frontend after every successful or failed execution.
    Returns Claude's four-beat narrative (AUTHENTICATION / REQUEST / RESPONSE / MEANING).
    """
    try:
        text = await generate_narrative(body.execution_data)
        return JSONResponse(content={"narrative": text})
    except Exception as exc:
        return JSONResponse(
            content={"narrative": f"Narrative unavailable: {exc}"},
            status_code=200,  # Always 200 — the UI handles the message gracefully
        )


@router.post("/followup", summary="Answer a follow-up question in the narrative panel")
async def followup(body: FollowupRequest) -> JSONResponse:
    """
    Called when the engineer types a question in the Ask More input.
    Context is the execution_data from the last call, included for reference.
    """
    try:
        answer = await answer_followup(body.question, body.context or {})
        return JSONResponse(content={"answer": answer})
    except Exception as exc:
        return JSONResponse(
            content={"answer": f"Could not generate answer: {exc}"},
            status_code=200,
        )


@router.post("/notepad", summary="Interpret notepad content and suggest next steps")
async def notepad(body: NotepadRequest) -> JSONResponse:
    """
    Called when the engineer clicks Ask Claude in the sidebar notepad.
    Claude reads the notepad content and recommends a surface, endpoint, and action.
    """
    try:
        response = await interpret_notepad(body.content)
        return JSONResponse(content={"response": response})
    except Exception as exc:
        return JSONResponse(
            content={"response": f"Could not interpret notepad: {exc}"},
            status_code=200,
        )
