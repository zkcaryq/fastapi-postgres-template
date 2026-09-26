"""真实 App 的中间件接线：确认 main.py 里的注册顺序没被改坏。

这是最容易悄悄失效的一环：顺序错了，500 响应里的 request_id 会变成 '-'，
而且没人会在本地手动构造异常去验证。
"""

from app.db.session import get_db_session
from app.main import app
from tests.conftest import FakeSession


def test_unexpected_error_keeps_request_id(client):
    try:
        app.dependency_overrides[get_db_session] = lambda: FakeSession(
            error=RuntimeError("boom-should-not-leak")
        )
        response = client.get("/health/ready", headers={"X-Request-ID": "abc-1"})

        assert response.status_code == 500
        body = response.json()
        assert body["request_id"] == "abc-1"
        assert response.headers["X-Request-ID"] == "abc-1"
        assert "boom-should-not-leak" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_openapi_is_served_outside_production(client):
    # APP_ENV=testing，因此 /docs 与 /openapi.json 应保持开放。
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
