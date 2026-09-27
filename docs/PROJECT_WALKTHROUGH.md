# FastAPI 后端模板 · 源码级讲解文档

> 这份文档对应**当前仓库的真实源码**，不维护“曾经是什么样”的历史。
> 拿到模板后，可以按章节挑读；任何与代码不一致的描述都是 bug。

- 项目路径：`D:/fastapi_learning/fastapi-postgres-template`（即本仓库根目录）
- 适合的用法：丢给模型让它按章节讲解 / 挑错 / 给改造建议

## 0. 读这份文档的 5 个要点

1. **这是基础设施模板，不是 CRUD 脚手架**。`app/` 内不含任何业务实体；
   唯一的真实代码示例在 `examples/student_crud/`。
2. **分层有边界**。Service 不知道 HTTP，Model 不知道 API，Schema 不是 ORM 对象。
3. **Middleware Stack 是最容易悄悄失效的地方**，第 5 节专门讲。
4. **本模板承认局限**：不引入 Repository / CQRS / JWT / Redis / Docker 等可选组件。
5. **数据库权限分离是配置层面的能力，不在运行时强制**。

## 1. 项目概览

### 1.1 一句话定位

业务无关的精简 FastAPI 后端模板：FastAPI + SQLAlchemy 2 + PostgreSQL + Alembic + uv。
所有教学性代码集中在 `examples/`，新项目可以整组删除或复制。

### 1.2 技术栈

| 组件 | 版本约束 | 作用 |
| --- | --- | --- |
| Python | `>=3.13,<3.15`（`.python-version` 固定 3.13） | 运行时 |
| uv | 锁文件驱动的包管理 | `uv sync` / `uv run` |
| FastAPI | `>=0.141.1,<1` | HTTP 路由与 OpenAPI |
| Pydantic 2 / pydantic-settings | `>=2.10,<3` | 请求校验与配置读取 |
| SQLAlchemy 2（asyncio） | `>=2.1.1,<3` | ORM 与异步 Session |
| psycopg 3（binary） | `>=3.3.6,<4` | PostgreSQL 驱动 |
| Alembic | `>=1.20,<2` | 数据库迁移 |
| uvicorn[standard] | `>=0.53,<1` | ASGI 服务器 |
| pytest + httpx（dev） | `>=9.1.1` / `>=0.28.1` | 测试 |
| pytest-asyncio（dev） | `>=1.0` | 集成测试的 async 用例（`asyncio_mode = "auto"`） |
| ruff（dev） | `>=0.6,<1` | 静态检查与格式化 |

### 1.3 五条设计原则

| 原则 | 在代码里的体现 |
| --- | --- |
| **Fail Fast** | 配置缺失 / 非法在 import 阶段就报错 |
| **不在启动时做 DDL** | 不建库、不建 Schema、不执行迁移 |
| **日志不泄密** | 生产 JSON 日志不含请求体、查询串、异常值、局部变量；密码会被替换 |
| **结构变更必须可审阅** | 全面禁用 `create_all()`，一切靠 Alembic revision |
| **不为假想需求做抽象** | 没有 Repository、CQRS、通用 CRUD 基类、迁移角色强行隔离 |

### 1.4 故意不包含的东西

Ruff 之外的检查工具、Redis、JWT、OAuth、CORS、Docker、K8s YAML、Celery / RabbitMQ /
Kafka、对象存储、监控 / Sentry / OpenTelemetry、Rate Limit、Plugin System。
理由写在 README：这些是真实需求出现时再加的组件。

## 2. 请求生命周期

```text
HTTP 请求
   │
   ▼
uvicorn
   │
   ▼
RequestIdMiddleware             ← 生成/透传 X-Request-ID，写入 contextvar
UnexpectedErrorMiddleware       ← 把漏出的异常转成 500
BodySizeLimitMiddleware         ← Content-Length + 实际字节计数
ExceptionMiddleware (Starlette) ← 处理 HTTPException
   │
   ▼
Router (api/routes/*)          ← 参数校验入口、依赖注入、状态码映射
   │
   ▼
Service (services/*)           ← 业务规则 + 查询编排 + 事务边界
   │
   ▼
Model / AsyncSession            ← SQLAlchemy ORM
   │
   ▼
PostgreSQL
```

### 2.1 健康检查为什么分成两个

| 接口 | 做什么 | 数据库挂了 |
| --- | --- | --- |
| `GET /health/live` | 证明进程能响应，**不注入数据库依赖** | 仍然 200 |
| `GET /health/ready` | `SELECT 1` + 目标 Schema 有 USAGE | 503 |

K8s 里 live 挂会重启容器，ready 挂只摘流量。数据库抖动时不该无限重启。

## 3. 配置

### 3.1 Settings 字段

`app/core/settings.py` 是 pydantic-settings：

- `frozen=True` + `lru_cache`：进程内复用、不可变；
- `hide_input_in_errors=True`：配置错误时不打印输入值；
- `DB_PASSWORD: SecretStr`：不在日志里泄漏；
- `DB_SCHEMA` 用正则 `^[a-z_][a-z0-9_]{0,62}$` + 显式拒绝 `pg_*` / `information_schema`；
- `model_validator` 禁 production + DEBUG；并校验 MIGRATION_* 必须成对出现；
- `database_url` / `migration_database_url` 用 SQLAlchemy 的 `URL.create()` 拼；
- `connect_args.options` 注入 `search_path=pg_catalog` /
  `statement_timeout` / `idle_in_transaction_session_timeout`。

### 3.2 为什么 `SHUTDOWN_TIMEOUT`

关闭连接池时给一个有限的等待时间，避免 K8s 滚动升级时容器卡在 `dispose()` 上。
超时只记日志，不外抛泄密信息。

### 3.3 数据库主动超时

`connect_args.options` 在 libpq 层设置：

- `statement_timeout = DB_STATEMENT_TIMEOUT_MS`（默认 30 秒）：单条 SQL 由数据库主动中止。
- `idle_in_transaction_session_timeout = DB_IDLE_IN_TX_TIMEOUT_MS`（默认 60 秒）：
  防止应用 bug 留下长事务阻塞 vacuum。

这两个超时不依赖应用层 `asyncio.timeout`，数据库侧生效，比应用层可靠。

### 3.4 迁移账号

```python
@property
def migration_database_url(self) -> URL:
    user = self.MIGRATION_DB_USER or self.DB_USER
    password_secret = self.MIGRATION_DB_PASSWORD or self.DB_PASSWORD
    return URL.create(...)
```

- 未配置 `MIGRATION_DB_USER` / `MIGRATION_DB_PASSWORD`：回退到运行时账号（开发环境）。
- 同时配置：迁移账号必须成对出现；只给一边会被 `model_validator` 拒绝。

运行时永远用 `Settings.database_url`；Alembic 永远用 `Settings.migration_database_url`。

## 4. 日志

`app/core/logging.py` 的设计：

- 密钥在 `configure_logging()` 时采集一次，避免每条日志都重新读配置和 `str.replace`；
- 异常只保留类型 + 文件**相对路径** + 行号 + 函数名，不记录异常值 / 源码行 / 局部变量；
- 文件路径用 `_relative_frame()` 转成项目根的相对路径：
  - 在项目内：`app/services/student.py:88:update_student`；
  - 在项目外（站点包里的库）：回退到 basename，仍然不暴露本机绝对路径。
- 关闭 `uvicorn.access` 默认日志：默认会打印完整 URL，未来任何人往查询串塞 Token 都会泄密。

## 5. Middleware Stack

### 5.1 最终顺序

```text
RequestIdMiddleware              ← 最外层
  └─ UnexpectedErrorMiddleware   ← 吞下所有 Exception → 500
      └─ BodySizeLimitMiddleware  ← 自己消费 _BodyTooLarge → 413
          └─ ExceptionMiddleware (Starlette)
              └─ Router
```

`app/main.py` 注册顺序：**先 `add` 最内层，再 `add` 最外层**。
最后 `add_middleware(BodySizeLimit)` 是最内层。

### 5.2 BodySizeLimit 为什么必须放在 UnexpectedError 内部

```python
try:
    await self.app(scope, counting_receive, tracking_send)
except _BodyTooLarge:
    if started:
        raise
    await self._reject(scope, receive, send)
```

`counting_receive` 超限时抛 `_BodyTooLarge`。这个异常向上传播：

- 如果中间件顺序是 RequestId → BodySizeLimit → UnexpectedError（**错误顺序**）：
  `UnexpectedErrorMiddleware` 用 `except Exception` 把 `_BodyTooLarge` 吞掉，
  直接返回 500，业务代码没被执行但状态码错了。
- 如果中间件顺序是 RequestId → UnexpectedError → BodySizeLimit（**正确顺序**）：
  `_BodyTooLarge` 先被 `BodySizeLimitMiddleware` 自己的 `try/except` 消费，
  转成 413；`UnexpectedErrorMiddleware` 看不到这个异常。

### 5.3 Request ID 的行为

```python
def _patch_response(send: Send) -> Send:
    async def send_wrapper(message: Message) -> None:
        if message["type"] == "http.response.start":
            rid = _request_id_var.get().encode("latin-1")
            headers = [
                (key, value)
                for key, value in (message.get("headers") or [])
                if bytes(key).lower() != _ENCODED_HEADER
            ]
            headers.append((REQUEST_ID_HEADER.encode("latin-1"), rid))
            message["headers"] = headers
        await send(message)

    return send_wrapper
```

强制覆盖：无论内层有没有写过 `X-Request-ID`，外层都用 contextvar 里的值覆盖。
这保证：

```text
current_request_id()  ==  log request_id  ==  X-Request-ID  ==  error_id 里的 request_id
```

### 5.4 HTTPException 不会被吞

`HTTPException` 由 Starlette 的 ExceptionMiddleware 处理成 404 / 405 / 422 等，
不会传播到 UnexpectedError。404 仍然是 404。

### 5.5 完整 Stack 集成测试

`tests/test_middleware.py::test_stack_*` 一组用例同时验证：

- 普通请求 → 200 + X-Request-ID；
- Content-Length 超限 → 413 + X-Request-ID；
- chunked 超限 → 413 + X-Request-ID；
- 无效 Content-Length → 400 + X-Request-ID；
- 路由主动抛未知异常 → 500 + request_id 正确；
- 404 / 405 仍是 404 / 405。

不要只测试单独的 BodySizeLimit 或 UnexpectedError；单独跑得通，组合后不一定对。

## 6. 数据访问层

### 6.1 `db/base.py`

```python
class Base(DeclarativeBase):
    metadata = MetaData(
        schema=get_settings().DB_SCHEMA,
        naming_convention=NAMING_CONVENTION,
    )
```

`metadata` 在**类定义时**就读取 `get_settings().DB_SCHEMA`：
Schema 名在 import 阶段固定，改 .env 不会让已有表搬家。

`naming_convention` 不是装饰：没有它，跨数据库迁移时约束名会不可预测，
`alembic downgrade` 可能因为找不到名字而失败。

### 6.2 `db/session.py`

```python
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
```

- `expire_on_commit=False`：commit 后访问普通属性不再触发隐式数据库 IO。
  这不是“async 必须”，是“配合 async 上下文读取的推荐默认”。
- `autoflush=False`：把“什么时候发 SQL”交回给业务代码。
  **`session.add()` 之后必须显式 `await session.flush()`** 才能让同一事务
  里的后续 SELECT 看到这一写入。
- 依赖 `get_db_session` 只创建与清理，**绝不自动 commit**；事务边界属于 Service。

### 6.3 Alembic env.py

- 离线模式与在线模式都用 `Settings.migration_database_url`；
- 同步 Engine + NullPool：短命令不需要异步迁移的复杂度；
- `include_name` 限制 Schema 反射：避免 `public` 或同名 Schema 被重复反射；
- Schema 不存在直接报错；
- 空 metadata 护栏：挡住“所有 Model 都没注册”的极端情况。
  注意这只能挡这个极端，**漏注册单个 Model 时它不生效**，
  所以 autogenerate 之后必须人工 review migration。

### 6.4 PostgreSQL IDENTITY

```python
stu_id: Mapped[int] = mapped_column(
    BigInteger,
    Identity(always=False),
    primary_key=True,
    comment="学生信息主键ID",
)
```

- `Identity()` 是 SQLAlchemy 2 的明确声明，PostgreSQL 上等价于
  `GENERATED BY DEFAULT AS IDENTITY`；
- **不要写** `autoincrement=True`：那是 SQLAlchemy 1.x 的 SERIAL 习惯，
  PostgreSQL dialect 会生成 `nextval(...)`，与 IDENTITY 行为有差异；
- `tests/examples/test_student_model.py` 锁定这一行为：列必须有 `Identity`，
  且 `autoincrement is not True`；
- **真实 PostgreSQL 验证**：`tests/integration/test_alembic_lifecycle.py` 在
  真实 PG 上跑 ``alembic upgrade head``，再读 ``information_schema.columns``，
  断言主键 ``is_identity = YES`` 且 ``identity_generation = 'BY DEFAULT'``。
  单元断言 + DDL 实测双重保护。

## 7. 业务示例：`examples/student_crud/`

### 7.1 这是教学代码

- **不**在 `app/` 任何地方被自动 import；
- **不**被 `app.models.__init__.py` 注册；
- **不**进入 `Base.metadata`（除非测试主动 import）；
- **不**出现在生产路由里；
- **不**影响 pytest（schema 单独的子集测试）。

### 7.2 PATCH 语义（最容易抄错的一处）

```python
@model_validator(mode="after")
def reject_explicit_null_for_not_null_columns(self) -> "StuUpdate":
    for field in _NOT_NULL_DB_COLUMNS:
        if field in self.model_fields_set and getattr(self, field) is None:
            raise ValueError(f"字段 {field} 在数据库中为 NOT NULL，不能显式设为 null")
    return self
```

- `model_fields_set`：Pydantic v2 提供，区分“未传”与“显式 null”。
  - `{}` → `model_fields_set = set()`；
  - `{"stu_name": null}` → `model_fields_set = {"stu_name"}`。
- 校验放在 Schema 层：不让请求撞数据库变成 500。
- Service 层用 `model_dump(exclude_unset=True)` 只处理明确给出的字段。

### 7.3 错误码映射

`_commit` 把 `IntegrityError.orig.sqlstate` 映射到业务异常：

| SQLSTATE | 含义 | 业务异常 |
| --- | --- | --- |
| 23505 | 唯一约束冲突 | `DataConflict("唯一字段已存在")` |
| 23503 | 外键约束 | `DataConflict("关联记录不存在或仍被引用")` |
| 23514 | 检查约束 | `DataConflict("数据违反检查约束")` |
| 23502 | NOT NULL 违反 | `DataConflict("字段为 NOT NULL 但收到了 null")` |

SQLSTATE 是数据库的稳定错误码，不解析英文错误文本。

## 8. 测试

### 8.1 单元测试（无数据库依赖）

```text
tests/
├── conftest.py                # 注入测试配置与 FakeSession
├── test_app.py                # main.py 中间件接线 + 真实 500 行为
├── test_errors.py             # UnexpectedError + RequestId 子集
├── test_health.py             # live / ready 分支
├── test_middleware.py         # 完整 Middleware Stack 集成
├── test_settings.py           # 配置层校验（含迁移账号回退）
├── test_logging.py            # 密码脱敏 + 路径不泄露
├── test_alembic_env.py        # 空 metadata 护栏
├── test_lifespan.py           # shutdown timeout 行为（mocked，不真等 10 秒）
├── examples/                  # 教学 Example 的单元测试
│   ├── test_student_schema.py # PATCH 语义：未传 vs 显式 null
│   └── test_student_model.py  # Identity + NOT NULL 约束
└── integration/               # 真实 PostgreSQL（默认跳过）
    ├── conftest.py
    ├── _models.py             # 测试专用 ORM（独立 DeclarativeBase + 阶段化 metadata）
    ├── _alembic/              # 测试专用 alembic env
    ├── test_alembic_lifecycle.py  # revision / upgrade / downgrade / check / 增量
    ├── test_async_session.py  # autoflush / commit / rollback / statement_timeout
    ├── test_connection_params.py  # search_path / 超时参数 / idle-in-tx 真实断连
    └── test_sqlstate.py       # 23505 / 23502 / 23514 / 23503
```

### 8.2 集成测试

```powershell
INTEGRATION_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db \
  uv run pytest -m integration
```

集成测试只在 ``fastapi_template_test`` Schema 内建表并清表；
**不要指向业务数据库**，且该 Schema 必须提前存在（conftest 不自动建，
缺失时立即失败并提示，避免掩盖权限问题）。
默认 ``addopts = -m 'not integration'``，需要显式 ``-m integration`` 启用；
默认 ``uv run pytest`` 不发起任何真实数据库连接。

### 8.3 真实 PostgreSQL 验证清单

下列行为都在真实 PostgreSQL（V1.0 验证环境：PostgreSQL 17.11）上跑过：

| 验证项 | 测试位置 | 结果 |
| --- | --- | --- |
| Alembic revision --autogenerate（迁移内容非空断言） | test_alembic_lifecycle.py | PASS |
| alembic upgrade head | 同上 | PASS |
| alembic check 报告无差异 | 同上 | PASS |
| alembic downgrade -1 → upgrade head 往返 | 同上 | PASS |
| 增量迁移：第一轮 3 表 → 第二轮真实新增第 4 表 | 同上 | PASS |
| alembic_version 表位于 fastapi_template_test | 同上 | PASS |
| 生成的 revision 不落入仓库 alembic/versions/ | 同上 | PASS |
| PostgreSQL ``is_identity = YES`` | 同上 | PASS |
| PostgreSQL ``identity_generation = BY DEFAULT`` | 同上 | PASS |
| 迁移文件用 ``sa.Identity(...)`` 而非 nextval/SERIAL | 同上 | PASS |
| UNIQUE → SQLSTATE 23505 | test_sqlstate.py | PASS |
| NOT NULL → SQLSTATE 23502（绕过 Pydantic 直接写库） | 同上 | PASS |
| CHECK → SQLSTATE 23514 | 同上 | PASS |
| FK → SQLSTATE 23503 | 同上 | PASS |
| ``search_path=pg_catalog`` + ORM INSERT/SELECT | 同上 | PASS |
| SHOW search_path = pg_catalog（生产 connect_args） | test_connection_params.py | PASS |
| SHOW statement_timeout == DB_STATEMENT_TIMEOUT_MS | 同上 | PASS |
| SHOW idle_in_transaction_session_timeout == 配置值 | 同上 | PASS |
| idle-in-tx 超时真实断开空闲事务（测试专用 1s 值） | 同上 | PASS |
| AsyncSession ``add`` 不自动 flush | test_async_session.py | PASS |
| ``flush()`` 后 Identity PK 就位、同事务可见 | 同上 | PASS |
| ``commit`` 后属性不再触发隐式 IO | 同上 | PASS |
| ``rollback`` 真撤销事务（两条 INSERT 均消失） | 同上 | PASS |
| ``statement_timeout=1s`` 真取消 ``pg_sleep(2)`` | 同上 | PASS |
| 超时后 Session 能 rollback 并继续工作 | 同上 | PASS |
| 真实 App 启动 + live 200 + ready 200（真实 Schema） | 手工验证（进程级） | PASS |
| ready 503 + live 200（DB_SCHEMA 指向不存在的 Schema） | 手工验证（进程级） | PASS |
| DB 连接失败日志无密码 / 无 URL / 无 SQL 参数 | 手工验证 + test_logging.py | PASS |
| shutdown timeout 真截断（mocked，< 3 秒） | test_lifespan.py | PASS |
| 密码经 ``configure_logging`` 全链路脱敏 | test_logging.py | PASS |
| Inner X-Request-ID 被外层强制覆盖 | test_middleware.py | PASS |
| 伪造小 Content-Length + 大 body → 413 | 同上 | PASS |
| 422 不被吞成 500 | 同上 | PASS |

## 9. Alembic

### 9.1 新项目标准流程

```powershell
uv run alembic revision --autogenerate -m "initial schema"
# 人工审查 upgrade / downgrade 后再 apply
uv run alembic upgrade head
uv run alembic check
```

模板 `alembic/versions/` 初始为空（带 `.gitkeep`），不携带任何 baseline。
已有数据库接管属于特殊场景，见
[`docs/EXISTING_DATABASE_MIGRATION.md`](EXISTING_DATABASE_MIGRATION.md)。

### 9.2 空 metadata 护栏

```python
def reject_empty_metadata(*, autogenerate: bool, tables: Mapping[str, Any]) -> None:
    if autogenerate and not tables:
        raise CommandError(
            "Base.metadata 为空；autogenerate 会把已有表当作删除候选。"
            "请在 app/models/__init__.py 显式 import 目标 Model 后重试。"
        )
```

只防止 metadata **完全为空**时 autogenerate 把现有表批量判断为删除。
**漏注册单个 Model 不被拦截**，所以 autogenerate 之后必须人工 review。

另两个 review 时必看的点（都来自本轮真实验证）：

- autogenerate **无差异时不会报错**，而是生成 ``pass``/``pass`` 的空迁移。
  “文件生成了”不等于“迁移有内容”，提交前必须打开看 upgrade/downgrade。
- 生成的迁移文件名以**随机 revision hash** 开头，文件名字母序 ≠ 创建顺序；
  任何按文件名排序挑选“第 N 份迁移”的脚本都不可靠，应按
  ``down_revision`` 链或 message slug 定位。

## 10. 关键设计决策

### 10.1 Middleware 顺序：后注册者在外层

Starlette 的 `add_middleware` 实现是 `user_middleware.insert(0, ...)`，
`build_middleware_stack()` 再 `reversed()` 迭代包壳。所以：

```text
add_middleware(BodySizeLimit)   # 第一个 add → 最内层
add_middleware(UnexpectedError) # 第二个 add → 中间
add_middleware(RequestId)      # 最后一个 add → 最外层
```

最终请求方向：RequestId → UnexpectedError → BodySizeLimit → Router。

### 10.2 PATCH NOT NULL 校验

`StuUpdate` 表面上所有字段都是 `str | None`，但 `model_validator(mode="after")`
会拒绝显式 `null` 对 NOT NULL 列。Service 用 `model_dump(exclude_unset=True)`
只更新明确给出的字段。

### 10.3 为什么禁掉 uvicorn access log

默认 access log 打印完整 URL（含查询串）。任何人未来把 Token 放进查询串就会泄密，
而这类泄漏在项目早期看不出来。这是“按最坏情况默认安全”的取舍。

### 10.4 为什么 `/health/live` 不能注入数据库依赖

live 挂 = 容器重启。如果 live 依赖数据库，一次数据库抖动就会触发全量重启风暴。
live 只回答“进程还能响应”；ready 才回答“能不能干业务”。

### 10.5 为什么 search_path=pg_catalog 是默认

`search_path="$user", public` 会让账号默认 Schema 干扰业务表解析；
固定 `pg_catalog` 强迫所有业务表由 `Base.metadata.schema` 显式限定。
代价是以后用 pgvector / PostGIS / uuid-ossp 等扩展时需要确认扩展默认 Schema；
参见 README 第 6 节。

### 10.6 数据库账号分离是配置能力

模板**支持**运行时账号与迁移账号独立配置，但**不强制**。
开发环境最常用同一份账号；生产环境按需独立配置。
模板不假装已经做了权限隔离——如果没配 `MIGRATION_DB_*`，运行时与迁移
共用同一个账号。

## 11. 已知限制

| 项 | 现状 | 可选改进 |
| --- | --- | --- |
| Access log | 整体禁用 | 保留但用自定义 formatter 脱敏 / 截断查询串 |
| 静态检查 | Ruff 最小集 | 按需开更多规则 |
| 迁移 / 数据迁移 | 空 baseline | 已有数据库接管见 `EXISTING_DATABASE_MIGRATION.md` |
| 认证授权 | 无 | 真实需求出现再加 |
| body_limit 流式场景 | 响应已开始时无法改成 413 | 需在入口网关层再做一层限制 |
| 示例代码 | 单表，无外键 | 若要演示关系加载，再补一张表 |
| Alembic 数据库连接预算 | 与运行时共享 pool | 大规模迁移可考虑独立连接池 |

## 12. 值得追问的问题

1. `add_middleware` 的注册顺序和实际执行顺序为什么相反？
2. `_BodyTooLarge` 之所以会被 `BodySizeLimitMiddleware` 自己捕获，
   而不是被 `UnexpectedErrorMiddleware` 吞掉，是哪条中间件顺序决定的？
3. 纯 ASGI 中间件的 `receive` 为什么要自己包装？
4. `search_path=pg_catalog` 加 `metadata.schema` 组合解决了什么问题？
   引入 pgvector / PostGIS 后应该改什么？
5. 为什么 `statement_timeout` 要放在连接参数里而不是应用层 `asyncio.timeout`？
6. `expire_on_commit=False` 在异步 Session 下解决的是什么问题？
7. 为什么 Session 依赖不自动 commit？事务边界放在哪一层由什么决定？
8. `IntegrityError.orig.sqlstate` 的四个码分别对应什么约束？
   为什么不用英文错误文本匹配？
9. PATCH 语义里“未传”与“显式 null”靠什么区分？`model_fields_set` 在哪里用？
10. live 和 ready 分离解决的是什么运维问题？反过来会怎样？
11. Alembic 空 metadata 护栏能挡住所有“忘记注册 Model”的情况吗？
