"""
app/routes/rest_api.py — Lucid REST API proxy routes.

A single route handles all REST endpoint executions:
  POST /api/rest/{endpoint_key}

The frontend POSTs { endpoint, params } here. The route delegates to
lucid_rest.execute_rest_call() and returns the structured result.

All REST endpoints share the same pattern — no individual route per endpoint.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services.lucid_rest import execute_rest_call

router = APIRouter(prefix="/api/rest", tags=["REST API"])


class ExecuteRequest(BaseModel):
    """Request body sent by the frontend for every REST endpoint execution."""
    endpoint: str
    params: dict = {}


@router.post("/{endpoint_key}", summary="Execute a Lucid REST API endpoint")
async def execute_rest_endpoint(
    endpoint_key: str,
    body: ExecuteRequest,
) -> JSONResponse:
    """
    Proxy a REST API call to Lucid's servers.

    The frontend sends the endpoint key and parameter values. This route:
      1. Validates the endpoint key exists
      2. Delegates to lucid_rest.execute_rest_call()
      3. Returns the full structured result (status, body, request log, cURL, Python)

    The endpoint_key in the path and body.endpoint should match — the path
    param is used for routing, the body param for the service call.
    """
    result = await execute_rest_call(endpoint_key, body.params)
    return JSONResponse(content=result, status_code=200)
