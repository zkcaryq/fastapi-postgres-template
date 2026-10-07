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

## CORS

默认允许本机Vite开发地址：

```dotenv
CORS_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]
CORS_ALLOW_CREDENTIALS=false
```

`CORS_ORIGINS`必须是JSON数组，内容是前端页面的“协议 + 主机 + 端口”，不是后端接口地址。
Bearer Token由`Authorization`请求头传递，不要求开启`CORS_ALLOW_CREDENTIALS`。只有明确采用跨站
Cookie并完成CSRF、SameSite和Secure设计后，才应开启凭据模式。

跨电脑调试还要让后端监听局域网网卡，并加入前端电脑的真实源：

```dotenv
HOST=0.0.0.0
CORS_ORIGINS=["http://192.168.1.10:5173"]
```

客户端应访问后端电脑的真实局域网IP，不能把`0.0.0.0`当成访问地址。

## 健康检查

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

- live 只检查进程。
- ready 使用注入的 AsyncSession 执行 `SELECT 1`。

## 日志

日志同时输出到终端和按启动时间创建的独立文件。日期和时间统一使用 UTC，末尾的 `Z`
表示 UTC，例如：

```text
logs/2026-10-06/app-13-45-20Z-pid-12345.log
```

每个进程启动时创建一个新文件；开发热重载产生新进程时也会创建新文件。PID 可以避免多个
进程在同一秒启动时写入同名文件。单个启动日志达到 5 MiB 后仍会轮转，并保留最多 5 份
该启动文件的历史分片。

查看最新启动日志：

```powershell
$latestLog = Get-ChildItem .\logs -Recurse -File -Filter "app-*.log" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
Get-Content -LiteralPath $latestLog.FullName -Tail 100
Select-String -LiteralPath $latestLog.FullName -Pattern "error_id"
```

跨全部日期和启动文件查找：

```powershell
Select-String -Path .\logs\*\app-*.log* -Pattern "error_id"
```

request_id 用于串联整次请求，error_id 用于定位一次未知异常。日志会替换配置中的数据库密码，但业务代码仍不得记录密码、Token、Cookie 或完整请求体。

按启动分文件会持续占用磁盘；模板不会擅自删除历史日志。部署时应由运维平台设置保留周期，
本地则应在确认不再需要排错记录后手工清理旧日期目录。

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
