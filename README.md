# FastAPI Backend Template

空业务基础设施 + 可直接删除的教学示例的精简 FastAPI 后端模板。
解压后改 `.env` 与 `pyproject.toml` 的项目名即可开始任何新项目，不绑定具体业务。

模板面向生产环境：异步 SQLAlchemy 2、psycopg 3、自定义 Schema、配置 Fail Fast、
不把请求体 / 查询串 / 原始异常写进日志。它不是某个具体系统的生产上线评审材料，
请按真实部署要求补齐进程托管、入口 TLS、备份演练与监控。

## 1. 五分钟开始

解压到任意目录后进入项目根目录，把 `.env.example` 复制成 `.env` 并填写连接参数，
其中 `DB_SCHEMA` **没有默认值**，必须填写你已经创建好的 Schema 名。
数据库本身以及 Schema 由你或 DBA 提前创建，本模板不建库、不建 Schema、不改授权。

```powershell
# 只在 .env 不存在时复制，避免覆盖已经填写的凭据。
if (-not (Test-Path -LiteralPath .env) -and (Test-Path -LiteralPath .env.example)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
uv sync
```

填写 `.env`：

| 必填 | 含义 |
| --- | --- |
| `APP_NAME` | OpenAPI 标题，仅显示名 |
| `DB_HOST` / `DB_PORT` / `DB_NAME` | 数据库地址、端口和数据库名 |
| `DB_USER` / `DB_PASSWORD` | 数据库登录身份；密码使用 `SecretStr`，不会打印 |
| `DB_SCHEMA` | 必填，模板不创建，由你提前创建好 |

```powershell
# 推荐跨平台入口：读取 HOST/PORT，兼容 Windows 的 psycopg 异步事件循环。
uv run python -m app --reload
```

`uvicorn` CLI 的 `--host` / `--port` 不会读取这里的配置；想要走 CLI 请显式传入。

## 2. 这是什么

- **空业务基础设施**：配置、日志、ORM Base、连接池、Session、lifespan、通用 500、
  Alembic 骨架、健康检查都在位，新项目不需要再搭骨架。
- **可运行的教学示例**：`models/student.py`、`schemas/student.py`、
  `services/student.py`、`api/routes/students.py` 用一张 `stu_table`
  演示主键自增、唯一约束、可空字段与事务边界，以及从 HTTP 到 SQL 的完整分层。
  开始自己的项目时直接删掉这些文件，README 第 5 节说明删除步骤。
- **不绑定业务实体**：没有 User / Product / Order 等固定业务代码。
- **带一套冒烟测试**：`tests/` 覆盖健康检查、请求 ID、请求体限制与通用 500，
  不连接真实数据库，也不需要本机 `.env`。

模板故意**不**带 ruff、Redis、JWT、Docker、CORS、CQRS、Repository
等组件——这些都是真实需求出现时再加，不预先堆叠。

## 3. 技术栈与分层

Python 3.13、uv、FastAPI、Pydantic 2 / pydantic-settings、SQLAlchemy 2、psycopg 3、
PostgreSQL、Alembic。`pyproject.toml` 声明兼容范围，`uv.lock` 锁定可复现版本。

```text
HTTP → Router → Service → SQLAlchemy Model / AsyncSession → PostgreSQL
          ↕
     Pydantic Schema
```

| 层 | 职责与边界 |
| --- | --- |
| Router | 路由、依赖注入、请求与响应、HTTP 状态；不承载业务 |
| Service | 业务规则、查询编排、事务边界；不依赖 FastAPI 的 Depends / HTTPException |
| Model | 数据库表、字段、约束；继承 Base |
| Schema | API 输入和输出；不充当 ORM Model |
| db | Engine、连接池、Session、Base |
| core | 配置、日志、Windows 兼容事件循环 |

不创建通用 CRUD 基类、Repository、DAO 或多层接口。
出现真实复用或跨数据源需求再引入抽象。

## 4. 目录

```text
fastapi-template/
├── app/
│   ├── __init__.py
│   ├── __main__.py              # 统一启动入口，读取 HOST/PORT 与 Windows 兼容 loop
│   ├── main.py                  # 应用、lifespan、通用 500
│   ├── core/
│   │   ├── __init__.py
│   │   ├── settings.py          # pydantic-settings，Fail Fast
│   │   ├── logging.py           # 开发文本 / 生产 JSON，密码脱敏 + request_id
│   │   ├── event_loop.py        # Windows psycopg 异步兼容性
│   │   ├── request_id.py        # X-Request-ID 中间件与 contextvar
│   │   ├── body_limit.py        # 请求体大小限制（413，含 chunked 计数）
│   │   └── errors.py            # 未捕获异常的统一 500 出口
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py              # DeclarativeBase + 统一命名规则
│   │   └── session.py           # AsyncEngine、连接池、Session dependency
│   ├── models/
│   │   ├── __init__.py          # 显式注册；新 Model 在此 import
│   │   └── student.py           # 教学示例：StuTable
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── student.py           # 教学示例：Create / Update / Response
│   ├── services/
│   │   ├── __init__.py
│   │   └── student.py           # 教学示例：CRUD + 冲突处理
│   └── api/
│       ├── __init__.py
│       ├── dependencies.py      # DbSession 注入
│       ├── router.py            # /api/v1 挂载入口
│       └── routes/
│           ├── __init__.py
│           ├── health.py        # /health/live, /health/ready
│           └── students.py      # 教学示例：/api/v1/students
├── tests/
│   ├── conftest.py              # 注入测试配置与替身 Session，不需要真实数据库
│   ├── test_app.py              # main.py 的中间件接线顺序
│   ├── test_errors.py           # 通用 500 的 error_id / request_id
│   ├── test_health.py           # live / ready 及其失败分支
│   └── test_middleware.py       # 请求 ID 与请求体限制
├── alembic/
│   ├── versions/                # 已有示例 baseline 迁移；新项目可清空重来
│   ├── env.py
│   ├── script.py.mako
│   └── README
├── .env.example
├── .gitignore
├── .python-version
├── alembic.ini
├── pyproject.toml
├── README.md
└── uv.lock
```

## 5. 把教学示例换成自己的业务

模板示例文件可以整组删除：

```powershell
Remove-Item -LiteralPath 'app\models\student.py'
Remove-Item -LiteralPath 'app\schemas\student.py'
Remove-Item -LiteralPath 'app\services\student.py'
Remove-Item -LiteralPath 'app\api\routes\students.py'
```

然后在 `app/models/__init__.py` 改成：

```python
# 新 Model 在这里显式 import；Alembic 通过导入本包发现表。
__all__: list[str] = []
```

`app/api/router.py` 移除示例路由的注册：

```python
from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")
# 新模块：api_router.include_router(xxx_router)
```

`app/main.py` 中的 `app.include_router(api_router)` 不必改动。

## 6. 配置与数据库连接

| 配置 | 含义 |
| --- | --- |
| `APP_NAME` | OpenAPI 标题；不改 import 路径 |
| `APP_ENV` | `development` / `testing` / `production` |
| `DEBUG` | 日志调试开关；不会开启客户端 traceback 或 SQL echo |
| `HOST` / `PORT` | `python -m app` 的绑定地址与端口 |
| `DB_HOST` / `DB_PORT` / `DB_NAME` | 数据库地址、端口和已有数据库名 |
| `DB_USER` / `DB_PASSWORD` | 数据库身份；必填，无真实凭据默认值 |
| `DB_SCHEMA` | 必填；小写字母/数字/下划线，最长 63 字符，不能以数字开头 |
| `DB_SSLMODE` | libpq TLS 模式；本地默认 `prefer`，生产按网络与证书明确设置 |
| `DB_SSLROOTCERT` | 可选 CA 文件路径，配合 `verify-full` |
| `DB_CONNECT_TIMEOUT` | 建连超时，默认 5 秒 |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 每进程常规池 5，临时溢出最多 5 |
| `DB_POOL_TIMEOUT` | 等待池连接最长 10 秒 |
| `DB_STATEMENT_TIMEOUT_MS` | 单条 SQL 超时（毫秒），由数据库主动中止，默认 30 000 |
| `DB_IDLE_IN_TX_TIMEOUT_MS` | 事务空闲超时（毫秒），由数据库主动中止，默认 60 000 |
| `HEALTH_TIMEOUT` | `/health/ready` 整体数据库检查最长 5 秒 |
| `MAX_REQUEST_BODY_BYTES` | HTTP 请求体上限（字节），超过直接 413，默认 1 MiB |

环境变量优先于项目根 `.env`；配置被缓存，修改后重启进程。
必填字段缺失、端口不合法、Schema 非法、`DB_PASSWORD` 为空立即报错。
生产环境不允许 `DEBUG=true`。`SecretStr` 与 `hide_input_in_errors` 只是基础保护，
业务代码仍禁止打印完整配置对象。

国内云 RDS / 自建 PostgreSQL 都使用相同协议：填写内网地址、端口、数据库、账号、
Schema；由运维配置白名单 / 安全组和 TLS。
公网连接推荐 `DB_SSLMODE=verify-full` 并填写 `DB_SSLROOTCERT`。
`prefer` 不强制加密，`require` 也不等于完整验证服务器身份。
模板不硬编码某家国内镜像源；下载受限时由组织配置可信的 uv 源。

## 7. 自定义 Schema

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

本模板面向一个项目一个主 Schema，不是租户路由系统。
多个项目应使用各自的数据库或专用 Schema，不能让两个项目在同一 Schema 中各自维护
互不知情的版本历史。Alembic 自动生成只扫描所配置 Schema，
但同一 Schema 内的旧表仍可能被判断为删除。

**新项目第一次迁移生成前确定 Schema 名称。** 自动生成的迁移会固化 Schema 名字；
以后不能靠改 `DB_SCHEMA` 搬迁已有表。建议同一项目开发 / 测试 / 生产使用相同 Schema 名，
通过不同数据库或实例隔离。变更既有 Schema 需要单独设计迁移，不改旧 revision。

## 8. 新增第一个 Model 与迁移

下面的 `Xxx` 是文档占位符，换成自己的业务名称。

创建 `app/models/xxx.py`：

```python
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Xxx(Base):
    __tablename__ = "xxx"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
```

在 `app/models/__init__.py` **显式注册**：

```python
from app.models.xxx import Xxx

__all__ = ["Xxx"]
```

定义类的模块只有被 import 后才会把表注册到 `Base.metadata`。
Alembic 导入 `app.models`，不会扫描整个文件系统；不要在 `main.py` 再逐个导入。
检查约束请提供稳定的 `name`；复合约束由 `Base` 中的统一命名规则生成名称。

```powershell
uv run alembic current
uv run alembic heads
uv run alembic revision --autogenerate -m "create initial tables"
# 打开新生成的文件，审查 upgrade / downgrade，确认没有误删、跨 Schema 操作。
uv run alembic upgrade head
uv run alembic current
uv run alembic check
```

空模板的 `heads` 无输出正常；已有空 Schema、无版本表时 `current` 无 revision 正常。
未注册任何 Model 时阻止 autogenerate，以免空 metadata 产生误删候选。
`revision --autogenerate` 需要连接数据库，仅生成候选文件；`upgrade head` 才修改结构。
自动生成不能可靠猜出改名、数据迁移或所有复杂约束，必须审查后提交。

后续流程始终是：修改 Model → 生成 revision → 审查 → 测试 → 执行 upgrade。
需要回滚时先确认迁移的 downgrade 是否会丢数据，并完成备份，
不能把 downgrade 当作通用撤销按钮。
不要在应用启动时运行迁移，不用 `create_all()` 替代版本管理。
生产迁移由独立部署步骤、单个执行者运行；多 worker 不竞争执行 DDL。

## 9. 新增 API Schema、Service、Router

`app/schemas/xxx.py` 示例：

```python
from pydantic import BaseModel, ConfigDict, Field


class XxxCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class XxxUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)


class XxxResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
```

部分更新用 `payload.model_dump(exclude_unset=True)` 区分未传与显式 null；
数据库字段不允许 null 时，业务必须拒绝显式 null，
而不是直接把这份字典写入数据库。
输出模型只声明允许返回的字段，避免把内部字段无意暴露。

`app/services/xxx.py` 示例：

```python
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.xxx import Xxx
from app.schemas.xxx import XxxCreate


async def create_xxx(session: AsyncSession, payload: XxxCreate) -> Xxx:
    entity = Xxx(name=payload.name)
    try:
        session.add(entity)
        await session.flush()  # 发 SQL、获得主键，还没有提交。
        await session.commit()  # 本次业务操作的明确事务边界。
    except Exception:
        await session.rollback()  # 不吞异常，回滚后交给上层处理。
        raise
    return entity
```

不需要 `refresh`；只有确实要重新读取数据库生成值时才调用
`await session.refresh(entity)`，不要每次写入都机械多查一次。
多个操作必须原子提交时，由编排它们的外层 Service 统一控制事务，内部函数只 flush，
不要调用多个各自 commit 的函数后误以为仍是一个事务。

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

在 `app/api/router.py` 中导入 router 并执行 `api_router.include_router(router)`，
最终地址为 `/api/v1/xxx`。业务错误按真实需求由 Router 映射到 HTTP 状态码；
模板不预造业务异常框架。

## 10. 教学示例：stu_table

模板自带 `models/student.py`、`schemas/student.py`、`services/student.py`、
`api/routes/students.py`，**不要把它当作业务实现**，
仅用来演示一列该怎么从数据库一路走到 HTTP 响应。

示例只是单表，没有外键：外键会牵出关系属性加载方式的选择，
那是另一个主题，按真实需求再加。

`StuTable`（`models/student.py`）演示：

| 字段 | 演示点 |
| --- | --- |
| `stu_id` | `BigInteger` 主键 + 自增，实际由 PostgreSQL IDENTITY 生成 |
| `stu_number` | `String(32)` + `nullable=False` + `unique=True`，唯一约束名由 Base 命名规则生成 |
| `stu_name` | 必填且不唯一的普通字符串 |
| `stu_class` / `stu_major` / `stu_college` | `Mapped[str \| None]` 与 `nullable=True` 保持一致，尚未分班时允许 NULL |
| `stu_phone` / `stu_email` / `stu_address` | 可空字段的长度上限一般在 32～255 之间按实际用途定 |

`schemas/student.py` 演示：

- `StuCreate` / `StuUpdate` 用 `extra="forbid"` 拒绝未知字段（包括客户端伪造的主键），
  `str_strip_whitespace=True` 去掉首尾空白。
- `StuUpdate` 全字段可选，配合路由层的 PATCH 语义表示"没传就不动"。
- `StuResponse` 用 `from_attributes=True` 从 ORM 对象构造，白名单式地只暴露允许返回的列。

`services/student.py` 演示：

- 错误码映射：`IntegrityError.orig.sqlstate` 转业务异常 `DataConflict`
  （23505 唯一冲突 / 23503 外键 / 23514 检查约束），Router 决定 HTTP 状态码。
- 事务边界集中在 `_commit`：只有它有 `commit`，失败先 `rollback` 再抛，
  不把数据库原始错误文本抛给客户端。
- `update_student` 用 `model_dump(exclude_unset=True)` 区分未传与显式 null。

`api/routes/students.py` 演示：

- 路由只声明依赖并映射状态码；`HTTPException` 仅出现在路由层，Service 不知道 HTTP。
- 端点：`POST /api/v1/students`、`GET /api/v1/students`（`offset` / `limit` 分页）、
  `GET /api/v1/students/{stu_id}`、`PATCH /api/v1/students/{stu_id}`、
  `DELETE /api/v1/students/{stu_id}`（204）。

## 11. Engine、连接池、Session 和事务

- Engine：每个进程一个数据库入口，持有连接池；import 时不会立即连接数据库。
- 连接池：按需建立连接，`pool_size` 是常规保留上限，不是启动时预开数量；
  高峰允许 `max_overflow` 临时连接，`pool_timeout` 限制等待时间。
- Session：每个使用数据库的请求独立创建，承载对象状态和事务。
  第一次 SQL 时才可能取连接；不等于整个请求始终占用一条物理连接。
- dependency：请求完成时关闭 Session，未提交的事务回滚、连接归还。
  不自动 commit；提交失败的业务必须 rollback，不能继续使用失败的事务。
- lifespan：退出时 `await engine.dispose()` 释放连接池资源。

同一个请求里使用并发任务时，每个并发任务也必须有自己的 Session。
后台任务应自己创建 / 关闭 Session，不复用即将结束的请求 Session。
异步适合数据库 / 网络 I/O 等待，CPU 密集或同步阻塞工作需另行处理。

连接预算：`进程数 × (DB_POOL_SIZE + DB_MAX_OVERFLOW)`，
还要为迁移、运维及其他服务留余量。
`pool_pre_ping` 能发现闲置连接失效，不能保证事务中断后自动重放业务写入。

## 12. 启动方式和健康检查

```powershell
# 推荐：读取 .env 中 HOST/PORT，明确指定 Windows 兼容事件循环。
uv run python -m app --reload

# 旧式命令也保留，HOST/PORT 在这里需要 CLI 参数，而非应用配置。
uv run uvicorn app.main:app --reload

# Windows 上不带 reload 的 Uvicorn CLI：显式指定兼容 loop。
uv run uvicorn app.main:app --loop app.core.event_loop:loop_factory --no-access-log

# 生产：预先注入 APP_ENV=production、数据库等环境变量；不使用 reload。
uv sync --locked --no-dev
uv run --no-dev --locked python -m app
```

不要通过 `python app/main.py` 启动。`uvicorn` CLI 的 `--host` / `--port`
属于服务器参数，不会自动读取 Settings 中的 `HOST` / `PORT`。
Windows 的 psycopg 不兼容 Proactor；不要只测 live 就认定异步数据库可用。

| 接口 | 含义 | 数据库失败时 |
| --- | --- | --- |
| `GET /health/live` | HTTP 进程可响应，不获取数据库 Session | 200 |
| `GET /health/ready` | `SELECT 1` 且目标 Schema 存在并有 `USAGE` 权限 | 503 |

ready 不代表所有表、迁移版本、业务权限均已正确，也不代替真实业务监控。
ready 返回固定响应，不输出数据库地址或异常详情。

## 13. 日志与异常、请求 ID 与请求体限制

`app/core/logging.py`：

- 开发环境输出可读文本，生产环境输出 UTC 时间戳的 JSON。
- `SafeFormatter` 替换消息中出现的 `DB_PASSWORD` 字面量（基础保护，
  不意味着任何 Token / API Key 都会被自动识别）。
- 每条日志都带 `request_id` 字段（详见下方中间件），便于把响应与日志对齐。
- 默认关闭 Uvicorn access log，避免未来 URL 查询串里的 Token 泄漏。
- 不记录异常值、源码行或局部变量，只保留异常类型、文件名、行号、函数名。

`app/core/request_id.py`：

- `RequestIdMiddleware` 优先信任上游 / 客户端的 `X-Request-ID`，
  没有则生成 32 位 hex；响应头 `X-Request-ID` 总是回写同样的值。
- ID 长度上限 64 字节，仅可见 ASCII，防止伪造超长或不可见字符污染日志。
- `current_request_id()` 在 async 上下文内任何位置都能拿到，
  业务代码可以 `logger.info("did X request_id=%s", current_request_id())`。

`app/core/body_limit.py`：

- 声明了 `Content-Length` 且超过 `MAX_REQUEST_BODY_BYTES`：直接 `413 Request body too large`，
  **完全不读取 body**。
- 没有 `Content-Length`（chunked 传输）或声明值撒谎：转发时累计**实际收到的字节数**，
  超限立即中断读取并返回 413，业务代码不会被调用。
- Content-Length 无法解析时返回 `400 Invalid Content-Length`。

`app/core/errors.py`：

- 返回 `{ "detail": "Internal server error", "error_id": "<uuid>", "request_id": "<id>" }`，
  响应头同时带 `X-Request-ID`；日志记录 `error_id` 与异常堆栈，客户端只拿到 ID。
- 这里是**中间件**而不是 `@app.exception_handler(Exception)`：后者会被 Starlette
  挂到所有用户中间件之外的 `ServerErrorMiddleware`，那里读不到 request_id（只能得到 `-`）。
- HTTPException（404 / 405 等）由 Starlette 处理成对应状态码，不会落到这里。

`app/main.py`：

- 中间件注册顺序（**最后 add 的在最外层**，请求自外向内穿过）：
  `RequestId → BodySizeLimit → UnexpectedError`。
  RequestId 放最外，它的 413 / 500 响应也能带上同一个 ID；
  UnexpectedError 放最内，保证异常回傳时还在 request_id 的 contextvar 范围内。
  改动这个顺序会让 500 响应退化成 `request_id: "-"`（见 `tests/test_app.py`）。
- 保留 FastAPI / Pydantic 的 422，不预造业务异常框架。
- 生产环境关闭 `/docs` 与 `/openapi.json`。
- lifespan 关闭时 `await engine.dispose()`，并捕获异常记录到日志。

业务新增日志也必须遵守脱敏边界：
不要因为有一个密码替换器就认为任何 Token / API Key 都会被自动识别。

### 数据库主动超时

`connect_args.options` 在 libpq 层设置：

- `statement_timeout = DB_STATEMENT_TIMEOUT_MS`（默认 30 秒）：单条 SQL 超时由 PostgreSQL 主动中止，应用不会一直挂着等返回。
- `idle_in_transaction_session_timeout = DB_IDLE_IN_TX_TIMEOUT_MS`（默认 60 秒）：打开事务后空闲太久会被 PostgreSQL 主动断开，避免应用 bug 留下长事务阻塞 vacuum 与持锁。

这两个超时不依赖应用层 `asyncio.timeout`，数据库侧生效，比应用层可靠。

## 14. 测试

```powershell
uv run pytest
```

测试是模板自带的基础设施，不是某个业务需要时才补的东西：

- 不连接真实数据库：数据库依赖被覆写成 `FakeSession`（`tests/conftest.py`），
  只实现健康检查用到的两个协程方法。
- 不读取本机 `.env`：conftest 在 import `app` 之前注入固定的测试环境变量，
  避免有人本机配置不同导致测试结果不一致。
- `tests/test_app.py` 盯住 `main.py` 的中间件顺序：注册顺序错了不会报错，
  只会让 500 响应里的 `request_id` 悄悄退化成 `-`。

新增不依赖数据库的 HTTP 行为时，优先加到这里；
需要真实 PostgreSQL 的集成测试请单独成文，不要让冒烟测试依赖外部服务。

## 15. 开发与生产差异

| 开发 | 生产 |
| --- | --- |
| 本地 `.env` | 部署平台注入配置与 Secret |
| reload，开放 `/docs` | 无 reload，关闭 `/docs` 与 OpenAPI |
| 可读文本日志 | UTC 时间戳的 JSON 标准输出日志 |
| 含教学示例 | 删除教学示例后再上线 |
| 可用迁移账号调试 | 迁移账号与运行账号分离；同一套 `DB_*` 由各进程独立注入 |
| 独立开发库 | 独立生产库，按连接预算设置 worker / 池 |

生产业务通常还需要进程托管、入口 TLS、访问控制、备份与恢复演练。
按部署平台配置，不在空模板中预装一整套运维组件。
运行时凭据不应拥有不必要的建库 / 建 Schema 权限。
数据库连接固定 UTC；业务时间使用带时区的 datetime，
展示时按业务要求转为北京时间。

以后有需求再添加：认证授权、CORS、Redis、任务队列、对象存储、审计 / 监控、容器部署。
没有 Repository 是因为当前没有复用需求；
没有 Redis / JWT / Docker 是因为它们分别属于缓存 / 身份 / 部署选择，
不是所有后端项目的必备基础。

## 16. Git 与打包

提交源码、迁移、`.env.example`、`pyproject.toml`、`uv.lock` 和文档。
不提交 `.env`、虚拟环境、缓存、日志、IDE 私人配置、`outputs/` 与 `work/`。
`.gitignore` 不会停止已经跟踪的文件；新仓库首次提交前检查 `git status`，
不要只检查忽略规则。

压缩模板时保留空 `alembic/versions/` 目录（仓库里放一个 `.gitkeep`），
不包含本机配置、虚拟环境、缓存、数据库验证资料。
Git 不保留真正空目录；从 Git 克隆后如目录不存在，先创建 `alembic/versions/` 再生成迁移。

## 17. 常用命令速查

| 目的 | 命令 |
| --- | --- |
| 安装依赖（含 dev） | `uv sync` |
| 仅安装生产依赖 | `uv sync --no-dev` |
| 运行测试 | `uv run pytest` |
| 开发启动 | `uv run python -m app --reload` |
| 替代启动 | `uv run uvicorn app.main:app --loop app.core.event_loop:loop_factory` |
| 当前数据库版本 | `uv run alembic current` |
| 本地迁移头 | `uv run alembic heads` |
| 生成候选迁移 | `uv run alembic revision --autogenerate -m "describe change"` |
| 应用迁移 | `uv run alembic upgrade head` |
| 检查模型差异 | `uv run alembic check` |

参考：[SQLAlchemy AsyncSession](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)、
[Alembic 自动生成](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)、
[psycopg Windows 异步限制](https://www.psycopg.org/psycopg3/docs/advanced/async.html)、
[Uvicorn 配置](https://www.uvicorn.org/settings/)、
[PostgreSQL 连接参数](https://www.postgresql.org/docs/17/libpq-connect.html)。