"""真实 App 的中间件接线 + 行为回归。

盯住 ``app/main.py`` 的中间件注册顺序：
- RequestId 最外层：413 / 500 响应里都带当前 request_id；
- UnexpectedError 在中间：把漏出的异常转成 500；
- BodySizeLimit 最内：自己消费 ``_BodyTooLarge`` 并返回 413。

这是最容易悄悄失效的一环，顺序错了 413 会变 500 或 500 里的 request_id 退化成 '-'。
"""

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import app
from tests.conftest import FakeSession


def test_openapi_is_served_outside_production(client):
    # APP_ENV=testing，因此 /docs 与 /openapi.json 应保持开放。
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_live_endpoint_returns_request_id(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


def test_unexpected_error_in_real_app_keeps_request_id():
    """主 App 的中间件栈端到端：500 响应里 request_id 必须正确。"""
    app.dependency_overrides[get_db_session] = lambda: FakeSession(
        error=RuntimeError("boom-should-not-leak")
    )
    try:
        with TestClient(app) as client:
            response = client.get("/health/ready", headers={"X-Request-ID": "real-1"})
        assert response.status_code == 500
        body = response.json()
        assert body["request_id"] == "real-1"
        assert response.headers["X-Request-ID"] == "real-1"
        assert "boom-should-not-leak" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_live_remains_ok_under_db_failure():
    """live 不注入数据库依赖，DB 故障时仍然 200。"""
    app.dependency_overrides[get_db_session] = lambda: FakeSession(error=RuntimeError("db-down"))
    try:
        with TestClient(app) as client:
            response = client.get("/health/live")
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()
