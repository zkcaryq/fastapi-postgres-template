# FastAPI 后端模板 · 完整讲解文档

> 这份文档包含项目的**全部源码**、每一层的设计理由、以及几个容易被忽略的底层机制。
> 目标是让拿到文档的人（或模型）不需要打开项目就能讲清楚它做了什么、为什么这么做。

- 项目路径：`D:/demo/backend`
- 文档生成方式：源码直接从磁盘读取，与当前代码一致
- 适合的使用方式：整份丢给 GPT，让它按章节讲解 / 挑错 / 出改造方案

---

## 0. 读这份文档的 5 个要点

1. **这不是 CRUD 脚手架，是一套"克制的基础设施"**：配置、日志、连接池、迁移、健康检查、错误处理、冒烟测试都在位，但业务代码只有一个可删的教学示例。
2. **分层是有边界的**：Service 层不知道 HTTP 的存在，Model 不知道 API 的存在，Schema 不是 ORM 对象。
3. **中间件顺序是这份代码里最容易悄悄失效的地方**，第 10.1 / 10.2 节专门解释 Starlette 的堆叠规则和由此暴露的一个真实 bug。
4. **很多注释写的是"为什么"而不是"做什么"**，那些注释是设计文档的一部分，删的时候要小心。
5. 文档最后列出了**已知限制**（第 11 节）和**值得追问的问题**（第 12 节）。

---

## 1. 项目概览

### 1.1 一句话定位

面向生产环境的精简 FastAPI 后端模板：异步 SQLAlchemy 2 + psycopg 3 + PostgreSQL + Alembic + uv，
自带一个可整组删除的教学示例，解压后改 `.env` 与项目名即可开始新项目。

### 1.2 技术栈与版本

| 组件 | 版本约束 | 作用 |
| --- | --- | --- |
| Python | `>=3.13,<3.15`（`.python-version` 固定 3.13） | 运行时 |
| uv | 锁文件驱动的包管理 | `uv sync` / `uv run` |
| FastAPI | `>=0.141.1,<1` | HTTP 路由与 OpenAPI |
| Pydantic 2 / pydantic-settings | `>=2.10,<3` | 请求校验与配置读取 |
| SQLAlchemy 2（asyncio） | `>=2.1.1,<3` | ORM 与异步 Session |
| psycopg 3（binary） | `>=3.3.6,<4` | PostgreSQL 驱动（同步 + 异步） |
| Alembic | `>=1.20,<2` | 数据库迁移 |
| uvicorn[standard] | `>=0.53,<1` | ASGI 服务器 |
| pytest + httpx（dev） | `>=9.1.1` / `>=0.28.1` | 冒烟测试 |

### 1.3 五条设计原则

| 原则 | 在代码里的体现 |
| --- | --- |
| **Fail Fast** | 配置缺失/非法在 import 阶段就报错，不带着残缺配置跑起来 |
| **不在启动时做 DDL** | 不建库、不建 Schema、不执行迁移，数据库故障由 `/health/ready` 表达 |
| **日志不泄密** | 生产 JSON 日志不含请求体、查询串、异常值、局部变量；密码会被替换 |
| **结构变更必须可审阅** | 全面禁用 `create_all()`，一切靠 Alembic revision |
| **不为假想需求做抽象** | 没有 Repository、CQRS、通用 CRUD 基类 |

### 1.4 故意不包含的东西

ruff、Redis、JWT、Docker、CORS、任务队列、对象存储、监控埋点。
理由写在 README 里：这些是真实需求出现时再加的组件，不是所有后端项目的必备基础。

---

## 2. 请求生命周期

### 2.1 分层模型

```text
HTTP 请求
   │
   ▼
ASGI 服务器（uvicorn）
   │
   ▼
中间件栈（自外向内）
   │   RequestIdMiddleware      → 生成/透传 X-Request-ID，写入 contextvar
   │   BodySizeLimitMiddleware  → 请求体大小闸（Content-Length + 实际字节计数）
   │   UnexpectedErrorMiddleware→ 兜底所有漏出的异常
   │   ExceptionMiddleware      → Starlette 内置，处理 HTTPException
   ▼
Router（api/routes/*）   只做：参数校验入口、依赖注入、状态码映射
   │
   ▼
Service（services/*）    业务规则 + 查询编排 + 事务边界；不 import FastAPI
   │
   ▼
Model / AsyncSession（models/*, db/session.py）
   │
   ▼
PostgreSQL
```

响应方向反过来；Pydantic Schema 横挂在 Router 两侧：
入参 Schema 负责 `extra="forbid"` 之类的校验，出参 Schema 负责白名单式地只暴露允许的列。

### 2.2 一个 POST 请求的完整路径

以 `POST /api/v1/students` 为例：

1. uvicorn 把请求交给 ASGI app；
2. `RequestIdMiddleware` 读取上游 `X-Request-ID`（或生成 32 位 hex），写入 contextvar；
3. `BodySizeLimitMiddleware` 检查 `Content-Length`，超限直接 413（不读 body）；否则转发时累计真实字节；
4. `UnexpectedErrorMiddleware` 进入等待：内侧任何异常都会被它换成带 `error_id` 的 500；
5. Starlette 路由到 `api/routes/students.py::create_student`；
6. FastAPI 用 `StuCreate` 校验 JSON：`extra="forbid"` 拒绝未知字段（含伪造主键），空白被 strip；
7. `Depends(get_db_session)` 从 `async_sessionmaker` 取一个新 Session（**不自动 commit**）；
8. Service 层 `create_student` 建对象 → `session.add()` → `await _commit(session)`；
9. 若触发唯一键冲突（SQLSTATE 23505），`_commit` 先 rollback 再转成 `DataConflict`；
10. Router 把 `DataConflict` 映射成 409；正常则把 ORM 对象交给 `response_model=StuResponse` 序列化成 201；
11. 请求结束，`get_db_session` 关闭 Session；未提交的隐式事务回滚，连接归还连接池；
12. 响应经过各中间件回到客户端，带上 `X-Request-ID`。

### 2.3 健康检查为什么分成两个

| 接口 | 做什么 | 数据库挂了 |
| --- | --- | --- |
| `GET /health/live` | 只证明进程能响应，**不注入数据库依赖** | 仍然 200 |
| `GET /health/ready` | `SELECT 1` + 确认目标 Schema 存在且有 `USAGE` | 503 |

这个分离的意义：K8s 里 live 挂会重启容器，ready 挂只是摘流量。
数据库抖动时不该无限重启整个服务。

---

## 3. 目录结构

```text
backend/
├── app/
│   ├── __init__.py                # 空文件
│   ├── __main__.py                # 统一启动入口：python -m app
│   ├── main.py                    # 应用工厂、lifespan、中间件注册顺序
│   ├── core/
│   │   ├── __init__.py            # 空文件
│   │   ├── settings.py            # pydantic-settings，Fail Fast，无默认值的 DB_SCHEMA
│   │   ├── logging.py             # 开发文本 / 生产 JSON，密钥脱敏 + request_id
│   │   ├── event_loop.py          # Windows 下 psycopg 异步兼容性
│   │   ├── request_id.py          # X-Request-ID 中间件（纯 ASGI）
│   │   ├── body_limit.py          # 请求体大小限制（纯 ASGI，含 chunked 计数）
│   │   └── errors.py              # 未捕获异常的统一 500 出口
│   ├── db/
│   │   ├── __init__.py            # 空文件
│   │   ├── base.py                # DeclarativeBase + 统一约束命名规则 + Schema 绑定
│   │   └── session.py             # AsyncEngine、连接池、Session 依赖
│   ├── models/
│   │   ├── __init__.py            # 显式注册 Model（Alembic 靠这个发现表）
│   │   └── student.py             # 教学示例 StuTable
│   ├── schemas/
│   │   ├── __init__.py            # 空文件
│   │   └── student.py             # 教学示例 Create / Update / Response
│   ├── services/
│   │   ├── __init__.py            # 空文件
│   │   └── student.py             # 教学示例：查询编排 + 事务边界 + 冲突转换
│   └── api/
│       ├── __init__.py            # 空文件
│       ├── dependencies.py        # DbSession 类型别名注入
│       ├── router.py              # /api/v1 挂载入口
│       └── routes/
│           ├── __init__.py        # 空文件
│           ├── health.py          # /health/live, /health/ready
│           └── students.py        # 教学示例 CRUD 路由
├── alembic/
│   ├── versions/
│   │   └── a2dfbfcac9f6_baseline_existing_stu_table.py   # 空迁移：登记基线，不建表
│   ├── env.py                     # 同步 Engine + NullPool，Schema 检查
│   ├── script.py.mako             # 迁移文件模板
│   └── README                     # Alembic 自带说明
├── tests/
│   ├── conftest.py                # 注入测试配置 + FakeSession 替身
│   ├── test_app.py                # main.py 的中间件接线顺序
│   ├── test_errors.py             # 通用 500 的 error_id / request_id
│   ├── test_health.py             # live / ready 及其失败分支
│   └── test_middleware.py         # 请求 ID 透传与请求体限制
├── docs/
│   └── PROJECT_WALKTHROUGH.md     # 本文档
├── .env.example                   # 必填项全部留空
├── .gitignore
├── .python-version
├── alembic.ini
├── pyproject.toml
├── README.md                      # 项目自带的使用说明（含 17 节）
└── uv.lock
```

---

## 4. 配置与工程文件

### 4.1 pyproject.toml

`[tool.uv] package = false` 表示这不是一个要发布的安装包，只是一个用 uv 管理依赖的应用。
pytest 配置直接内联在这里，没有单独的 pytest.ini。
#### `pyproject.toml`

`pyproject.toml`

```toml
[project]
name = "fastapi-backend"
version = "0.1.0"
description = "含分层教学示例的精简 FastAPI 后端模板"
readme = "README.md"
requires-python = ">=3.13,<3.15"
dependencies = [
    "alembic>=1.20,<2",
    "fastapi>=0.141.1,<1",
    "pydantic-settings>=2.10,<3",
    "psycopg[binary]>=3.3.6,<4",
    "sqlalchemy[asyncio]>=2.1.1,<3",
    "uvicorn[standard]>=0.53,<1",
]

[tool.uv]
package = false

# 测试不连接真实数据库：通过依赖覆盖注入替身 Session。
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --strict-markers"
pythonpath = ["."]

[dependency-groups]
dev = [
    "httpx>=0.28.1",
    "pytest>=9.1.1",
]
```

### 4.2 `.python-version`

```
3.13
```

uv 依据它决定虚拟环境的 Python 版本；配合 `requires-python = ">=3.13,<3.15"` 形成双重约束。

### 4.3 `.gitignore`

值得注意的两条：`.env.*` 加 `!.env.example`（白名单例外写法），以及 `.idea/`、`.vscode/` 都被排除——
模板不假设团队用同一个 IDE。


`.gitignore`

```gitignore
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/
.env
.env.*
!.env.example
*.log
.idea/
.vscode/
dist/
build/
*.egg-info/
outputs/
work/
```

### 4.4 `.env.example`

三条关键约定：

- 空的必填项（`DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_SCHEMA`）**没有任何替你兜底的默认值**；
- `DB_SCHEMA` 必须指向一个你和 DBA 已经建好的 Schema，模板不创建；
- `DB_SSLMODE` 默认 `prefer`，注释明确提醒"prefer 不强制加密，require 也不等于校验服务器身份"。


`.env.example`

```dotenv
# 复制为 .env；空的必填项必须由你填写。不要复制学习项目的数据库配置。
APP_NAME=FastAPI Backend
APP_ENV=development
DEBUG=false
HOST=127.0.0.1
PORT=8000

DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=
DB_USER=
DB_PASSWORD=
# 必填：填写你已经创建并获得权限的 Schema；模板不负责创建数据库或 Schema。
DB_SCHEMA=

# 按 PostgreSQL/RDS 的实际 TLS 设置配置；生产推荐 verify-full 并配置 CA 路径。
DB_SSLMODE=prefer
# DB_SSLROOTCERT=D:/certs/database-ca.pem
DB_CONNECT_TIMEOUT=5
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
DB_POOL_TIMEOUT=10
DB_STATEMENT_TIMEOUT_MS=30000
DB_IDLE_IN_TX_TIMEOUT_MS=60000
HEALTH_TIMEOUT=5
MAX_REQUEST_BODY_BYTES=1048576
```

### 4.5 `alembic.ini`

刻意极简：只声明脚本位置和 sys.path，不在这里写数据库 URL——URL 由 `alembic/env.py` 从 Settings 拼出来，
避免凭据在两个地方重复。


`alembic.ini`

```ini
[alembic]
script_location = %(here)s/alembic
prepend_sys_path = %(here)s
path_separator = os
```
#### `alembic/script.py.mako` — 生成迁移文件时用的模板

`alembic/script.py.mako`

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}
revision: str = ${repr(up_revision)}
down_revision: str | Sequence[str] | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

---

## 5. 应用骨架

### 5.1 `app/__main__.py` — 启动入口

模板推荐 `python -m app` 而不是 `uvicorn` CLI，原因有二：

1. CLI 的 `--host/--port` 不会读 `.env` 里的 `HOST`/`PORT`，两个世界的配置会打架；
2. Windows 上 psycopg 的异步实现和 Proactor 事件循环不兼容，需要显式指定 loop 工厂。


`app/__main__.py`

```python
import argparse

import uvicorn

from app.core.settings import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 FastAPI，读取 HOST/PORT 并兼容 Windows")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if args.reload and settings.APP_ENV == "production":
        parser.error("生产环境禁止 --reload")
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=args.reload,
        loop="app.core.event_loop:loop_factory",
        access_log=False,
    )


if __name__ == "__main__":
    main()
```

### 5.2 `app/main.py` — 应用与中间件顺序

三句话概括：

- **lifespan 什么都不建**：不建库、不建 Schema、不跑迁移；关闭时 `await engine.dispose()` 释放连接池。
- **debug 永远 False**：`DEBUG` 只控制日志级别，绝不给客户端看 Starlette 的 traceback。
- **中间件注册顺序是这份文件里最脆弱的一处**，第 10.1 节专门解释。


`app/main.py`

```python
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.api.routes.health import router as health_router
from app.core.body_limit import BodySizeLimitMiddleware
from app.core.errors import UnexpectedErrorMiddleware
from app.core.logging import configure_logging
from app.core.request_id import RequestIdMiddleware
from app.core.settings import get_settings
from app.db.session import engine

settings = get_settings()
configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 不在启动时建库、建 Schema、建表或执行迁移；数据库故障由 ready 表达。
    # 启动读取配置会 fail fast，但建连接是惰性的，live 不依赖数据库在线。
    try:
        yield
    finally:
        # 关闭时给连接池一个有限的等待时间，避免 K8s 滚动升级时卡死。
        try:
            await engine.dispose()
        except Exception:
            logger.exception("engine dispose failed during shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    # DEBUG 仅控制内部日志；不向客户端暴露 Starlette 的调试 traceback。
    debug=False,
    lifespan=lifespan,
    docs_url=None if settings.APP_ENV == "production" else "/docs",
    redoc_url=None,
    openapi_url=None if settings.APP_ENV == "production" else "/openapi.json",
)
# 中间件顺序：最后 add 的排在最外层，请求自外向内穿过。
# 外向内依次是 RequestId → BodySizeLimit → UnexpectedError：
# RequestId 最外：之后所有日志、413 和 500 响应都带上 request_id；
# UnexpectedError 最内：异常回传时仍在 RequestId 的 contextvar 范围内，
# 若用 @app.exception_handler(Exception) 注册，处理器会落到最外层 ServerErrorMiddleware，
# 那里读到的 request_id 只会是 '-'。
app.add_middleware(UnexpectedErrorMiddleware)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.MAX_REQUEST_BODY_BYTES)
app.add_middleware(RequestIdMiddleware)
app.include_router(health_router)
app.include_router(api_router)
```

### 5.3 `app/core/event_loop.py` — Windows 兼容


`app/core/event_loop.py`

```python
import asyncio
import sys


def loop_factory() -> asyncio.AbstractEventLoop:
    # psycopg 在 Windows 不支持 Proactor；工厂同时适用于 reload 和普通运行。
    # 不在 app import 时修改全局事件循环策略，避免影响宿主或测试框架。
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()
```

注意这里刻意**不在模块 import 时改全局事件循环策略**——那会污染宿主进程和测试框架。
它返回一个 loop 工厂，由 uvicorn 在启动时调用。

---

## 6. core 层

### 6.1 `settings.py` — Fail Fast 的配置

这是全项目最值得细读的文件之一。它的每一个字段几乎都带"为什么"：

- `frozen=True` + `lru_cache` 让配置不可变且进程内复用；
- `hide_input_in_errors=True`：配置报错时不把已填的值（含密码）打印出来；
- `DB_PASSWORD: SecretStr` 不是语法糖，`logging` 层会拿它做脱敏；
- `DB_SCHEMA` 用正则 `^[a-z_][a-z0-9_]{0,62}$` 约束为普通小写标识符，并且**显式校验不是 `pg_` 前缀 / `information_schema`**；
- `model_validator` 禁止生产环境开 DEBUG；
- `database_url` 用 SQLAlchemy 的 `URL.create()` 拼，正确处理密码里的 `@` `:` `%`，而不是字符串拼接；
- `connect_args.options` 里塞了四个 PostgreSQL 启动参数——这是本文件最有价值的部分，见代码注释。


`app/core/settings.py`

```python
"""配置只负责读取与校验，不创建数据库连接。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # 环境变量优先于 .env；固定项目根路径，避免从其他目录启动时误读配置。
    # 隐藏校验错误中的输入值，避免配置错误时连带打印密码。
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        hide_input_in_errors=True,
        frozen=True,
    )

    APP_NAME: str = Field(default="FastAPI Backend", min_length=1)
    APP_ENV: Literal["development", "testing", "production"] = "development"
    DEBUG: bool = False
    HOST: str = "127.0.0.1"
    PORT: int = Field(default=8000, ge=1, le=65535)

    DB_HOST: str = Field(min_length=1)
    DB_PORT: int = Field(default=5432, ge=1, le=65535)
    DB_NAME: str = Field(min_length=1)
    DB_USER: str = Field(min_length=1)
    DB_PASSWORD: SecretStr
    # 约束为普通小写标识符，减少 SQL 引号、大小写与工具兼容性差异。
    # 这不是默认值：缺失时直接阻止启动，不隐式回退到其他 Schema。
    DB_SCHEMA: str = Field(pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    DB_SSLMODE: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = (
        "prefer"
    )
    DB_SSLROOTCERT: Path | None = None
    DB_CONNECT_TIMEOUT: int = Field(default=5, ge=1, le=60)
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=100)
    DB_MAX_OVERFLOW: int = Field(default=5, ge=0, le=100)
    DB_POOL_TIMEOUT: float = Field(default=10, gt=0, le=120)
    # 单条 SQL 超过此秒数由数据库主动中止，避免慢查询把连接占满。
    DB_STATEMENT_TIMEOUT_MS: int = Field(default=30_000, ge=1_000, le=600_000)
    # 事务打开后空闲超过此秒数由数据库主动中止，避免应用 bug 留下长事务阻塞 vacuum / 持有锁。
    DB_IDLE_IN_TX_TIMEOUT_MS: int = Field(default=60_000, ge=1_000, le=600_000)
    HEALTH_TIMEOUT: float = Field(default=5, gt=0, le=60)
    # 任何 HTTP 请求体超过此字节数直接 413；防止恶意大 body 占内存。
    MAX_REQUEST_BODY_BYTES: int = Field(default=1_048_576, ge=1_024, le=33_554_432)

    @field_validator("DB_PASSWORD")
    @classmethod
    def nonempty_password(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("DB_PASSWORD 不能为空")
        return value

    @field_validator("DB_SCHEMA")
    @classmethod
    def application_schema(cls, value: str) -> str:
        if value.startswith("pg_") or value == "information_schema":
            raise ValueError("不能使用 PostgreSQL 系统 Schema")
        return value

    @field_validator("DB_HOST", "DB_NAME", "DB_USER", "APP_NAME", "HOST")
    @classmethod
    def nonblank_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("配置不能仅包含空白")
        return value

    @model_validator(mode="after")
    def production_debug(self) -> "Settings":
        if self.APP_ENV == "production" and self.DEBUG:
            raise ValueError("生产环境不能开启 DEBUG")
        return self

    @property
    def database_url(self) -> URL:
        # URL 对象正确处理密码中的 @、:、% 等字符；不要把完整 URL 打印到日志。
        return URL.create(
            "postgresql+psycopg",
            username=self.DB_USER,
            password=self.DB_PASSWORD.get_secret_value(),
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        )

    @property
    def connect_args(self) -> dict[str, str | int]:
        args: dict[str, str | int] = {
            "connect_timeout": self.DB_CONNECT_TIMEOUT,
            "sslmode": self.DB_SSLMODE,
            # 表通过 metadata 显式限定 Schema。固定系统查找路径，避免账号的
            # search_path 改变反射结果，或无 Schema SQL 意外访问其他业务表。
            # 同时设置 statement_timeout / idle_in_transaction_session_timeout，
            # 让数据库主动中止失控 SQL 与长事务，不依赖应用层超时。
            "options": (
                "-csearch_path=pg_catalog "
                "-ctimezone=UTC "
                f"-cstatement_timeout={self.DB_STATEMENT_TIMEOUT_MS} "
                f"-cidle_in_transaction_session_timeout={self.DB_IDLE_IN_TX_TIMEOUT_MS}"
            ),
        }
        if self.DB_SSLROOTCERT is not None:
            args["sslrootcert"] = str(self.DB_SSLROOTCERT)
        return args


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 同一进程复用配置；应用与迁移各自在自己的进程中读取。
    return Settings()
```

#### 为什么把超时放到连接参数里

`statement_timeout` 与 `idle_in_transaction_session_timeout` 在 libpq 层下发，
由**数据库服务端**执行。相比应用层 `asyncio.timeout`：

- 不会在客户端超时后把慢查询留在服务端继续跑；
- 不受 Python GIL / 事件循环调度影响；
- 长事务超时能防止应用 bug 留下占锁事务，阻塞 vacuum。

`search_path=pg_catalog` 同样重要：把默认搜索路径钉死在系统 Schema，
所有业务表必须由 Model 的 `metadata.schema` 显式限定，避免出现"账号默认 Schema 不同 → 反射出来不同的表"。

### 6.2 `logging.py` — 带脱敏和 request_id 的日志


`app/core/logging.py`

```python
"""标准库日志：开发可读、生产 JSON；不记录请求体、查询串或原始异常文本。"""

import json
import logging
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

from app.core.request_id import current_request_id
from app.core.settings import get_settings


class SafeFormatter(logging.Formatter):
    def __init__(self, secrets: tuple[str, ...], json_output: bool) -> None:
        super().__init__()
        # 密钥在配置时采集一次，避免每条日志重复读取配置和做空值替换。
        self._secrets = tuple(item for item in secrets if item)
        self._json_output = json_output

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        # 基础保护不等于万能脱敏；业务代码仍禁止记录 Token、请求体和配置对象。
        for secret in self._secrets:
            if secret in message:
                message = message.replace(secret, "[REDACTED]")
        data = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "request_id": current_request_id(),
        }
        if record.exc_info:
            exc_type, _, tb = record.exc_info
            data["exception_type"] = exc_type.__name__ if exc_type else "unknown"
            # 保留定位信息，但不包含异常值、源码行或局部变量，避免泄露 SQL 参数。
            data["frames"] = "; ".join(
                f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                for frame in traceback.extract_tb(tb)
            )
        if self._json_output:
            return json.dumps(data, ensure_ascii=False)
        return " | ".join(f"{key}={value}" for key, value in data.items())


def configure_logging() -> None:
    settings = get_settings()
    formatter = SafeFormatter(
        secrets=(settings.DB_PASSWORD.get_secret_value(),),
        json_output=settings.APP_ENV == "production",
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "sqlalchemy", "alembic"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
        logger.setLevel(logging.WARNING if name == "sqlalchemy" else logging.INFO)
    # Uvicorn 默认 access log 含完整查询串；模板默认关闭，避免未来 Token 泄漏。
    logging.getLogger("uvicorn.access").disabled = True
```

三个容易被忽略的细节：

1. **密钥在 `configure_logging()` 时采集一次**，不是每条日志都去读配置和做 `str.replace`——高频日志下这是真实开销；
2. 异常只保留类型 + 文件名/行号/函数名，**不记录异常值、源码行和局部变量**，因为它们常常带着 SQL 参数值；
3. `uvicorn.access` 被整体禁用：默认 access log 打完整 URL，未来任何人往查询串塞 Token 都会泄密。
   代价是失去访问日志（第 9 节列为待办）。

### 6.3 `request_id.py` — 请求 ID 中间件（纯 ASGI）


`app/core/request_id.py`

```python
"""请求 ID：让客户端报错时可以关联到具体一条日志。

生产环境里客户端经常只看到"500 错误，请联系管理员"。
把 ID 同时写进响应头 X-Request-ID 与每条日志，运维只需要这一个 ID 就能 grep 到完整调用链。

实现为纯 ASGI 中间件，不继承 BaseHTTPMiddleware：后者会新建 Task 并多一次消息通道往返，
对 SSE / WebSocket / BackgroundTask 也有边缘行为差异。纯 ASGI 只在 ASGI 消息层面工作，
不碰 FastAPI 内部结构，也不需要 Starlette 的 Request / Response 对象。
"""

import contextvars
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_ENCODED_HEADER = REQUEST_ID_HEADER.lower().encode("latin-1")

# ContextVar 在 async 上下文自动传递；中途切换线程/任务也不会丢。
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


def current_request_id() -> str:
    """读取当前请求的 ID；非请求上下文返回 '-'。"""
    return _request_id_var.get()


def set_request_id(value: str) -> None:
    _request_id_var.set(value)


def reset_request_id(token: contextvars.Token[str]) -> None:
    _request_id_var.reset(token)


class RequestIdMiddleware:
    """优先信任上游网关 / 客户端传入的 X-Request-ID，便于跨服务串联。

    没有或不可信则生成 32 位 hex；响应总是回写同一个值。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # 非 HTTP（lifespan / websocket）没有响应头可写，原样透传。
            await self.app(scope, receive, send)
            return

        incoming = _header(scope.get("headers"), _ENCODED_HEADER)
        rid = incoming if _is_trusted(incoming) else uuid.uuid4().hex
        token = _request_id_var.set(rid)
        try:
            await self.app(scope, receive, _patch_response(send, rid))
        finally:
            _request_id_var.reset(token)


def _patch_response(send: Send, rid: str) -> Send:
    async def send_wrapper(message: Message) -> None:
        if message["type"] == "http.response.start":
            # 应用可能自己写过 X-Request-ID；已有同名头时不覆盖。
            keys = {bytes(key).lower() for key, _ in message.get("headers") or ()}
            if _ENCODED_HEADER not in keys:
                message["headers"] = [
                    *(message.get("headers") or []),
                    (REQUEST_ID_HEADER.encode("latin-1"), rid.encode("latin-1")),
                ]
        await send(message)

    return send_wrapper


def _header(headers, wanted: bytes) -> str:
    if not headers:
        return ""
    for key, value in headers:
        if bytes(key).lower() == wanted:
            return value.decode("latin-1")
    return ""


def _is_trusted(value: str) -> bool:
    """防止上游伪造超长或非 ASCII 字符撑爆日志；最多保留 64 字节可见 ASCII。"""
    if not value or len(value) > 64:
        return False
    # 仅可见 ASCII；中文 / 控制字符 / 不可见字符一律丢弃后重新生成。
    return all(0x21 <= ord(char) <= 0x7E for char in value)
```

要点：

- **纯 ASGI 实现**，没有继承 `BaseHTTPMiddleware`。后者会新建 Task 并多一次消息通道往返，对 SSE / WebSocket / BackgroundTask 有边缘行为差异。
- 上游传入的 ID 会先被 `_is_trusted()` 过滤：超过 64 字节或含非可见 ASCII 就丢弃并重新生成，防止日志被伪造 ID 污染。
- `http.response.start` 阶段才追加响应头，而且**如果应用已经自己写了同名头就不覆盖**。
- 非 HTTP scope（lifespan / websocket）原样透传，因为它们没有响应头可写。

### 6.4 `body_limit.py` — 请求体大小限制（含 chunked 计数）


`app/core/body_limit.py`

```python
"""请求体大小限制：把过大的请求挡在业务代码之前，防止占满内存。

两道闸：
1. 声明了 Content-Length 且超过上限：直接 413，**完全不读取 body**，也不反序列化。
2. 没有 Content-Length（chunked 传输）或 Content-Length 撒谎：转发时累计实际字节数，
   超限立刻中断转发并返回 413，业务代码不会被调用、payload 不会进对象。

实现为纯 ASGI 中间件：只在 ASGI 消息层面统计字节，不构造 Request 对象，
不缓冲完整 body，也不依赖具体的 ASGI 服务器。
"""

from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _BodyTooLarge(Exception):
    """内部信号：转发 body 时超过上限，用于中断下游。"""


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _content_length(scope.get("headers"))
        if declared is None:
            await self._respond(400, {"detail": "Invalid Content-Length"}, scope, receive, send)
            return
        if declared > self.max_bytes:
            await self._reject(scope, receive, send)
            return

        seen = 0
        started = False

        async def counting_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body") or b"")
                if seen > self.max_bytes:
                    # 从 receive 侧中断：下游的请求读取会直接结束，
                    # 既不把剩余 payload 读进内存，也不会走到业务代码。
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            if started:
                # 流式响应已经开始，状态码无法再改；交给外层处理而不是伪造 413。
                raise
            await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._respond(
            413, {"detail": "Request body too large"}, scope, receive, send
        )

    async def _respond(
        self, status: int, payload: dict[str, str], scope: Scope, receive: Receive, send: Send
    ) -> None:
        response: Response = JSONResponse(payload, status_code=status)
        await response(scope, receive, send)


def _content_length(headers) -> int | None:
    """返回声明的请求体长度；没有该头返回 0（无 body），解析失败返回 None。"""
    if not headers:
        return 0
    for key, value in headers:
        if bytes(key).lower() == b"content-length":
            try:
                return int(value.decode("latin-1"))
            except ValueError:
                return None
    # 没有 Content-Length 时无法预判大小：交给转发阶段的字节计数。
    return 0
```

这里堵的是一个真实的安全缺口：只检查 `Content-Length` 的话，
`Transfer-Encoding: chunked` 的请求根本没有这个头，可以无限推送数据。

实现思路：

1. 声明了长度且超限 → 直接 413，**一个字节都不读**；
2. 长度造假或没声明 → 转发时累计**实际收到的字节**，超限从 `receive` 侧抛内部异常中断下游；
3. 关键收益：业务代码不会被调用，payload 也不会被读进 Python 对象；
4. 流式响应已经开始（`started=True`）时状态码改不了，此时选择**原样抛出**而不是伪造一个 413。

### 6.5 `errors.py` — 为什么不用 `@app.exception_handler(Exception)`


`app/core/errors.py`

```python
"""未捕获异常的统一出口：给客户端一个可追踪、但不泄密的 500 响应。

这里不用 @app.exception_handler(Exception)，因为 Starlette 会把 Exception 处理器
挂到 ServerErrorMiddleware——它在所有用户中间件的最外层，
拿不到 RequestIdMiddleware 设置的 request_id contextvar（实测只能读到 '-'）。
改成中间件后，只要它比 RequestIdMiddleware 更靠内层，500 响应里就有正确的 request_id。

HTTPException 由 Starlette 的 ExceptionMiddleware 处理成对应状态码，不会传播到这里；
能到达这里的都是真正的意外错误。
"""

import logging
import uuid

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_id import REQUEST_ID_HEADER, current_request_id

logger = logging.getLogger(__name__)


class UnexpectedErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:  # 捕获所有异常本来就是这里的目的。
            if started:
                # 响应已经开始，状态码改不了；交给外层，不要伪造一个 500。
                raise
            await error_response(scope, receive, send, exc)


async def error_response(
    scope: Scope, receive: Receive, send: Send, exc: Exception
) -> None:
    """响应里同时返回 error_id 与 request_id：error_id 是这一次的 UUID，
    request_id 与响应头 X-Request-ID 一致，便于客户端与日志双向关联。
    """
    rid = current_request_id()
    error_id = uuid.uuid4().hex
    logger.error(
        "unhandled_error request_id=%s error_id=%s method=%s path=%s",
        rid,
        error_id,
        scope.get("method"),
        scope.get("path"),
        exc_info=exc,
    )
    response = JSONResponse(
        {"detail": "Internal server error", "error_id": error_id, "request_id": rid},
        status_code=500,
        headers={REQUEST_ID_HEADER: rid},
    )
    await response(scope, receive, send)
```

**这个文件存在的理由是 10.2 节那个 bug。** 简述：用 `@app.exception_handler(Exception)` 注册处理器，
Starlette 会把它放到 `ServerErrorMiddleware`——那是最外层、在所有用户中间件**之外**，
于是 `current_request_id()` 只能读到默认值 `-`，500 响应完全失去可追踪性。
改成最内层的中间件后，异常回传时还在 request_id 的 contextvar 范围内。

另外，`HTTPException`（404/405 等）由 Starlette 的 ExceptionMiddleware 处理成对应状态码，
不会传播到这里，所以这里不用担心"吞掉"正常的状态码。

---

## 7. 数据访问层

### 7.1 `db/base.py` — Base 与命名约定


`app/db/base.py`

```python
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from app.core.settings import get_settings

# 多字段约束使用所有字段，避免只取第一列造成名称碰撞。
# CheckConstraint 必须显式提供 name，尤其是直接写 SQL 字符串时。
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    # 所有 Model 继承同一 Base，自动继承用户指定的 Schema。
    # 不使用 create_all：结构变更必须有可审阅、可追踪的 Alembic 迁移。
    metadata = MetaData(
        schema=get_settings().DB_SCHEMA,
        naming_convention=NAMING_CONVENTION,
    )
```

`naming_convention` 不是装饰：没有它，跨数据库迁移时约束名会不可预测，
`alembic downgrade` 很可能因为找不到名字而失败。
`%(column_0_N_name)s` 是多字段约束的写法，避免只取第一列造成名称碰撞。

注意 `metadata` 在**类定义时**就读取了 `get_settings().DB_SCHEMA`：
这意味着 Schema 名在 import 阶段固定，改 `DB_SCHEMA` 不会“自动”带着表搬家。

### 7.2 `db/session.py` — Engine、连接池、Session


`app/db/session.py`

```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import get_settings

settings = get_settings()

# Engine 管理连接池，不是一条连接；每进程共享，连接按需建立。
# 多 worker 的连接上限 = worker 数 × (pool_size + max_overflow)。
# 不随意设置 pool_recycle：只有代理/防火墙有明确空闲断连要求时再配置。
engine = create_async_engine(
    settings.database_url,
    connect_args=settings.connect_args,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    echo=False,
    hide_parameters=True,
)

session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    # Session 有事务状态，不能跨请求或并发任务共享。async I/O 让数据库等待
    # 不阻塞其他请求，但不会自动让 SQL 变快，也不适合直接运行阻塞型计算。
    async with session_factory() as session:
        # Service 明确 commit；依赖只清理。关闭时未提交的事务会回滚。
        # flush：发送 SQL，仍可回滚；commit：提交事务。
        # rollback：放弃事务，恢复失败后的会话；refresh：重新查询对象属性。
        yield session
```

几个判断：

- `create_async_engine` 在 import 时不建连接，连接池按需增长；
- `pool_pre_ping=True` 能发现失效的闲置连接，但**不具备事务重放能力**；
- `expire_on_commit=False`：异步 Session 下这是必须的，否则 commit 后访问属性会触发隐式 IO（在 async 语境里会抛错）；
- `autoflush=False`：让"什么时候发 SQL"变成显式可控的；
- 依赖 `get_db_session` 只负责创建和清理，**绝不自动 commit**——事务边界属于 Service 层。

连接预算公式：`进程数 × (DB_POOL_SIZE + DB_MAX_OVERFLOW)`，还要给迁移、运维和其他服务留余量。

### 7.3 `api/dependencies.py` — 一个类型别名就够了


`app/api/dependencies.py`

```python
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session

# 路由只声明依赖；不让 Service 依赖 FastAPI 的 Depends 或 HTTPException。
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
```

### 7.4 教学示例：Model / Schema / Service / Router

下面这一组是可以整组删除的示例代码，价值在于演示"每一列怎么从数据库走到 HTTP"。

#### `models/__init__.py` — 显式注册


`app/models/__init__.py`

```python
from app.models.student import StuTable

# 显式 import 才能让 Base.metadata 看到这张表；Alembic 也通过这个包发现表。
__all__ = ["StuTable"]
```

Alembic 是靠 `import app.models` 发现表的，**不会扫描文件系统**。忘了在这里 import，表就不会出现在 metadata 里，
而 `alembic/env.py` 的 `reject_empty_metadata` 就是为这个场景准备的护栏。
#### `app/models/student.py` — 教学示例 Model

`app/models/student.py`

```python
"""教学示例：照搬学习项目里 test.stu_table 的真实列。

已经按 PostgreSQL 实际列定义对齐：字段注释 / 唯一约束 / 是否可空 / 长度。
alembic check 在该模型下应报告"无差异"，方便后面用 stamp head 把库打上迁移基线。
"""

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StuTable(Base):
    __tablename__ = "stu_table"
    # 表级注释与数据库一致；增删字段时这里也要同步改。
    __table_args__ = {"comment": "学生基本信息表"}

    # bigint 主键 NOT NULL；PostgreSQL 默认 GENERATED BY DEFAULT AS IDENTITY 自增。
    # 这一列在数据库里就是 IDENTITY，不再写 SERIAL/BIGSERIAL。
    stu_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="学生信息主键ID",
    )

    # 学号：32 位变长字符串，NOT NULL + UNIQUE（DB 上是 uq_stu_table_stu_number）。
    # 唯一约束的命名由 Base 中的统一命名规则生成；不需要再传 name=。
    stu_number: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, comment="学生学号"
    )

    # 姓名：必填，不唯一。
    stu_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="学生姓名"
    )

    # 班级 / 专业 / 学院：可空字符串。学生尚未分班时允许 NULL。
    stu_class: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="学生班级"
    )
    stu_major: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="学生专业"
    )
    stu_college: Mapped[str | None] = mapped_column(
        String(150), nullable=True, comment="学生学院"
    )

    # 联系方式：电话 32 位足够国际区号；邮箱限 255 字符；地址限 255 字符。
    stu_phone: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="学生手机号"
    )
    stu_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="学生邮箱"
    )
    stu_address: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="学生地址"
    )
```
#### `app/schemas/student.py` — 教学示例 Schema

`app/schemas/student.py`

```python
"""API 输入/输出：照搬 stu_table 的列；不是数据库表，不继承 ORM Base。"""

from pydantic import BaseModel, ConfigDict, Field


class StuCreate(BaseModel):
    # 不允许带外键创建请求里出现；客户端不该自己造主键。
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    stu_number: str = Field(min_length=1, max_length=32)
    stu_name: str = Field(min_length=1, max_length=100)
    stu_class: str | None = Field(default=None, max_length=100)
    stu_major: str | None = Field(default=None, max_length=100)
    stu_college: str | None = Field(default=None, max_length=150)
    stu_phone: str | None = Field(default=None, max_length=32)
    stu_email: str | None = Field(default=None, max_length=255)
    stu_address: str | None = Field(default=None, max_length=255)


class StuUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # PATCH：未传字段表示不动；显式 null 表示把数据库字段改成 NULL。
    # 学号与姓名如果允许 null，业务规则会冲突，请在 Router/Service 层拒绝。
    stu_number: str | None = Field(default=None, min_length=1, max_length=32)
    stu_name: str | None = Field(default=None, min_length=1, max_length=100)
    stu_class: str | None = Field(default=None, max_length=100)
    stu_major: str | None = Field(default=None, max_length=100)
    stu_college: str | None = Field(default=None, max_length=150)
    stu_phone: str | None = Field(default=None, max_length=32)
    stu_email: str | None = Field(default=None, max_length=255)
    stu_address: str | None = Field(default=None, max_length=255)


class StuResponse(BaseModel):
    # from_attributes=True 允许直接拿 ORM 对象构造响应；
    # 只在这里出现的字段才会被序列化，避免把内部属性意外暴露给客户端。
    model_config = ConfigDict(from_attributes=True)

    stu_id: int
    stu_number: str
    stu_name: str
    stu_class: str | None
    stu_major: str | None
    stu_college: str | None
    stu_phone: str | None
    stu_email: str | None
    stu_address: str | None
```
#### `app/services/student.py` — 教学示例 Service

`app/services/student.py`

```python
"""示例业务层：负责查询和事务，不依赖 FastAPI 的 HTTPException / Depends。"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student import StuTable
from app.schemas.student import StuCreate, StuUpdate


class DataConflict(Exception):
    """示例写入违反数据库约束；Router 决定对应的 HTTP 状态。"""


async def _commit(session: AsyncSession) -> None:
    # commit 自带 flush；只有要中途取主键或检查约束时才单独 await flush()。
    # 一个完整业务只在明确边界提交；不要把自动 commit 放进 dependency。
    try:
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        # SQLSTATE 直接拿来判断，不解析英文错误文本，也不把数据库错误原样抛给客户端。
        if isinstance(exc, IntegrityError):
            code = getattr(exc.orig, "sqlstate", None)
            if code == "23505":
                raise DataConflict("唯一字段已存在") from exc
            if code == "23503":
                raise DataConflict("关联记录不存在或仍被引用") from exc
            if code == "23514":
                raise DataConflict("数据违反检查约束") from exc
        raise


async def create_student(session: AsyncSession, payload: StuCreate) -> StuTable:
    entity = StuTable(**payload.model_dump())
    session.add(entity)  # add 只登记对象，不是异步 I/O。
    await _commit(session)
    return entity


async def list_students(
    session: AsyncSession, offset: int = 0, limit: int = 20
) -> list[StuTable]:
    result = await session.scalars(
        select(StuTable).order_by(StuTable.stu_id).offset(offset).limit(limit)
    )
    return list(result.all())


async def get_student(session: AsyncSession, stu_id: int) -> StuTable | None:
    return await session.get(StuTable, stu_id)


async def update_student(
    session: AsyncSession, stu_id: int, payload: StuUpdate
) -> StuTable | None:
    entity = await session.get(StuTable, stu_id)
    if entity is None:
        return None
    # exclude_unset 区分“未传”与“显式 null”。
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entity, field, value)
    await _commit(session)
    return entity


async def delete_student(session: AsyncSession, stu_id: int) -> bool:
    entity = await session.get(StuTable, stu_id)
    if entity is None:
        return False
    await session.delete(entity)
    await _commit(session)
    return True
```
#### `app/api/routes/students.py` — 教学示例 Router

`app/api/routes/students.py`

```python
"""示例路由：仅处理 HTTP / 依赖注入 / 状态码；SQL 与事务在 Service 层。"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Response

from app.api.dependencies import DbSession
from app.schemas.student import StuCreate, StuResponse, StuUpdate
from app.services import student as service

router = APIRouter(tags=["stu_table"])
StuId = Annotated[int, Path(gt=0)]


@router.post("/students", response_model=StuResponse, status_code=201)
async def create_student(payload: StuCreate, session: DbSession):
    try:
        return await service.create_student(session, payload)
    except service.DataConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/students", response_model=list[StuResponse])
async def list_students(
    session: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return await service.list_students(session, offset, limit)


@router.get("/students/{stu_id}", response_model=StuResponse)
async def get_student(stu_id: StuId, session: DbSession):
    entity = await service.get_student(session, stu_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="学生不存在")
    return entity


@router.patch("/students/{stu_id}", response_model=StuResponse)
async def update_student(stu_id: StuId, payload: StuUpdate, session: DbSession):
    try:
        entity = await service.update_student(session, stu_id, payload)
    except service.DataConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if entity is None:
        raise HTTPException(status_code=404, detail="学生不存在")
    return entity


@router.delete("/students/{stu_id}", status_code=204)
async def delete_student(stu_id: StuId, session: DbSession):
    if not await service.delete_student(session, stu_id):
        raise HTTPException(status_code=404, detail="学生不存在")
    return Response(status_code=204)
```
#### `app/api/router.py` — 挂载入口

`app/api/router.py`

```python
from fastapi import APIRouter

from app.api.routes.students import router as students_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(students_router)

# 新模块在这里显式注册。学生示例照搬学习项目的 stu_table，替换业务时整组删除。
```

### 7.5 `api/routes/health.py` — 健康检查


`app/api/routes/health.py`

```python
import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import DbSession
from app.core.settings import get_settings

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/live")
async def live() -> dict[str, str]:
    # 不注入数据库依赖，数据库不可用时仍然表示 HTTP 进程存活。
    return {"status": "ok"}


@router.get("/ready", response_model=None)
async def ready(session: DbSession) -> JSONResponse:
    settings = get_settings()
    try:
        # 超时包含取连接、建立连接和查询，不能让健康探针无限等待。
        async with asyncio.timeout(settings.HEALTH_TIMEOUT):
            await session.execute(text("SELECT 1"))
            accessible = await session.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace "
                    "WHERE nspname = :schema "
                    "AND has_schema_privilege(current_user, oid, 'USAGE'))"
                ),
                {"schema": settings.DB_SCHEMA},
            )
        if not accessible:
            return JSONResponse({"status": "not_ready"}, status_code=503)
    except (SQLAlchemyError, TimeoutError) as exc:
        logger.warning("readiness_failed exception_type=%s", type(exc).__name__)
        return JSONResponse({"status": "not_ready"}, status_code=503)
    return JSONResponse({"status": "ok"})
```

两个容易看懂但不容易想到的点：

- `live` **故意不注入数据库依赖**，所以它天然不会受数据库状态影响；
- `ready` 用 `asyncio.timeout` 包住整段检查（含取连接），并额外校验 `has_schema_privilege(..., 'USAGE')`——
  Schema 存在但没权限，同样应该报 503；
- 探针返回固定字典，**不含数据库地址、异常文本**，避免把拓扑信息暴露出去。

---

## 8. Alembic 迁移

### 8.1 `alembic/env.py`


`alembic/env.py`

```python
from alembic import context
from alembic.util import CommandError
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

import app.models  # 导入包才会执行各 Model 定义，注册到 metadata
from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.db.base import Base

settings = get_settings()
configure_logging()
target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    # 连接的 search_path 固定为 pg_catalog；目标 Schema 显式限定，避免 public
    # 或与账号同名的 Schema 被当作默认 Schema 后重复反射。
    if type_ == "schema":
        return name == settings.DB_SCHEMA
    if type_ == "table":
        return parent_names.get("schema_name") == settings.DB_SCHEMA
    return True


def reject_empty_metadata(migration_context, revision, directives):
    # 忘记注册 Model 时，空 metadata 可能把已有表误判为删除。
    # 只防止自动生成；手写迁移和空模板的 current / heads 不受影响。
    if getattr(context.config.cmd_opts, "autogenerate", False) and not target_metadata.tables:
        raise CommandError("没有注册 Model；请先在 app/models/__init__.py 显式导入。")


def configure(**kwargs):
    context.configure(
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        # 版本表与业务表位于同一明确指定的 Schema；不存在时不偷偷创建。
        version_table_schema=settings.DB_SCHEMA,
        compare_type=True,
        process_revision_directives=reject_empty_metadata,
        **kwargs,
    )


def run_migrations_offline():
    configure(
        url=settings.database_url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    # 独立短命令使用同步 Engine + NullPool，无须引入异步迁移复杂度。
    engine = create_engine(
        settings.database_url,
        connect_args=settings.connect_args,
        poolclass=NullPool,
        hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            if not inspect(connection).has_schema(settings.DB_SCHEMA):
                raise CommandError("目标 Schema 不存在；请先由你或 DBA 创建，再填写 DB_SCHEMA。")
            # 反射检查启动了事务；结束只读事务后，迁移才能正确拥有自己的事务。
            connection.rollback()
            configure(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

设计选择：

- **迁移用同步 Engine + NullPool**：它是短命令，没必要引入异步迁移的复杂度；
- `include_name` 限制了可见的 Schema：因为 `search_path` 被钉死在 `pg_catalog`，
  目标 Schema 必须显式指定，避免 `public` 或同名 Schema 被重复反射；
- **Schema 不存在时直接报错**，而不是"顺手帮你建一个"——权限和审计属于运维，不属于模板；
- `reject_empty_metadata`：忘了注册 Model 时，空 metadata 会把已有表判断成"要删除"，这条护栏在自动生成阶段拦住它；
- 反射检查开了一个只读事务，`connection.rollback()` 之后迁移才有属于它自己的干净事务。

### 8.2 baseline 迁移（空迁移）

#### `alembic/versions/a2dfbfcac9f6_baseline_existing_stu_table.py` — 空迁移：只在 alembic_version 里登记基线

`alembic/versions/a2dfbfcac9f6_baseline_existing_stu_table.py`

```python
"""baseline: existing stu_table

Revision ID: a2dfbfcac9f6
Revises:
Create Date: 2026-09-26 23:05:23.954551

说明：
- 这是一条空迁移。test.stu_table 由已有脚本手动建立，模板接管时不重建、不删数据。
- 升级 / 降级都是 pass；它的作用是在 alembic_version 表里登记当前数据库的迁移基线。
- 新增字段、索引、约束时再创建下一条 revision。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a2dfbfcac9f6'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
```

这条迁移什么都不做，但它是必要的：**表已经存在**（由历史脚本建的），
模板接管时不能重建也不能删数据，于是用一条空迁移把"当前状态 = 基线"记进 `alembic_version` 表。
之后的变更才逐条累加 revision。

### 8.3 标准工作流

```powershell
uv run alembic revision --autogenerate -m "describe change"   # 生成候选，需要连库
# 人工审查 upgrade / downgrade，确认没有误删 / 跨 Schema 操作
uv run alembic upgrade head
uv run alembic check                                          # 确认 Model 与库无差异
```

原则：**不在应用启动时跑迁移，不用 `create_all()` 替代版本管理，生产迁移由单一执行者在独立步骤里跑。**

---

## 9. 测试

### 9.1 为什么模板自带测试

README 里原本写着"pytest 在真实需求出现时再加"——这是不对的：
模板自己的基础设施（尤其是中间件顺序）必须有回归保护，
否则某次改动让 500 响应的 request_id 变成 `-` 时，不会有任何信号。

### 9.2 两条硬约束

- **不连真实数据库**：用 `FakeSession` 替身覆写依赖；
- **不用本机 `.env`**：conftest 在 import `app` **之前**注入测试环境变量，因为配置在 import 阶段就被读取并缓存。

#### `tests/conftest.py` — 测试配置与 FakeSession

`tests/conftest.py`

```python
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
```
#### `tests/test_app.py` — 盯住 main.py 的中间件接线

`tests/test_app.py`

```python
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
```
#### `tests/test_errors.py` — 通用 500

`tests/test_errors.py`

```python
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
```
#### `tests/test_health.py` — 健康检查所有分支

`tests/test_health.py`

```python
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
```
#### `tests/test_middleware.py` — 请求 ID 与请求体限制

`tests/test_middleware.py`

```python
"""中间件：X-Request-ID 透传与请求体大小限制（含 chunked 绕过场景）。"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.body_limit import BodySizeLimitMiddleware
from app.core.request_id import _is_trusted


def build_size_app(max_bytes: int) -> tuple[FastAPI, list[int]]:
    """返回一个记录已到达业务代码的请求体大小的 App。"""
    received: list[int] = []
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        size = len(await request.body())
        received.append(size)
        return {"size": size}

    return app, received


@pytest.mark.parametrize(
    "value",
    ["中文-request-id", "line\nbreak", "tab\there", "a" * 65, ""],
)
def test_untrusted_request_id_is_replaced(value):
    assert _is_trusted(value) is False


@pytest.mark.parametrize("value", ["abc-123", "gateway-trace-id", "a" * 64])
def test_trusted_request_id_is_preserved(value):
    assert _is_trusted(value) is True


def test_request_id_echoes_upstream_value(client):
    response = client.get("/health/live", headers={"X-Request-ID": "upstream-42"})
    assert response.headers["X-Request-ID"] == "upstream-42"


def test_request_id_is_generated_when_missing(client):
    response = client.get("/health/live")
    rid = response.headers["X-Request-ID"]
    assert len(rid) == 32
    assert int(rid, 16) >= 0  # 32 位 hex


def test_oversized_upstream_request_id_is_regenerated(client):
    response = client.get("/health/live", headers={"X-Request-ID": "x" * 200})
    assert response.headers["X-Request-ID"] != "x" * 200
    assert len(response.headers["X-Request-ID"]) == 32


def test_small_body_is_forwarded():
    app, received = build_size_app(max_bytes=256)
    response = TestClient(app).post("/echo", content=b"x" * 10)
    assert response.status_code == 200
    assert response.json() == {"size": 10}
    assert received == [10]


def test_declared_oversized_body_is_rejected_before_reading():
    app, received = build_size_app(max_bytes=256)
    response = TestClient(app).post("/echo", content=b"x" * 1024)
    assert response.status_code == 413
    # 关键：路由没被调用，body 没有被读入业务代码。
    assert received == []


def test_chunked_body_without_content_length_is_counted():
    """没有 Content-Length 的 chunked 请求必须同样受限，不能绕过。"""
    app, received = build_size_app(max_bytes=256)

    def chunks():
        for _ in range(64):
            yield b"x" * 16  # 合计 1024 字节

    response = TestClient(app).post("/echo", content=chunks())
    assert response.status_code == 413
    assert received == []


def test_invalid_content_length_is_bad_request():
    app, received = build_size_app(max_bytes=256)
    response = TestClient(app).post(
        "/echo", content=b"x" * 4, headers={"Content-Length": "not-a-number"}
    )
    assert response.status_code == 400
    assert received == []
```

运行：

```powershell
uv run pytest        # 26 个用例，无需数据库
```

---

## 10. 关键设计决策与踩过的坑

这一节是整份文档最该让讲解者展开的部分。

### 10.1 中间件注册顺序：后注册者在外层

Starlette 的 `add_middleware` 实现是 `user_middleware.insert(0, ...)`，
`build_middleware_stack()` 再 `reversed()` 迭代包壳。最终结果是：

```text
ServerErrorMiddleware        （最外层，用户不可控）
  └─ 最后 add 的用户中间件
      └─ ...
          └─ 最先 add 的用户中间件
              └─ ExceptionMiddleware   （处理 HTTPException）
                  └─ Router
```

所以本模板里 `RequestId → BodySizeLimit → UnexpectedError`（自外向内），
注册顺序却是**反着写**的：先 `UnexpectedError`，最后 `RequestId`。

### 10.2 已修复的真实 bug：500 响应丢了 request_id

原本用 `@app.exception_handler(Exception)` 注册 500 处理器。
`build_middleware_stack()` 里有一行：

```python
for key, value in self.exception_handlers.items():
    if key in (500, Exception):
        error_handler = value          # ← 被交给 ServerErrorMiddleware
```

也就是说 `Exception` 处理器被挂到**所有用户中间件之外**，
`RequestIdMiddleware` 设置的 contextvar 在那里读不到，`request_id` 恒为 `-`。

**修复**：改成最内层的 `UnexpectedErrorMiddleware`，异常回传时仍在 contextvar 范围内；
并加 `tests/test_app.py` 做回归保护。这个 bug 是通过写测试发现的，本地手工点永远不会遇到。

### 10.3 chunked 请求能绕过 Content-Length 检查

见 6.4 节。老的 `BaseHTTPMiddleware` 版本只读 `Content-Length` 头，
`Transfer-Encoding: chunked` 的请求没有这个头。新实现按实际字节计数，并从 `receive` 侧中断。

### 10.4 为什么选纯 ASGI 而不是 BaseHTTPMiddleware

| | BaseHTTPMiddleware | 纯 ASGI |
| --- | --- | --- |
| 实现成本 | 低 | 略高（要处理 raw scope/message） |
| 每次请求开销 | 多一次 Task 创建和消息通道往返 | 几乎没有额外开销 |
| 流式响应 / SSE | 有已知的缓冲与边缘问题 | 语义清晰可控 |
| BackgroundTask | 可能拿不到已清理的上下文 | contextvar 语义直观、天然有效 |

### 10.5 为什么 `DB_SCHEMA` 没有默认值

给默认值等于在背书一个隐含假设。Schema 缺失时应该让进程**立刻失败**，
而不是悄悄落到 `public` 然后在一个错误的地方写业务表。
同理，"账号默认 Schema" 也被 `search_path=pg_catalog` 屏蔽掉。

### 10.6 为什么禁掉 uvicorn access log

默认 access log 打印完整 URL（含查询串）。任何人未来把 Token 放进查询串就会泄密，
而这类泄漏在项目早期看不出来。这是"按最坏情况默认安全"的取舍。

### 10.7 为什么 `/health/live` 不能注入数据库依赖

live 挂 = 容器重启。如果 live 依赖数据库，一次数据库抖动就会触发全量重启风暴。
live 只回答"进程还能响应"；ready 才回答"能不能干业务"。

---

## 11. 已知限制与待办

| 项 | 现状 | 可选改进 |
| --- | --- | --- |
| Access log | 整体禁用 | 保留但用自定义 formatter 脱敏/截断查询串 |
| 静态检查 | 无 ruff | 加最小 ruff 配置（现在有 20+ 测试文件要维护） |
| 迁移/prisma 式数据迁移 | 只有 baseline | 按业务累加 revision |
| 认证授权 | 无 | 真实需求出现再加 |
| body_limit 流式场景 | 响应已开始时无法改成 413 | 需在入口网关层再做一层限制 |
| 教学示例 | 单表，无外键 | 若要演示关系加载，再补一张表 |

---

## 12. 值得追问的 10 个问题

拿这份文档给模型讲解时，可以用这些问题检验理解深度：

1. `add_middleware` 的注册顺序和实际执行顺序为什么相反？改错会发生什么具体现象？
2. 为什么 `@app.exception_handler(Exception)` 拿不到 contextvar？它的处理器在哪一层执行？
3. 纯 ASGI 中间件的 `receive` 为什么要自己包装？chunked 请求如何绕过 Content-Length 检查？
4. `search_path=pg_catalog` 加 `metadata.schema` 组合解决了什么问题？如果去掉会怎样？
5. 为什么 `statement_timeout` 要放在连接参数里而不是应用层 `asyncio.timeout`？
6. `expire_on_commit=False` 在异步 Session 下为什么是必须的？
7. 为什么 Session 依赖不自动 commit？事务边界放在哪一层由什么决定？
8. `IntegrityError.orig.sqlstate` 的三个码分别对应什么约束？为什么不用英文错误文本匹配？
9. live 和 ready 分离解决的是什么运维问题？反过来会怎样？
10. 为什么统一约束命名约定这种细节，会直接决定 `alembic downgrade` 能否成功？
