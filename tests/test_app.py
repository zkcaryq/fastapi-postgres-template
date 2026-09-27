"""真实 App 的中间件接线 + 行为回归。

盯住 ``app/main.py`` 的中间件注册顺序：
- RequestId 最外层：413 / 500 响应里都带当前 request_id；
- UnexpectedError 在中间：把漏出的异常转成 500；
- BodySizeLimit 最内：自己消费 ``_BodyTooLarge`` 并返回 413。

这是最容易悄悄失效的一环，顺序错了 413 会变 500 或 500 里的 request_id 退化成 '-'。
"""
# ↑ 模块 docstring：这些测试直接测"真实 app 实例"（不是临时构造的），
#   目的是盯住 main.py 里中间件的接线顺序是否正确。

# 导入测试客户端。
from fastapi.testclient import TestClient

# 导入 app 的数据库依赖、主应用实例，和假 Session。
from app.db.session import get_db_session
from app.main import app
from tests.conftest import FakeSession


def test_openapi_is_served_outside_production(client):
    # ↑ 测试：非生产环境下 /docs 和 /openapi.json 是开放的。

    # APP_ENV=testing，因此 /docs 与 /openapi.json 应保持开放。
    # ↑ 说明。
    assert client.get("/openapi.json").status_code == 200
    # ↑ 断言 openapi.json 返回 200。
    assert client.get("/docs").status_code == 200
    # ↑ 断言 /docs 返回 200。


def test_live_endpoint_returns_request_id(client):
    # ↑ 测试：真实 app 的 live 接口带 request_id。

    response = client.get("/health/live")
    # ↑ 请求。
    assert response.status_code == 200
    # ↑ 断言 200。
    assert response.headers["X-Request-ID"]
    # ↑ 断言有 X-Request-ID 头。


def test_unexpected_error_in_real_app_keeps_request_id():
    # ↑ 测试：真实 app 里发生异常，500 响应仍带正确的 request_id。

    """主 App 的中间件栈端到端：500 响应里 request_id 必须正确。"""
    # ↑ docstring。
    app.dependency_overrides[get_db_session] = lambda: FakeSession(
        error=RuntimeError("boom-should-not-leak")
    )
    # ↑ 覆盖数据库依赖，让 /health/ready 注入一个会抛异常的假 Session。
    try:
        # ↑ 用 try/finally 保证最后清理覆盖。
        with TestClient(app) as client:
            # ↑ 创建客户端。
            response = client.get("/health/ready", headers={"X-Request-ID": "real-1"})
            # ↑ 请求 ready（会触发数据库异常），带自定义 request_id。
        assert response.status_code == 500
        # ↑ 断言 500。
        body = response.json()
        # ↑ 解析响应体。
        assert body["request_id"] == "real-1"
        # ↑ 断言 request_id 正确透传。
        assert response.headers["X-Request-ID"] == "real-1"
        # ↑ 断言响应头一致。
        assert "boom-should-not-leak" not in response.text
        # ↑ 断言异常文本没泄露。
    finally:
        # ↑ 无论如何最后执行。
        app.dependency_overrides.clear()
        # ↑ 清理依赖覆盖。


def test_live_remains_ok_under_db_failure():
    # ↑ 测试：数据库故障时，live 接口仍然 200。

    """live 不注入数据库依赖，DB 故障时仍然 200。"""
    # ↑ docstring。
    app.dependency_overrides[get_db_session] = lambda: FakeSession(error=RuntimeError("db-down"))
    # ↑ 覆盖依赖，模拟数据库故障。
    try:
        # ↑ 保证清理。
        with TestClient(app) as client:
            # ↑ 创建客户端。
            response = client.get("/health/live")
            # ↑ 请求 live（它不依赖数据库）。
        assert response.status_code == 200
        # ↑ 断言 200（数据库挂了也不影响 live）。
    finally:
        # ↑ 清理。
        app.dependency_overrides.clear()
        # ↑ 清空覆盖。
