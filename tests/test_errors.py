"""通用 500：回到客户端的只有 error_id / request_id，不含异常内容。

注意中间件的注册顺序必须与 app/main.py 一致（RequestId 在外、Error 在内），
否则 request_id 会退化成 '-'：最后 add 的排在最外层。
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import UnexpectedErrorMiddleware
from app.core.request_id import RequestIdMiddleware


def build_app() -> FastAPI:
    app = FastAPI()
    # UnexpectedError 先注册 → 更内层 → 处在 RequestId 的 contextvar 范围内。
    app.add_middleware(UnexpectedErrorMiddleware)
    app.add_middleware(RequestIdMiddleware)

    @app.get("/boom")
    async def boom() -> None:
        raise ValueError("connection string postgresql://u:p@host/db leaked")

    return app


def test_unexpected_error_returns_ids_only():
    client = TestClient(build_app())
    response = client.get("/boom", headers={"X-Request-ID": "trace-9"})

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "Internal server error"
    assert len(body["error_id"]) == 32
    assert body["request_id"] == "trace-9"
    assert response.headers["X-Request-ID"] == "trace-9"
    # 异常原文绝不出现在客户端响应里。
    assert "postgresql://" not in response.text
    assert "leaked" not in response.text


def test_unexpected_error_has_unique_error_id():
    client = TestClient(build_app())
    first = client.get("/boom").json()["error_id"]
    second = client.get("/boom").json()["error_id"]
    assert first != second


def test_http_exception_keeps_its_own_status():
    """404/405 这类 HTTPException 不能被通用 500 吃掉。"""
    response = TestClient(build_app()).get("/missing")
    assert response.status_code == 404
    assert response.json()["detail"] == "Not Found"
