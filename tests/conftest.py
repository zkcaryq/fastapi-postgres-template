"""测试配置：不依赖本机 .env，也不需要真实数据库。

环境变量优先于 .env 文件，这里的赋值保证测试用确定性配置。
必须在 import app 之前完成：配置、Engine 与 Base.metadata 的 Schema
都在 import 时就读取并固定下来。
"""

import os

os.environ.update(
    {
        "APP_NAME": "Test App",
        "APP_ENV": "testing",
        "DEBUG": "false",
        "HOST": "127.0.0.1",
        "PORT": "8000",
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "5432",
        "DB_NAME": "test_db",
        "DB_USER": "test_user",
        "DB_PASSWORD": "test-password-not-a-real-secret",
        "DB_SCHEMA": "test_schema",
    }
)

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import get_db_session  # noqa: E402
from app.main import app  # noqa: E402


class FakeSession:
    """替身 Session：只实现健康检查用到的协程方法，不建立真实连接。"""

    def __init__(self, *, accessible: bool = True, error: Exception | None = None):
        self.accessible = accessible
        self.error = error
        self.executed: list[str] = []

    async def execute(self, statement, *args, **kwargs) -> None:
        self.executed.append(str(statement))
        if self.error is not None:
            raise self.error

    async def scalar(self, statement, *args, **kwargs) -> bool:
        if self.error is not None:
            raise self.error
        return self.accessible


@pytest.fixture
def client() -> Iterator[TestClient]:
    """整 App 的测试客户端；不带数据库依赖覆盖。"""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def ready_client() -> Iterator[object]:
    """工厂 fixture：ready_client(session) 返回注入该 Session 的客户端。"""

    def factory(session: FakeSession) -> TestClient:
        app.dependency_overrides[get_db_session] = lambda: session
        return TestClient(app)

    yield factory
    # 每个用例结束后必须清理，否则依赖覆盖会泄漏到其他测试。
    app.dependency_overrides.clear()
