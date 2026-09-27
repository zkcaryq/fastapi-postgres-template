"""健康检查：live 不依赖数据库，ready 覆盖成功与各类失败分支。"""
# ↑ 模块 docstring：测试 /health/live 和 /health/ready 两个接口。

# 导入 SQLAlchemy 的异常基类（用于模拟数据库错误）。
from sqlalchemy.exc import SQLAlchemyError

# 导入测试公共工具里的假 Session。
from tests.conftest import FakeSession


def test_live_is_ok_without_database(client):
    # ↑ 测试：live 接口不依赖数据库，即使没有数据库也返回 200。

    response = client.get("/health/live")
    # ↑ 请求 live 接口（client 是 conftest 里定义的 fixture）。
    assert response.status_code == 200
    # ↑ 断言状态码 200。
    assert response.json() == {"status": "ok"}
    # ↑ 断言响应体。


def test_live_has_request_id(client):
    # ↑ 测试：live 接口的响应也带 X-Request-ID。

    response = client.get("/health/live")
    # ↑ 请求。
    assert response.headers["X-Request-ID"]
    # ↑ 断言响应头里有 X-Request-ID（非空即通过）。


def test_ready_ok(ready_client):
    # ↑ 测试：数据库可访问时 ready 返回 200。

    response = ready_client(FakeSession(accessible=True)).get("/health/ready")
    # ↑ 用"可访问"的假 Session 请求 ready 接口。
    assert response.status_code == 200
    # ↑ 断言 200。
    assert response.json() == {"status": "ok"}
    # ↑ 断言响应体。


def test_ready_without_schema_privilege(ready_client):
    # ↑ 测试：Schema 无权限时 ready 返回 503。

    response = ready_client(FakeSession(accessible=False)).get("/health/ready")
    # ↑ 用"不可访问"的假 Session（模拟 Schema 没权限）。
    assert response.status_code == 503
    # ↑ 断言 503。
    assert response.json() == {"status": "not_ready"}
    # ↑ 断言响应体。


def test_ready_database_error(ready_client):
    # ↑ 测试：数据库抛异常时 ready 返回 503。

    response = ready_client(FakeSession(error=SQLAlchemyError("connection refused"))).get(
        "/health/ready"
    )
    # ↑ 用会抛数据库异常的假 Session。
    assert response.status_code == 503
    # ↑ 断言 503。
    # 探针不泄露异常详情，避免把连接信息暴露给调用方。
    # ↑ 说明。
    assert "connection refused" not in response.text
    # ↑ 断言响应文本里没有"连接被拒"的细节（不泄露内部信息）。
    assert response.json() == {"status": "not_ready"}
    # ↑ 断言响应体。


def test_ready_timeout(ready_client):
    # ↑ 测试：数据库检查超时时 ready 返回 503。

    response = ready_client(FakeSession(error=TimeoutError())).get("/health/ready")
    # ↑ 用会抛超时异常的假 Session。
    assert response.status_code == 503
    # ↑ 断言 503。
    assert response.json() == {"status": "not_ready"}
    # ↑ 断言响应体。
