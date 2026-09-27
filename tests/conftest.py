"""测试配置：不依赖本机 .env，也不需要真实数据库。

环境变量优先于 .env 文件，这里的赋值保证测试用确定性配置。
必须在 import app 之前完成：配置、Engine 与 Base.metadata 的 Schema
都在 import 时就读取并固定下来。
"""
# ↑ 模块 docstring：这个文件是 pytest 的"全局配置"，在所有测试运行前先执行。
#   它干两件事：① 用假的环境变量替代真实的 .env；② 提供一些公共的测试工具。

# 导入 os 标准库：用来操作环境变量。
import os

os.environ.update(
    # ↑ 把一组假配置写进进程的环境变量（因为环境变量优先于 .env，测试就会用这些假值）。
    {
        "APP_NAME": "Test App",
        # ↑ 应用名（测试用占位值）。
        "APP_ENV": "testing",
        # ↑ 环境设为 testing（这样 /docs 等保持开放，方便测试）。
        "DEBUG": "false",
        # ↑ 关闭调试。
        "HOST": "127.0.0.1",
        # ↑ 监听地址。
        "PORT": "8000",
        # ↑ 端口。
        "DB_HOST": "127.0.0.1",
        # ↑ 数据库主机（占位，不会真连）。
        "DB_PORT": "5432",
        # ↑ 数据库端口。
        "DB_NAME": "test_db",
        # ↑ 数据库名（占位）。
        "DB_USER": "test_user",
        # ↑ 数据库用户名（占位）。
        "DB_PASSWORD": "test-password-not-a-real-secret",
        # ↑ 数据库密码（占位，明确不是真实密钥）。
        "DB_SCHEMA": "test_schema",
        # ↑ Schema 名（占位）。
    }
)
# ↑ 注意：这段必须在任何 `import app.*` 之前执行，因为 app 在 import 时就会
#   读取并固定配置。所以这些 import 下面才出现，并标了 noqa: E402（见下）。

# 导入 Iterator 类型（用于标注 fixture 的返回类型）。
from collections.abc import Iterator  # noqa: E402

# 导入 pytest（测试框架）和 TestClient（模拟 HTTP 请求的客户端）。
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# 导入 app 的数据库会话依赖函数和主应用实例。
from app.db.session import get_db_session  # noqa: E402
from app.main import app  # noqa: E402

# ↑ 上面几个 import 都加了 noqa: E402，意思是"忽略 'import 不在文件顶部' 的 lint 规则"。
#   因为我们必须先写 os.environ.update(...)，才能 import app，这是刻意的顺序。


class FakeSession:
    # ↑ 定义一个"假的数据库会话"，用来在测试里替代真实的 Session。
    #   这样测试不用真的连数据库。

    """替身 Session：只实现健康检查用到的协程方法，不建立真实连接。"""

    # ↑ docstring：说明它只模拟健康检查用到的方法。

    def __init__(self, *, accessible: bool = True, error: Exception | None = None):
        # ↑ 初始化：accessible 表示"数据库是否可访问"，error 是可选的要抛出的异常。
        self.accessible = accessible
        # ↑ 记住"可访问"标记。
        self.error = error
        # ↑ 记住"要抛出的异常"（如果传了）。
        self.executed: list[str] = []
        # ↑ 记录"执行过的 SQL"（供测试断言用）。

    async def execute(self, statement, *args, **kwargs) -> None:
        # ↑ 模拟执行 SQL：记录这条 SQL，如果设定了 error 就抛出。
        self.executed.append(str(statement))
        # ↑ 把 SQL 语句转成字符串记录下来。
        if self.error is not None:
            # ↑ 如果设定了要抛出的异常……
            raise self.error
            # ↑ 抛出来（模拟数据库故障）。

    async def scalar(self, statement, *args, **kwargs) -> bool:
        # ↑ 模拟"取单个值"：健康检查里用它查 Schema 权限。
        if self.error is not None:
            # ↑ 有异常就抛。
            raise self.error
        return self.accessible
        # ↑ 返回"是否可访问"标记。


@pytest.fixture
# ↑ 声明一个 pytest fixture（测试夹具）。fixture 是可复用的"准备动作"，
#   测试函数在参数里写它的名字，pytest 就会自动调用它。
def client() -> Iterator[TestClient]:
    # ↑ 这个 fixture 提供一个"测试客户端"。

    """整 App 的测试客户端；不带数据库依赖覆盖。"""
    # ↑ docstring。
    with TestClient(app) as test_client:
        # ↑ 创建测试客户端（能像真服务器一样发请求，但跑在内存里）。
        yield test_client
        # ↑ 把客户端交给测试函数使用。


@pytest.fixture
def ready_client() -> Iterator[object]:
    # ↑ 这个 fixture 是一个"工厂"：调用 ready_client(某个FakeSession) 会返回
    #   一个注入了该假 Session 的测试客户端。

    """工厂 fixture：ready_client(session) 返回注入该 Session 的客户端。"""
    # ↑ docstring。

    def factory(session: FakeSession) -> TestClient:
        # ↑ 内部工厂函数：接收一个假 Session。
        app.dependency_overrides[get_db_session] = lambda: session
        # ↑ 关键：覆盖 app 的数据库依赖，让 /health/ready 拿到我们给的假 Session，
        #   而不是真实的数据库连接。
        return TestClient(app)
        # ↑ 返回测试客户端。

    yield factory
    # ↑ 把工厂函数交给测试使用。
    # 每个用例结束后必须清理，否则依赖覆盖会泄漏到其他测试。
    # ↑ 说明：测试跑完后要清掉覆盖，否则影响下一个测试。
    app.dependency_overrides.clear()
    # ↑ 清空所有依赖覆盖。
