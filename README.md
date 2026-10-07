# FastAPI PostgreSQL Template

面向个人项目和中小型生产项目的异步后端模板。保留连接池、超时、日志、请求追踪、统一响应、全局异常、CORS 和 Alembic 等生产基础能力，同时保持 Router → Service → ORM 调用链清晰。

## 技术栈

- FastAPI
- SQLAlchemy 2 AsyncIO
- PostgreSQL + psycopg 3
- Alembic
- Pydantic Settings
- uv
- Ruff

## 开始使用

```powershell
Copy-Item .env.example .env
uv sync
uv run alembic upgrade head
uv run python -m app --reload
```

Swagger：`http://127.0.0.1:8000/docs`

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

## 数据库边界

- 数据库、Schema、账号和权限由开发者、DBA 或部署流程提前创建。
- 应用启动不会建库、建 Schema、建表或自动执行迁移。
- 运行连接使用 `database_url`；Alembic 使用 `migration_database_url`。
- 本地可共用一个账号；生产可以配置独立迁移账号。

## 关键目录

```text
app/api          HTTP 路由和依赖注入
app/core         配置、日志、中间件和事件循环
app/db           Engine、Session、ORM Base 与 Alembic 护栏
app/models       SQLAlchemy ORM
app/schemas      Pydantic 请求/响应结构
app/services     业务逻辑和数据库操作
alembic          数据库迁移
docs             架构和运维说明
```

业务接口统一返回：

```json
{
  "code": 200,
  "message": "请求成功",
  "data": {}
}
```

失败时仍返回真实的4xx/5xx HTTP状态码。`ApiResponse`只统一JSON外形，不把错误伪装成HTTP 200。

详细设计见 [架构说明](docs/ARCHITECTURE.md)，启动、日志和迁移命令见 [运维说明](docs/OPERATIONS.md)。

## 常用命令

```powershell
uv run ruff check .
uv run ruff format --check .
uv run python -m compileall app alembic
uv run alembic current
uv run alembic check
uv run alembic revision --autogenerate -m "迁移说明"
uv run alembic upgrade head
```

项目不包含 pytest 或测试目录。修改后至少执行 Ruff、compileall、Alembic 检查和接口手动验证。
