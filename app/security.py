"""
app/security.py — Request-level security helpers.

This app is intended for local workstation use. These helpers enforce that
default behavior while allowing explicit remote exposure when configured.
"""

from __future__ import annotations

import ipaddress
from fastapi import HTTPException, Request

from app.config import ALLOW_REMOTE


def _is_loopback_host(value: str | None) -> bool:
    if not value:
        return False
    host = value.strip().lower()
    if host in {"localhost", "127.0.0.1", "::1", "testclient"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_local_request(request: Request) -> bool:
    if ALLOW_REMOTE:
        return True

    client_host = request.client.host if request.client else None
    if not _is_loopback_host(client_host):
        return False

    # If traffic passed through a proxy/tunnel, require forwarded source to be local too.
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        source = x_forwarded_for.split(",", 1)[0].strip()
        if source and not _is_loopback_host(source):
            return False

    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip and not _is_loopback_host(x_real_ip.strip()):
        return False

    return True


def require_local_request(request: Request, purpose: str = "this route") -> None:
    if is_local_request(request):
        return
    raise HTTPException(
        status_code=403,
        detail=(
            f"Remote access is blocked for {purpose}. "
            "Set ALLOW_REMOTE=true only when you intentionally expose the app."
        ),
    )


async def require_local_request_dep(request: Request) -> None:
    """FastAPI dependency for local-only routes."""
    require_local_request(request, "this route")
