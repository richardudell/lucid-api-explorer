"""
app/errors.py — Typed API envelope + correlation ID helpers.

Provides:
  - stable error categories/actions for UI + support workflows
  - success/error response envelope builders
  - mapping helpers from upstream result dicts and exceptions
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

ErrorCategory = Literal[
    "config_error",
    "auth_error",
    "api_error",
    "rate_limit",
    "network_error",
    "model_output_error",
    "model_policy_error",
    "validation_error",
    "unknown_error",
]

RecommendedAction = Literal[
    "retry",
    "reauth",
    "fix_config",
    "contact_support",
    "escalate_engineering",
    "escalate_safety",
]

logger = logging.getLogger("lucid_api_explorer.errors")


class UpstreamMeta(BaseModel):
    service: str | None = None
    url: str | None = None
    status_code: int | None = None
    request_id: str | None = None


class ApiErrorEnvelope(BaseModel):
    ok: bool = False
    correlation_id: str
    category: ErrorCategory
    message: str
    details: dict[str, Any] = {}
    upstream: UpstreamMeta | None = None
    retryable: bool = False
    recommended_action: RecommendedAction = "escalate_engineering"
    http_status: int = 500


def get_correlation_id(request: Request) -> str:
    cid = getattr(request.state, "correlation_id", None)
    if cid:
        return cid
    cid = str(uuid.uuid4())
    request.state.correlation_id = cid
    return cid


def success_response(
    request: Request,
    data: Any,
    http_status: int = 200,
    meta: dict[str, Any] | None = None,
) -> JSONResponse:
    cid = get_correlation_id(request)
    payload = {
        "ok": True,
        "correlation_id": cid,
        "data": data,
        "meta": meta or {},
    }
    resp = JSONResponse(content=payload, status_code=http_status)
    resp.headers["X-Correlation-Id"] = cid
    return resp


def error_response(
    request: Request,
    *,
    category: ErrorCategory,
    message: str,
    http_status: int,
    details: dict[str, Any] | None = None,
    upstream: UpstreamMeta | None = None,
    retryable: bool = False,
    recommended_action: RecommendedAction | None = None,
    data: Any = None,
) -> JSONResponse:
    cid = get_correlation_id(request)
    action = recommended_action or _default_action_for_category(category)
    err = ApiErrorEnvelope(
        correlation_id=cid,
        category=category,
        message=message,
        details=details or {},
        upstream=upstream,
        retryable=retryable,
        recommended_action=action,
        http_status=http_status,
    )
    payload = {
        "ok": False,
        "correlation_id": cid,
        "error": err.model_dump(),
        "data": data,
    }
    _log_error(
        cid=cid,
        route=request.url.path,
        category=category,
        message=message,
        upstream=upstream,
        http_status=http_status,
    )
    resp = JSONResponse(content=payload, status_code=http_status)
    resp.headers["X-Correlation-Id"] = cid
    return resp


def error_response_from_exception(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, httpx.TimeoutException):
        return error_response(
            request,
            category="network_error",
            message="Upstream request timed out.",
            http_status=504,
            details={"exception_class": exc.__class__.__name__},
            retryable=True,
            recommended_action="retry",
        )
    if isinstance(exc, httpx.RequestError):
        return error_response(
            request,
            category="network_error",
            message="Network error while contacting upstream service.",
            http_status=503,
            details={"exception_class": exc.__class__.__name__, "detail": str(exc)},
            retryable=True,
            recommended_action="retry",
        )
    msg = str(exc)
    low = msg.lower()
    if (
        "missing required environment variable" in low
        or ("not configured" in low and ("api key" in low or "oauth" in low))
        or ("disabled" in low and "api key" in low)
    ):
        return error_response(
            request,
            category="config_error",
            message=msg or "Missing required runtime configuration.",
            http_status=500,
            details={"exception_class": exc.__class__.__name__},
            retryable=False,
            recommended_action="fix_config",
        )
    if "policy" in low or "refus" in low:
        return error_response(
            request,
            category="model_policy_error",
            message=msg or "Model refused the request.",
            http_status=422,
            details={"exception_class": exc.__class__.__name__},
            retryable=False,
            recommended_action="escalate_safety",
        )
    modelish = any(
        marker in low
        for marker in (
            "anthropic",
            "claude",
            "model output",
            "model returned",
            "json parse failure from model",
        )
    )
    if modelish and ("json" in low or "schema" in low or "malformed" in low):
        return error_response(
            request,
            category="model_output_error",
            message=msg or "Model output could not be parsed or validated.",
            http_status=422,
            details={"exception_class": exc.__class__.__name__},
            retryable=True,
            recommended_action="retry",
        )
    return error_response(
        request,
        category="unknown_error",
        message=msg or "Unexpected internal error.",
        http_status=500,
        details={"exception_class": exc.__class__.__name__},
        retryable=False,
        recommended_action="escalate_engineering",
    )


def error_response_from_result(
    request: Request,
    result: dict[str, Any],
    *,
    default_category: ErrorCategory = "api_error",
) -> JSONResponse:
    status = int(result.get("status_code", 500) or 500)
    body = result.get("body") if isinstance(result.get("body"), dict) else {}
    message = (
        body.get("error")
        or body.get("message")
        or f"Upstream request failed with status {status}."
    )
    upstream = _upstream_from_result(result)
    safe_body = _sanitize_value(body)
    details = {
        "upstream_body": safe_body,
        "auth_method": result.get("auth_method"),
    }
    safe_result = _safe_result_for_client(result)
    retry_after = None
    headers = result.get("response_headers")
    if isinstance(headers, dict):
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after is not None:
            details["retry_after"] = retry_after

    if status in (401, 403):
        return error_response(
            request,
            category="auth_error",
            message=message,
            http_status=status,
            details=details,
            upstream=upstream,
            retryable=False,
            recommended_action="reauth",
            data=safe_result,
        )
    if status == 429:
        return error_response(
            request,
            category="rate_limit",
            message=message,
            http_status=429,
            details=details,
            upstream=upstream,
            retryable=True,
            recommended_action="retry",
            data=safe_result,
        )
    if status == 400:
        cat: ErrorCategory = "validation_error"
        low_msg = str(message).lower()
        # Model-specific categories should only be used when we have explicit model
        # signals, not for generic malformed request bodies entered by users.
        modelish = any(
            marker in low_msg
            for marker in (
                "anthropic",
                "claude",
                "model output",
                "model returned",
                "refusal",
                "policy",
                "json parse failure from model",
            )
        )
        if modelish and ("policy" in low_msg or "refus" in low_msg):
            cat = "model_policy_error"
        elif modelish and ("json" in low_msg or "schema" in low_msg or "malformed" in low_msg):
            cat = "model_output_error"
        return error_response(
            request,
            category=cat,
            message=message,
            http_status=400,
            details=details,
            upstream=upstream,
            retryable=False,
            recommended_action=_default_action_for_category(cat),
            data=safe_result,
        )
    if status >= 500:
        return error_response(
            request,
            category=default_category,
            message=message,
            http_status=status,
            details=details,
            upstream=upstream,
            retryable=True,
            recommended_action="retry",
            data=safe_result,
        )
    return error_response(
        request,
        category=default_category,
        message=message,
        http_status=status,
        details=details,
        upstream=upstream,
        retryable=False,
        recommended_action=_default_action_for_category(default_category),
        data=safe_result,
    )


def _default_action_for_category(category: ErrorCategory) -> RecommendedAction:
    mapping: dict[ErrorCategory, RecommendedAction] = {
        "config_error": "fix_config",
        "auth_error": "reauth",
        "api_error": "contact_support",
        "rate_limit": "retry",
        "network_error": "retry",
        "model_output_error": "retry",
        "model_policy_error": "escalate_safety",
        "validation_error": "fix_config",
        "unknown_error": "escalate_engineering",
    }
    return mapping[category]


def _service_name_from_url(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url).hostname or ""
    if "mcp.lucid.app" in host:
        return "lucid_mcp"
    if "users.lucid.app" in host:
        return "lucid_scim"
    if "api.lucid.co" in host:
        return "lucid_rest"
    if "anthropic" in host:
        return "anthropic"
    return host or None


def _upstream_from_result(result: dict[str, Any]) -> UpstreamMeta | None:
    request = result.get("request") if isinstance(result.get("request"), dict) else {}
    headers = result.get("response_headers") if isinstance(result.get("response_headers"), dict) else {}
    url = request.get("url")
    upstream = UpstreamMeta(
        service=_service_name_from_url(url),
        url=url,
        status_code=int(result.get("status_code", 0) or 0) or None,
        request_id=(
            headers.get("x-request-id")
            or headers.get("X-Request-Id")
            or headers.get("x-lucid-flow-id")
        ),
    )
    return upstream


def _log_error(
    *,
    cid: str,
    route: str,
    category: ErrorCategory,
    message: str,
    upstream: UpstreamMeta | None,
    http_status: int,
) -> None:
    logger.warning(
        "api_error correlation_id=%s route=%s category=%s http_status=%s upstream_service=%s upstream_status=%s message=%s",
        cid,
        route,
        category,
        http_status,
        upstream.service if upstream else None,
        upstream.status_code if upstream else None,
        message,
    )


def _safe_result_for_client(result: dict[str, Any]) -> dict[str, Any]:
    request = result.get("request") if isinstance(result.get("request"), dict) else {}
    headers = request.get("headers") if isinstance(request.get("headers"), dict) else {}
    safe_headers: dict[str, Any] = {}
    for k, v in headers.items():
        lk = str(k).lower()
        if lk == "authorization":
            safe_headers[k] = _redact_bearer(v)
        else:
            safe_headers[k] = v
    safe_request = {
        "method": request.get("method"),
        "url": request.get("url"),
        "headers": safe_headers,
        "body": _sanitize_value(request.get("body")),
        "timestamp": request.get("timestamp"),
    }
    return {
        "status_code": result.get("status_code"),
        "body": _sanitize_value(result.get("body")),
        "request": safe_request,
        "response_headers": result.get("response_headers") if isinstance(result.get("response_headers"), dict) else {},
        "auth_method": result.get("auth_method"),
        "latency_ms": result.get("latency_ms"),
        "curl_command": result.get("curl_command", ""),
        "python_snippet": result.get("python_snippet", ""),
    }


def _sanitize_value(value: Any, key_hint: str | None = None) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for k, v in value.items():
            cleaned[k] = _sanitize_value(v, key_hint=str(k))
        return cleaned
    if isinstance(value, list):
        return [_sanitize_value(v, key_hint=key_hint) for v in value]
    if isinstance(value, str):
        low_key = (key_hint or "").lower()
        sensitive_key = (
            low_key in {"token", "access_token", "refresh_token", "id_token", "client_secret", "authorization", "password", "api_key", "apikey"}
            or low_key.endswith("_token")
            or low_key.endswith("_secret")
        )
        if sensitive_key:
            if low_key == "authorization":
                return _redact_bearer(value)
            return "••••••••"
        return value
    return value


def _redact_bearer(value: Any) -> str:
    raw = str(value or "")
    if not raw.lower().startswith("bearer "):
        return "••••••••"
    tok = raw[7:].strip()
    if not tok:
        return "Bearer ••••••••"
    return f"Bearer {tok[:8]}••••••••"
