"""健康检查：live 不依赖数据库，ready 覆盖成功与各类失败分支。"""

from sqlalchemy.exc import SQLAlchemyError

from tests.conftest import FakeSession


def test_live_is_ok_without_database(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_live_has_request_id(client):
    response = client.get("/health/live")
    assert response.headers["X-Request-ID"]


def test_ready_ok(ready_client):
    response = ready_client(FakeSession(accessible=True)).get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_without_schema_privilege(ready_client):
    response = ready_client(FakeSession(accessible=False)).get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_ready_database_error(ready_client):
    response = ready_client(FakeSession(error=SQLAlchemyError("connection refused"))).get(
        "/health/ready"
    )
    assert response.status_code == 503
    # 探针不泄露异常详情，避免把连接信息暴露给调用方。
    assert "connection refused" not in response.text
    assert response.json() == {"status": "not_ready"}


def test_ready_timeout(ready_client):
    response = ready_client(FakeSession(error=TimeoutError())).get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
