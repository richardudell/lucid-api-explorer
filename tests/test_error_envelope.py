"""
tests/test_error_envelope.py — Envelope + correlation ID behavior.
"""

import uuid


def _fake_success_result():
    return {
        "status_code": 200,
        "body": {"ok": True},
        "request": {"method": "GET", "url": "https://api.lucid.co/users/1", "headers": {}, "body": None},
        "response_headers": {},
        "auth_method": "Bearer token (OAuth 2.0 Authorization Code — User Token)",
        "latency_ms": 12,
        "curl_command": "curl ...",
        "python_snippet": "import requests",
    }


def _fake_error_result(status_code: int):
    return {
        "status_code": status_code,
        "body": {"error": f"upstream error {status_code}"},
        "request": {"method": "POST", "url": "https://api.lucid.co/documents", "headers": {}, "body": None},
        "response_headers": {"Retry-After": "30"} if status_code == 429 else {},
        "auth_method": "Bearer token (OAuth 2.0 Authorization Code — User Token)",
        "latency_ms": 0,
        "curl_command": "",
        "python_snippet": "",
    }


def test_correlation_id_returned_on_success(client, monkeypatch):
    import app.routes.rest_api as rest_route

    async def _mock_execute(*_args, **_kwargs):
        return _fake_success_result()

    monkeypatch.setattr(rest_route, "execute_rest_call", _mock_execute)
    res = client.post("/api/rest/getUser", json={"endpoint": "getUser", "params": {}})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert isinstance(body["correlation_id"], str) and body["correlation_id"]
    assert res.headers.get("X-Correlation-Id") == body["correlation_id"]


def test_correlation_id_returned_on_error_with_inbound_header(client, monkeypatch):
    import app.routes.rest_api as rest_route

    async def _mock_execute(*_args, **_kwargs):
        return _fake_error_result(401)

    monkeypatch.setattr(rest_route, "execute_rest_call", _mock_execute)
    cid = str(uuid.uuid4())
    res = client.post(
        "/api/rest/getUser",
        json={"endpoint": "getUser", "params": {}},
        headers={"X-Correlation-Id": cid},
    )
    assert res.status_code == 401
    body = res.json()
    assert body["ok"] is False
    assert body["correlation_id"] == cid
    assert res.headers.get("X-Correlation-Id") == cid


def test_upstream_429_maps_to_rate_limit_retryable_true(client, monkeypatch):
    import app.routes.rest_api as rest_route

    async def _mock_execute(*_args, **_kwargs):
        return _fake_error_result(429)

    monkeypatch.setattr(rest_route, "execute_rest_call", _mock_execute)
    res = client.post("/api/rest/searchDocuments", json={"endpoint": "searchDocuments", "params": {}})
    assert res.status_code == 429
    body = res.json()
    assert body["ok"] is False
    assert body["error"]["category"] == "rate_limit"
    assert body["error"]["retryable"] is True
    assert body["error"]["recommended_action"] == "retry"


def test_upstream_401_maps_to_auth_error(client, monkeypatch):
    import app.routes.rest_api as rest_route

    async def _mock_execute(*_args, **_kwargs):
        return _fake_error_result(401)

    monkeypatch.setattr(rest_route, "execute_rest_call", _mock_execute)
    res = client.post("/api/rest/getUser", json={"endpoint": "getUser", "params": {}})
    assert res.status_code == 401
    body = res.json()
    assert body["ok"] is False
    assert body["error"]["category"] == "auth_error"
    assert body["error"]["recommended_action"] == "reauth"
