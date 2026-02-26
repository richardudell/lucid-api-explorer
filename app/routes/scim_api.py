"""
app/routes/scim_api.py — Lucid SCIM API proxy routes.

Identical pattern to rest_api.py:
  POST /api/scim/{endpoint_key}

The frontend POSTs { endpoint, params } here. The route delegates to
lucid_scim.execute_scim_call() and returns the structured result.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.errors import error_response_from_exception, error_response_from_result, success_response
from app.services.lucid_scim import execute_scim_call

router = APIRouter(prefix="/api/scim", tags=["SCIM API"])


class ExecuteRequest(BaseModel):
    """Request body sent by the frontend for every SCIM endpoint execution."""
    endpoint: str
    params: dict = {}


@router.post("/{endpoint_key}", summary="Execute a Lucid SCIM API endpoint")
async def execute_scim_endpoint(
    request: Request,
    endpoint_key: str,
    body: ExecuteRequest,
) -> JSONResponse:
    """
    Proxy a SCIM API call to Lucid's servers.

    Auth difference vs REST: the SCIM bearer token is a static value loaded
    from .env at startup — no OAuth flow is needed. The token is injected
    server-side by lucid_scim.execute_scim_call(), never by the frontend.
    """
    try:
        result = await execute_scim_call(endpoint_key, body.params)
    except Exception as exc:  # defensive guard for unexpected adapter exceptions
        return error_response_from_exception(request, exc)

    status = int(result.get("status_code", 500) or 500) if isinstance(result, dict) else 500
    if status >= 400:
        return error_response_from_result(request, result)
    return success_response(request, data=result, http_status=200)
