"""中间件：X-Request-ID 透传与请求体大小限制（含 chunked 绕过场景）。"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.body_limit import BodySizeLimitMiddleware
from app.core.request_id import _is_trusted


def build_size_app(max_bytes: int) -> tuple[FastAPI, list[int]]:
    """返回一个记录已到达业务代码的请求体大小的 App。"""
    received: list[int] = []
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        size = len(await request.body())
        received.append(size)
        return {"size": size}

    return app, received


@pytest.mark.parametrize(
    "value",
    ["中文-request-id", "line\nbreak", "tab\there", "a" * 65, ""],
)
def test_untrusted_request_id_is_replaced(value):
    assert _is_trusted(value) is False


@pytest.mark.parametrize("value", ["abc-123", "gateway-trace-id", "a" * 64])
def test_trusted_request_id_is_preserved(value):
    assert _is_trusted(value) is True


def test_request_id_echoes_upstream_value(client):
    response = client.get("/health/live", headers={"X-Request-ID": "upstream-42"})
    assert response.headers["X-Request-ID"] == "upstream-42"


def test_request_id_is_generated_when_missing(client):
    response = client.get("/health/live")
    rid = response.headers["X-Request-ID"]
    assert len(rid) == 32
    assert int(rid, 16) >= 0  # 32 位 hex


def test_oversized_upstream_request_id_is_regenerated(client):
    response = client.get("/health/live", headers={"X-Request-ID": "x" * 200})
    assert response.headers["X-Request-ID"] != "x" * 200
    assert len(response.headers["X-Request-ID"]) == 32


def test_small_body_is_forwarded():
    app, received = build_size_app(max_bytes=256)
    response = TestClient(app).post("/echo", content=b"x" * 10)
    assert response.status_code == 200
    assert response.json() == {"size": 10}
    assert received == [10]


def test_declared_oversized_body_is_rejected_before_reading():
    app, received = build_size_app(max_bytes=256)
    response = TestClient(app).post("/echo", content=b"x" * 1024)
    assert response.status_code == 413
    # 关键：路由没被调用，body 没有被读入业务代码。
    assert received == []


def test_chunked_body_without_content_length_is_counted():
    """没有 Content-Length 的 chunked 请求必须同样受限，不能绕过。"""
    app, received = build_size_app(max_bytes=256)

    def chunks():
        for _ in range(64):
            yield b"x" * 16  # 合计 1024 字节

    response = TestClient(app).post("/echo", content=chunks())
    assert response.status_code == 413
    assert received == []


def test_invalid_content_length_is_bad_request():
    app, received = build_size_app(max_bytes=256)
    response = TestClient(app).post(
        "/echo", content=b"x" * 4, headers={"Content-Length": "not-a-number"}
    )
    assert response.status_code == 400
    assert received == []
