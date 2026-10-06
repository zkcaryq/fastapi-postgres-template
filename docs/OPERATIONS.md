# 开发与运维命令

## 初始化

```powershell
Copy-Item .env.example .env
uv sync
uv run alembic upgrade head
```

模板不会创建数据库或 Schema。请提前在 PostgreSQL 中创建数据库、`app` Schema、账号并授予权限。

## 启动

```powershell
uv run python -m app --reload
```

生产环境设置 `APP_ENV=production`，并且不要使用 `--reload`。生产环境会关闭 Swagger 和 OpenAPI JSON。

## 健康检查

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

- live 只检查进程。
- ready 使用注入的 AsyncSession 执行 `SELECT 1`。

## 日志

日志同时输出到终端和 `logs/app.log`，文件达到 5 MiB 后轮转，最多保留 5 份。

```powershell
Get-Content .\logs\app.log -Tail 100
Select-String -Path .\logs\app.log -Pattern "error_id"
```

request_id 用于串联整次请求，error_id 用于定位一次未知异常。日志会替换配置中的数据库密码，但业务代码仍不得记录密码、Token、Cookie 或完整请求体。

## Alembic

```powershell
uv run alembic current
uv run alembic history
uv run alembic check
uv run alembic revision --autogenerate -m "迁移说明"
uv run alembic upgrade head
uv run alembic downgrade -1
```

生成 revision 后必须先审阅文件，再执行 upgrade。开发环境不配置 `MIGRATION_DB_*` 时使用运行账号；生产环境可配置独立 DDL 账号。

## 静态验证

```powershell
uv run ruff check .
uv run ruff format --check .
uv run python -m compileall app alembic
```
