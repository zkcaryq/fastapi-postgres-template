"""中间件：请求 ID 透传、请求体大小限制，以及真实完整 Middleware Stack 的集成测试。"""

import pytest
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient

from app.core.body_limit import BodySizeLimitMiddleware
from app.core.errors import UnexpectedErrorMiddleware
from app.core.request_id import RequestIdMiddleware, _is_valid_request_id


def _build_app(
    *,
    max_bytes: int = 256,
    with_unexpected_error: bool = True,
    with_request_id: bool = True,
) -> tuple[FastAPI, list[int]]:
    """构造一个最小 App，附带记录“路由是否被调用”与“路由收到的请求体大小”。

    顺序：最后 add 的最外层。所以参数顺序对应中间件从内到外：
    BodySizeLimit → UnexpectedError → RequestId。
    """
    received: list[int] = []
    app = FastAPI()

    @app.post("/echo")
    async def _echo(request: Request) -> dict[str, int]:
        body = await request.body()
        received.append(len(body))
        return {"size": len(body)}

    @app.get("/boom")
    async def _boom() -> None:
        raise RuntimeError("boom-should-not-leak")

    @app.get("/missing")
    async def _missing() -> None:
        raise HTTPException(status_code=404, detail="nope")

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)
    if with_unexpected_error:
        app.add_middleware(UnexpectedErrorMiddleware)
    if with_request_id:
        app.add_middleware(RequestIdMiddleware)
    return app, received


# ---------------------------------------------------------------------------
# Request ID：合法/非法格式与透传行为
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["中文-request-id", "line\nbreak", "tab\there", "a" * 65, ""],
)
def test_invalid_request_id_is_replaced(value):
    assert _is_valid_request_id(value) is False


@pytest.mark.parametrize("value", ["abc-123", "gateway-trace-id", "a" * 64])
def test_valid_request_id_is_preserved(value):
    assert _is_valid_request_id(value) is True


def test_request_id_echoes_upstream_value():
    app, _ = _build_app()
    with TestClient(app) as client:
        response = client.get("/echo", headers={"X-Request-ID": "upstream-42"})
    # 405 因为 /echo 是 POST；我们只要响应头。
    assert response.headers["X-Request-ID"] == "upstream-42"


def test_request_id_is_generated_when_missing():
    app, _ = _build_app()
    with TestClient(app) as client:
        response = client.post("/echo", content=b"x")
    rid = response.headers["X-Request-ID"]
    assert len(rid) == 32
    int(rid, 16)  # 32 位 hex


def test_oversized_upstream_request_id_is_regenerated():
    app, _ = _build_app()
    with TestClient(app) as client:
        response = client.post("/echo", content=b"x", headers={"X-Request-ID": "x" * 200})
    assert response.headers["X-Request-ID"] != "x" * 200
    assert len(response.headers["X-Request-ID"]) == 32


def test_request_id_header_is_forced_by_middleware():
    """即使内层代码塞了别的 X-Request-ID，外层 RequestIdMiddleware 也会覆盖。"""
    app = FastAPI()

    @app.get("/fake-id")
    async def _fake_id() -> Response:
        # 内层 Response 显式写一个 X-Request-ID，外层 middleware 应强制覆盖。
        return Response(
            content=b"ok",
            headers={"X-Request-ID": "fake-id-set-by-inner"},
        )

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=256)
    app.add_middleware(UnexpectedErrorMiddleware)
    app.add_middleware(RequestIdMiddleware)

    with TestClient(app) as client:
        response = client.get("/fake-id", headers={"X-Request-ID": "real-upstream-id"})
    assert response.status_code == 200
    # 外层 RequestIdMiddleware 用 contextvar 里的值（"real-upstream-id"）覆盖。
    # 内层设的 "fake-id-set-by-inner" 不应该出现。
    assert response.headers["X-Request-ID"] == "real-upstream-id"
    assert "fake-id-set-by-inner" not in response.headers.get("X-Request-ID", "")
    # 且响应里有且只有一个 X-Request-ID 头（替换而非追加）。
    assert response.headers.get_list("X-Request-ID") == ["real-upstream-id"]


# ---------------------------------------------------------------------------
# BodySizeLimit：单独跑，确认未引入回归
# ---------------------------------------------------------------------------


def test_small_body_is_forwarded():
    app, received = _build_app(max_bytes=256)
    with TestClient(app) as client:
        response = client.post("/echo", content=b"x" * 10)
    assert response.status_code == 200
    assert response.json() == {"size": 10}
    assert received == [10]


def test_declared_oversized_body_is_rejected_before_reading():
    app, received = _build_app(max_bytes=256)
    with TestClient(app) as client:
        response = client.post("/echo", content=b"x" * 1024)
    assert response.status_code == 413
    # 关键：路由没被调用，body 没有被读入业务代码。
    assert received == []


def test_chunked_body_without_content_length_is_counted():
    app, received = _build_app(max_bytes=256)

    def chunks():
        for _ in range(64):
            yield b"x" * 16  # 合计 1024 字节

    with TestClient(app) as client:
        response = client.post("/echo", content=chunks())
    assert response.status_code == 413
    assert received == []


def test_invalid_content_length_is_bad_request():
    app, received = _build_app(max_bytes=256)
    with TestClient(app) as client:
        response = client.post(
            "/echo", content=b"x" * 4, headers={"Content-Length": "not-a-number"}
        )
    assert response.status_code == 400
    assert received == []


# ---------------------------------------------------------------------------
# 真实完整 Middleware Stack：RequestId + UnexpectedError + BodySizeLimit
# 这是这次修复的核心——保证三者共存时行为正确。
# ---------------------------------------------------------------------------


def test_stack_normal_request_returns_200_with_request_id():
    app, received = _build_app()
    with TestClient(app) as client:
        response = client.post("/echo", content=b"hi", headers={"X-Request-ID": "stack-1"})
    assert response.status_code == 200
    assert response.json() == {"size": 2}
    assert received == [2]
    assert response.headers["X-Request-ID"] == "stack-1"


def test_stack_declared_oversized_body_returns_413_with_request_id():
    app, received = _build_app(max_bytes=64)
    with TestClient(app) as client:
        response = client.post("/echo", content=b"x" * 1024, headers={"X-Request-ID": "stack-413a"})
    assert response.status_code == 413
    assert received == []
    # 关键：413 响应必须仍然带 X-Request-ID。
    assert response.headers["X-Request-ID"] == "stack-413a"
    assert response.json() == {"detail": "Request body too large"}


def test_stack_chunked_oversized_body_returns_413_with_request_id():
    app, received = _build_app(max_bytes=64)

    def chunks():
        for _ in range(8):
            yield b"x" * 32  # 合计 256 字节

    with TestClient(app) as client:
        response = client.post("/echo", content=chunks(), headers={"X-Request-ID": "stack-413b"})
    assert response.status_code == 413
    assert received == []
    assert response.headers["X-Request-ID"] == "stack-413b"


def test_stack_invalid_content_length_returns_400_with_request_id():
    app, received = _build_app(max_bytes=64)
    with TestClient(app) as client:
        response = client.post(
            "/echo",
            content=b"x" * 4,
            headers={"Content-Length": "not-a-number", "X-Request-ID": "stack-400"},
        )
    assert response.status_code == 400
    assert received == []
    assert response.headers["X-Request-ID"] == "stack-400"


def test_stack_lying_content_length_is_caught_by_byte_counting():
    """伪造小 Content-Length 但实际 body 超限：仍必须 413。

    声明值 (10) ≤ 上限 (64) 会骗过第一道闸；转发阶段的真实字节计数
    (1024) 必须抓住它。这正是 chunked 计数逻辑的第二用途。
    """
    app, received = _build_app(max_bytes=64)
    with TestClient(app) as client:
        response = client.post(
            "/echo",
            content=b"x" * 1024,
            headers={"Content-Length": "10", "X-Request-ID": "stack-lie"},
        )
    assert response.status_code == 413, response.text
    assert received == []
    assert response.headers["X-Request-ID"] == "stack-lie"


def test_stack_router_exception_returns_500_with_request_id():
    app, _ = _build_app()
    with TestClient(app) as client:
        response = client.get("/boom", headers={"X-Request-ID": "stack-500"})
    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "Internal server error"
    assert body["request_id"] == "stack-500"
    # 异常文本绝对不能进客户端响应。
    assert "boom-should-not-leak" not in response.text
    assert response.headers["X-Request-ID"] == "stack-500"


def test_stack_http_exception_keeps_its_status():
    app, _ = _build_app()
    with TestClient(app) as client:
        response = client.get("/missing", headers={"X-Request-ID": "stack-404"})
    assert response.status_code == 404
    assert response.json()["detail"] == "nope"
    # 404 仍然带 X-Request-ID。
    assert response.headers["X-Request-ID"] == "stack-404"


def test_stack_405_is_not_converted_to_500():
    app, _ = _build_app()
    with TestClient(app) as client:
        # /echo 是 POST；用 GET 触发 405
        response = client.get("/echo", headers={"X-Request-ID": "stack-405"})
    assert response.status_code == 405
    assert response.headers["X-Request-ID"] == "stack-405"


def test_stack_422_validation_error_is_not_converted_to_500():
    """FastAPI / Pydantic 的 422 必须保持状态码，不被 UnexpectedError 吞成 500。"""
    from pydantic import BaseModel

    app = FastAPI()

    class Payload(BaseModel):
        name: str  # required

    @app.post("/strict", response_model=None)
    async def _strict(payload: Payload):  # type: ignore[valid-type]
        return {"name": payload.name}

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=1024)
    app.add_middleware(UnexpectedErrorMiddleware)
    app.add_middleware(RequestIdMiddleware)

    with TestClient(app) as client:
        response = client.post(
            "/strict",
            json={},  # 缺 name
            headers={"X-Request-ID": "stack-422"},
        )
    assert response.status_code == 422, response.text
    assert response.headers["X-Request-ID"] == "stack-422"


def test_stack_streaming_response_keeps_single_request_id_header():
    """StreamingResponse 同样带且只带一个 X-Request-ID；body 完整到达。

    RequestId 中间件工作在 ``http.response.start`` 消息层，
    与 body 是一次性还是分块流式无关。
    """
    from fastapi.responses import StreamingResponse

    app = FastAPI()

    @app.get("/stream")
    async def _stream() -> StreamingResponse:
        async def gen():
            for chunk in (b"part-1;", b"part-2;", b"part-3"):
                yield chunk

        return StreamingResponse(gen(), media_type="text/plain")

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=1024)
    app.add_middleware(UnexpectedErrorMiddleware)
    app.add_middleware(RequestIdMiddleware)

    with TestClient(app) as client:
        response = client.get("/stream", headers={"X-Request-ID": "stream-rid"})

    assert response.status_code == 200
    assert response.text == "part-1;part-2;part-3"
    # httpx 把同名头合并为逗号分隔值；只有一个头时值就是它本身。
    assert response.headers["X-Request-ID"] == "stream-rid"
    raw_values = response.headers.get_list("X-Request-ID")
    assert raw_values == ["stream-rid"], raw_values
