"""
app/routes/scim_api.py — Lucid SCIM API proxy routes.

Identical pattern to rest_api.py:
  POST /api/scim/{endpoint_key}

The frontend POSTs { endpoint, params } here. The route delegates to
lucid_scim.execute_scim_call() and returns the structured result.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services.lucid_scim import execute_scim_call

router = APIRouter(prefix="/api/scim", tags=["SCIM API"])


class ExecuteRequest(BaseModel):
    """Request body sent by the frontend for every SCIM endpoint execution."""
    endpoint: str
    params: dict = {}


@router.post("/{endpoint_key}", summary="Execute a Lucid SCIM API endpoint")
async def execute_scim_endpoint(
    endpoint_key: str,
    body: ExecuteRequest,
) -> JSONResponse:
    """
    Proxy a SCIM API call to Lucid's servers.

    Auth difference vs REST: the SCIM bearer token is a static value loaded
    from .env at startup — no OAuth flow is needed. The token is injected
    server-side by lucid_scim.execute_scim_call(), never by the frontend.
    """
    result = await execute_scim_call(endpoint_key, body.params)
    return JSONResponse(content=result, status_code=200)
