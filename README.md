# FastAPI Backend Template

业务无关的精简 FastAPI 后端模板：FastAPI + SQLAlchemy 2 + PostgreSQL + Alembic + uv。
解压后改 `.env`、写 Model / Schema / Service / Router、生成迁移，就可以开始新项目。

模板本体（`app/`）不含任何业务实体；唯一的真实代码是一组分层示例，位于
`examples/student_crud/`，可整组删除或复制进 `app/`。

## 1. 五分钟开始

```powershell
# 复制配置（仅在 .env 不存在时）
if (-not (Test-Path -LiteralPath .env) -and (Test-Path -LiteralPath .env.example)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}

uv sync
```

填写 `.env`：

| 必填 | 含义 |
| --- | --- |
| `APP_NAME` | OpenAPI 标题 |
| `DB_HOST` / `DB_PORT` / `DB_NAME` | 数据库地址、端口、数据库名 |
| `DB_USER` / `DB_PASSWORD` | 运行时账号；密码是 `SecretStr`，不会打印 |
| `DB_SCHEMA` | 必填，模板不创建 Schema |

```powershell
uv run python -m app --reload
```

`uvicorn` CLI 的 `--host` / `--port` 不会读取这里的配置；想走 CLI 请显式传入。

## 2. 这是什么

- **空业务基础设施**：配置、日志、ORM Base、连接池、Session、lifespan、
  Middleware Stack、Alembic 骨架、健康检查都在位。
- **教学示例在 `examples/`**：`examples/student_crud/` 演示一张表怎么从
  Model 走到 HTTP，复制后改字段名即可作为真实业务起点。
- **不绑定业务实体**：`app/` 内没有 User / Product / Order 之类固定业务代码。
- **自带冒烟测试**：84 个 unit 用例不需要真实数据库、本机 `.env`；
  21 个 integration 用例默认跳过，需要真实 PostgreSQL + `INTEGRATION_DATABASE_URL` 启用。

模板故意**不**带 Ruff 以外的检查工具、Redis、JWT、OAuth、Docker、监控、消息队列、
Repository、CQRS、DDD 基类。出现真实需求时再引入。

## 3. 技术栈与分层

Python 3.13、uv、FastAPI、Pydantic 2 / pydantic-settings、SQLAlchemy 2、
psycopg 3、PostgreSQL、Alembic、pytest（+ pytest-asyncio）、ruff。
`pyproject.toml` 声明版本范围，`uv.lock` 锁定可复现版本。

```text
HTTP → Router → Service → SQLAlchemy Model / AsyncSession → PostgreSQL
          ↕
     Pydantic Schema
```

| 层 | 职责与边界 |
| --- | --- |
| Router | 路由、依赖注入、请求与响应、HTTP 状态码；不承载业务 |
| Service | 业务规则、查询编排、事务边界；不依赖 FastAPI 的 Depends / HTTPException |
| Model | 数据库表、字段、约束；继承 Base |
| Schema | API 输入输出；不充当 ORM Model |
| db | Engine、连接池、Session、Base |
| core | 配置、日志、Middleware、Windows 兼容事件循环 |

不创建通用 CRUD 基类、Repository、DAO。出现真实复用需求再引入抽象。

## 4. 目录

```text
backend/
├── app/                              # 模板核心；不含任何业务实体
│   ├── __init__.py
│   ├── __main__.py                   # 统一启动入口，读取 HOST/PORT 与 Windows 兼容 loop
│   ├── main.py                       # 应用、lifespan、Middleware Stack
│   ├── core/
│   │   ├── __init__.py
│   │   ├── settings.py               # pydantic-settings，Fail Fast
│   │   ├── logging.py                # 开发文本 / 生产 JSON，密码脱敏 + request_id
│   │   ├── request_id.py             # X-Request-ID 中间件与 contextvar
│   │   ├── body_limit.py             # 请求体大小限制（413，含 chunked 计数）
│   │   ├── errors.py                 # 未捕获异常的统一 500 出口
│   │   └── event_loop.py             # Windows psycopg 异步兼容
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py                   # DeclarativeBase + 统一命名规则
│   │   ├── alembic_guard.py          # 提取出来供测试的 alembic 护栏
│   │   └── session.py                # AsyncEngine、连接池、Session dependency
│   ├── models/
│   │   └── __init__.py               # 空：显式注册新 Model
│   ├── schemas/
│   │   └── __init__.py               # 空
│   ├── services/
│   │   └── __init__.py               # 空
│   └── api/
│       ├── __init__.py
│       ├── dependencies.py           # DbSession 注入
│       ├── router.py                 # /api/v1 挂载入口（默认空）
│       └── routes/
│           ├── __init__.py
│           └── health.py             # /health/live, /health/ready
├── alembic/
│   ├── versions/.gitkeep             # 仓库里保持空；新项目自己 generate
│   ├── env.py                        # 迁移账号优先；空 metadata 护栏
│   ├── script.py.mako
│   └── README
├── examples/
│   └── student_crud/                 # 教学示例（独立于 app/）
│       ├── README.md
│       ├── model.py                  # Identity 主键 + NOT NULL 示例
│       ├── schema.py                 # PATCH 语义：区分“未传”与“显式 null”
│       ├── service.py                # 事务边界 + IntegrityError 映射（含 23502）
│       └── router.py
├── tests/
│   ├── conftest.py                   # 注入测试配置与 FakeSession
│   ├── test_app.py                   # main.py 的中间件接线顺序
│   ├── test_errors.py                # UnexpectedError + RequestId 子集
│   ├── test_health.py                # live / ready 与失败分支
│   ├── test_middleware.py            # 完整 Middleware Stack 集成测试
│   ├── test_settings.py              # 配置层校验（含迁移账号回退）
│   ├── test_logging.py               # 密码脱敏 + 路径不泄露
│   ├── test_alembic_env.py           # 空 metadata 护栏
│   ├── test_lifespan.py              # shutdown timeout 行为（mocked）
│   ├── examples/                     # 教学 Example 的单元测试
│   │   ├── test_student_schema.py    # PATCH nullable 语义
│   │   └── test_student_model.py     # Identity + NOT NULL 约束
│   └── integration/                  # 需要真实 PG；默认跳过
│       ├── conftest.py
│       ├── _models.py                # 测试专用 ORM（独立 DeclarativeBase）
│       ├── _alembic/                 # 测试专用 alembic env
│       ├── test_alembic_lifecycle.py # revision / upgrade / downgrade / check / 增量
│       ├── test_async_session.py     # autoflush / commit / rollback / statement_timeout
│       ├── test_connection_params.py # search_path / 超时参数 / idle-in-tx 真实断连
│       └── test_sqlstate.py          # 23505 / 23502 / 23514 / 23503
├── docs/
│   ├── PROJECT_WALKTHROUGH.md        # 源码级讲解文档
│   └── EXISTING_DATABASE_MIGRATION.md
├── .env.example
├── .gitignore
├── .python-version
├── alembic.ini
├── pyproject.toml
├── README.md
└── uv.lock
```

## 5. 配置

| 配置 | 含义 |
| --- | --- |
| `APP_NAME` | OpenAPI 标题 |
| `APP_ENV` | `development` / `testing` / `production` |
| `DEBUG` | 日志调试开关；不开启客户端 traceback |
| `HOST` / `PORT` | `python -m app` 的绑定地址与端口 |
| `DB_HOST` / `DB_PORT` / `DB_NAME` | 数据库地址、端口、数据库名 |
| `DB_USER` / `DB_PASSWORD` | 运行时账号；理论上只需 DML 权限 |
| `MIGRATION_DB_USER` / `MIGRATION_DB_PASSWORD` | 可选；未配置时回退到运行时账号 |
| `DB_SCHEMA` | 必填；小写字母/数字/下划线，最长 63 字符，不能以数字开头 |
| `DB_SSLMODE` | libpq TLS 模式；生产按 `verify-full` + `DB_SSLROOTCERT` 配 |
| `DB_CONNECT_TIMEOUT` | 建连超时（秒） |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 每进程常规池 + 临时溢出 |
| `DB_POOL_TIMEOUT` | 等待池连接最长秒数 |
| `DB_STATEMENT_TIMEOUT_MS` | 单条 SQL 超时（毫秒），由数据库主动中止 |
| `DB_IDLE_IN_TX_TIMEOUT_MS` | 事务空闲超时（毫秒），由数据库主动中止 |
| `HEALTH_TIMEOUT` | `/health/ready` 整体数据库检查最长秒数 |
| `MAX_REQUEST_BODY_BYTES` | HTTP 请求体上限；超过直接 413 |
| `SHUTDOWN_TIMEOUT` | lifespan 关闭连接池的最长等待秒数 |

环境变量优先于 `.env`；配置被 `lru_cache` 缓存，修改后重启进程。

### 数据库账号分离

模板**支持**运行时账号与迁移账号独立配置，但**不强制**：

- 仅配置 `DB_USER` / `DB_PASSWORD`：开发环境最常用；同一份账号负责运行时和迁移。
- 同时配置 `MIGRATION_DB_USER` / `MIGRATION_DB_PASSWORD`：生产环境推荐；
  运行时账号理论上只授予 `SELECT / INSERT / UPDATE / DELETE`，
  迁移账号拥有 `CREATE / ALTER / DROP` 等 DDL 权限。

运行时连接永远走 `Settings.database_url`；Alembic 永远走 `Settings.migration_database_url`。
迁移账号的密码不会被运行时记录到日志（Alembic 在自己的进程里读同一份配置）。

## 6. 自定义 Schema

`DB_SCHEMA` 没有默认值，填什么就用什么。Schema 与数据库本身由你或 DBA 提前创建，
模板**不创建数据库、不创建 Schema、不执行授权、不 stamp/重置版本、不删除对象**。

创建账号需有数据库 `CREATE` 权限；已有 Schema 至少需 `USAGE`，
迁移账号还需 `CREATE` 及后续对象所有权 / DDL 权限，
应用账号按业务只授予必要的表 / 序列权限。

运行时与迁移连接都把 `search_path` 固定为 `pg_catalog`，Model 由 `Base.metadata`
带上 `DB_SCHEMA` 前缀，因此不受账号默认 Schema 干扰。
手写 SQL 必须明确限定业务 Schema；优先用 ORM / Core 对象，不用字符串拼接标识符。
不要在请求中改变 `search_path`。

Alembic 版本表 `alembic_version` 与业务表放在同一个显式配置的 Schema，
因此迁移初始化独立于业务 revision。应用启动和迁移不会自动创建缺失 Schema。

### PostgreSQL 扩展与 search_path

`search_path=pg_catalog` 不只影响 table 查找，还影响 type / function / operator /
extension object 的解析。以后引入以下扩展时需要确认扩展默认 Schema：

- `pgvector` 通常装在 `public` / `extensions`，需要在查询里显式 schema 限定
- `PostGIS` 默认装在 `public`
- `uuid-ossp` 取决于 `CREATE EXTENSION` 时指定的 schema

**不要为了兼容扩展直接把模板恢复成宽松的 `search_path="$user", public`**。
要么在 DDL 里显式限定，要么经评估后调整并把这次决定写进项目文档。

## 7. 新增第一个 Model 与迁移

### 7.1 ⚠️ 模板解压后第一步

`app/models/__init__.py` 默认是**空的**，同时 ``alembic/versions/`` 也为空。
直接跑下面这条会立刻报错：

```powershell
uv run alembic revision --autogenerate -m "initial schema"
# ❌ Base.metadata 为空；autogenerate 会把已有表当作删除候选。
```

**正确的首次流程**：

```text
1. 创建第一个 Model：app/models/xxx.py（见下文）
2. 在 app/models/__init__.py 显式 import 这个 Model
3. 确认 DB_SCHEMA 在数据库里已经存在
4. uv run alembic revision --autogenerate -m "initial schema"
5. 人工审查生成的 revision 文件（upgrade / downgrade / 表 / 约束 / 索引）
6. uv run alembic upgrade head
7. uv run alembic check
```

**模板不做自动 Model 发现**：不会扫描 `app/models/*.py`，必须在 `__init__.py`
显式 import。这是设计选择，不是缺陷。

### 7.2 创建 Model

下面的 `Xxx` 是文档占位符，换成自己的业务名称。

创建 `app/models/xxx.py`：

```python
from sqlalchemy import Identity, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Xxx(Base):
    __tablename__ = "xxx"

    # BigInteger + PostgreSQL IDENTITY：与 SERIAL / BIGSERIAL 不等价。
    # 不要写 autoincrement=True：会让 SQLAlchemy 在 PG 上回退到 SERIAL。
    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=False),
        primary_key=True,
    )
```

更详细的写法见 `examples/student_crud/model.py`。

### 7.3 显式注册 Model

在 `app/models/__init__.py` **显式 import**：

```python
from app.models.xxx import Xxx

__all__ = ["Xxx"]
```

Alembic 通过 `import app.models` 发现所有表，不会扫描文件系统。

### 7.4 第一次生成迁移

```powershell
uv run alembic revision --autogenerate -m "create initial tables"
# 人工审查 upgrade / downgrade 后再 apply
uv run alembic upgrade head
uv run alembic check
```

**每次 autogenerate 后必须人工 review migration**：模板只挡住“所有 Model
都没注册”的极端情况，漏注册单个 Model 时不会拦截。

## 8. 新增 API Schema、Service、Router

`app/schemas/xxx.py` 示例：

```python
from pydantic import BaseModel, ConfigDict, Field


class XxxCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)


class XxxResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
```

PATCH 语义要点：

- **未传字段**：保持数据库原值；
- **显式 `null`**：如果对应列允许 NULL，把列改成 NULL；
- **对 NOT NULL 字段显式 `null`**：请求校验阶段直接 `422`，不进 Service。

区分“未传”与“显式 null”使用 `payload.model_fields_set` + `model_dump(exclude_unset=True)`；
正确实现参考 `examples/student_crud/schema.py::StuUpdate`。

`app/services/xxx.py` 示例：

```python
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.xxx import Xxx
from app.schemas.xxx import XxxCreate


async def create_xxx(session: AsyncSession, payload: XxxCreate) -> Xxx:
    entity = Xxx(name=payload.name)
    session.add(entity)
    await session.commit()
    return entity
```

事务边界属于**完整业务 Use Case**：单个 Service 函数目前就是一个 Use Case；
以后出现“创建订单 + 扣库存 + 写支付记录”这种原子操作，由外层编排函数控制
事务与 `commit`，被编排的内部函数只 `flush` 不 `commit`。
不要引入自动 `commit` 的 BaseService / UnitOfWork。

`app/api/routes/xxx.py` 示例：

```python
from fastapi import APIRouter
from app.api.dependencies import DbSession
from app.schemas.xxx import XxxCreate, XxxResponse
from app.services.xxx import create_xxx

router = APIRouter(prefix="/xxx", tags=["xxx"])


@router.post("", response_model=XxxResponse, status_code=201)
async def create(payload: XxxCreate, session: DbSession):
    return await create_xxx(session, payload)
```

在 `app/api/router.py` 中 `api_router.include_router(router)`，最终地址 `/api/v1/xxx`。

## 9. Engine、连接池、Session 和事务

- Engine：每个进程一个数据库入口，持有连接池；import 时不会立即连接数据库。
- 连接池：按需建立连接，`pool_size` 是常规保留上限，不是启动时预开数量。
- Session：每个使用数据库的请求独立创建；`expire_on_commit=False` + `autoflush=False`
  是 AsyncSession 推荐默认配置。
- dependency：请求完成时关闭 Session，未提交的事务回滚、连接归还。
  **不自动 commit**；提交失败的业务必须 rollback，不能继续使用失败的事务。
- lifespan：退出时 `await engine.dispose()`；超时由 `SHUTDOWN_TIMEOUT` 控制。

`session.add()` 之后**不会**自动 flush。如果同一事务里后续 SELECT 依赖这个写入，
必须显式 `await session.flush()`，不要依赖隐式 autoflush。

连接预算：`进程数 × (DB_POOL_SIZE + DB_MAX_OVERFLOW)`，
还要为迁移、运维及其他服务留余量。
`pool_pre_ping=True` 能发现闲置连接失效，不保证事务中断后自动重放业务写入。

## 10. 启动与健康检查

```powershell
uv run python -m app --reload
```

| 接口 | 含义 | 数据库失败时 |
| --- | --- | --- |
| `GET /health/live` | HTTP 进程可响应，不获取数据库 Session | 200 |
| `GET /health/ready` | `SELECT 1` 且目标 Schema 有 USAGE 权限 | 503 |

`ready` 不代表所有表、迁移版本、业务权限均已正确，不代替真实业务监控。
`ready` 返回固定响应，不输出数据库地址或异常详情。

## 11. Middleware Stack

`app/main.py` 的中间件注册顺序（最后 `add` 的最外层）：

```text
RequestIdMiddleware              ← 最外：设置 request_id contextvar；强制覆盖响应头
  └─ UnexpectedErrorMiddleware   ← 把漏出的异常转成 500（带 request_id / error_id）
      └─ BodySizeLimitMiddleware  ← 最内：自己消费 _BodyTooLarge → 413
          └─ ExceptionMiddleware (Starlette)
              └─ Router
```

设计要点：

- **RequestId 最外**：响应头 `X-Request-ID` 与日志 / 错误响应里的 request_id
  一一对应。即使内部代码写过 `X-Request-ID`，外层 RequestIdMiddleware 也会强制覆盖。
- **BodySizeLimit 最内**：自己 try/except `_BodyTooLarge` 再生成 413；
  异常先于 UnexpectedError 被消费。如果顺序反过来，413 会被吞成 500。
- **HTTPException 不会被 UnexpectedError 吞**：404 / 405 由 Starlette 的
  ExceptionMiddleware 处理。

请求体大小限制：

- 声明了 `Content-Length` 且超过 `MAX_REQUEST_BODY_BYTES`：直接 413，**完全不读 body**；
- 没有 `Content-Length`（chunked 传输）或声明值撒谎：转发时累计实际字节数，
  超限立即中断读取并返回 413，业务代码不会被调用；
- `Content-Length` 无法解析：400。

## 12. 日志与异常、请求 ID

- 生产 JSON、开发文本；带 `request_id` 字段。
- `SafeFormatter` 替换消息中出现的 `DB_PASSWORD` 字面量；
  这是基础保护，不意味着任何 Token / API Key 都会被自动识别。
- 默认关闭 Uvicorn access log（默认会打印完整 URL，未来容易泄漏查询串里的 Token）。
- 异常只保留类型 + 文件相对路径 + 行号 + 函数名，不记录异常值、源码行、局部变量。
- 413 / 500 / 4xx 都返回 `X-Request-ID`；500 还附带 `error_id` 用于日志侧关联。

## 13. 测试

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

测试是模板自带的基础设施：

- 不连接真实数据库（`FakeSession` 替身）。
- 不读取本机 `.env`（conftest 在 import `app` 之前注入固定的测试环境变量）。
- `tests/test_middleware.py` 盯住完整 Middleware Stack 的真实行为；
  顺序错了会有人工可见的失败。

集成测试（`tests/integration/`）默认跳过：

```powershell
# 启用集成测试（密码只经环境变量传入，不落任何文件）
INTEGRATION_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db uv run pytest -m integration
```

集成测试的前提与边界：

- 目标库中必须**已存在** `fastapi_template_test` Schema（conftest 不自动创建，
  缺失时立即失败并提示，避免掩盖权限问题）；
- 测试只在该 Schema 内建表 / 清表，**不触碰任何其他 Schema、表或数据**；
- 生成的临时 migration 写入 pytest 临时目录，不落入仓库 `alembic/versions/`；
- 验证内容：Alembic 完整生命周期（含 downgrade / 增量迁移）、
  Identity DDL（`information_schema` 实测）、四种 SQLSTATE 约束、
  `search_path=pg_catalog`、`statement_timeout` / `idle_in_transaction_session_timeout`
  真实生效、AsyncSession flush / commit / rollback 行为。
  完整清单见 `docs/PROJECT_WALKTHROUGH.md` § 8.3。

## 14. Alembic

新项目标准流程（前提：已按 § 7.1 创建并注册至少一个 Model）：

```powershell
uv run alembic revision --autogenerate -m "initial schema"
# 人工审查 upgrade / downgrade 后再 apply
uv run alembic upgrade head
uv run alembic check
```

审查要点（真实踩坑验证过的）：

- autogenerate **无差异时不报错**，会生成 `pass`/`pass` 的空迁移；
  “文件生成了”不等于“迁移有内容”，必须打开看。
- 迁移文件名以随机 revision hash 开头，文件名字母序 ≠ 创建顺序；
  按 `down_revision` 链定位，不要按文件名排序。
- 空 metadata 护栏只挡“一个 Model 都没注册”；漏注册单个 Model 不会被拦截。

模板里 `alembic/versions/` 初始为空（带 `.gitkeep`）；没有任何历史 baseline。
已有数据库接管属于特殊场景，流程见
[`docs/EXISTING_DATABASE_MIGRATION.md`](docs/EXISTING_DATABASE_MIGRATION.md)。

Alembic 永远走 `Settings.migration_database_url`：迁移账号独立时用它；
未配置迁移账号时回退到运行时账号（开发环境最常用）。

不要在应用启动时跑迁移；不用 `create_all()` 替代版本管理；生产迁移由独立部署步骤、
单个执行者运行；多 worker 不竞争执行 DDL。

## 15. 开发与生产差异

| 开发 | 生产 |
| --- | --- |
| 本地 `.env` | 部署平台注入配置与 Secret |
| reload，开放 `/docs` | 无 reload，关闭 `/docs` 与 OpenAPI |
| 可读文本日志 | UTC 时间戳的 JSON 标准输出日志 |
| 包含教学示例 | 删除 `examples/` 或将其明确标记为示例后再上线 |
| 可用迁移账号调试 | 迁移账号与运行账号分离；通过 `MIGRATION_DB_*` 独立注入 |
| 独立开发库 | 独立生产库，按连接预算设置 worker / 池 |

数据库连接固定 UTC；业务时间使用带时区的 datetime，展示时按业务要求转为本地时间。

## 16. 常用命令速查

| 目的 | 命令 |
| --- | --- |
| 安装依赖（含 dev） | `uv sync` |
| 仅安装生产依赖 | `uv sync --no-dev` |
| 静态检查 | `uv run ruff check .` |
| 格式校验 | `uv run ruff format --check .` |
| 格式化 | `uv run ruff format .` |
| 运行测试 | `uv run pytest` |
| 运行集成测试 | `INTEGRATION_DATABASE_URL=... uv run pytest -m integration` |
| 开发启动 | `uv run python -m app --reload` |
| 当前数据库版本 | `uv run alembic current` |
| 本地迁移头 | `uv run alembic heads` |
| 生成候选迁移 | `uv run alembic revision --autogenerate -m "describe change"` |
| 应用迁移 | `uv run alembic upgrade head` |
| 检查模型差异 | `uv run alembic check` |

参考：[SQLAlchemy AsyncSession](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)、
[Alembic 自动生成](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)、
[psycopg Windows 异步限制](https://www.psycopg.org/psycopg3/docs/advanced/async.html)、
[PostgreSQL 连接参数](https://www.postgresql.org/docs/17/libpq-connect.html)。
