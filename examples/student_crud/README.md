# 教学示例：单表 CRUD

> 这一组文件**不**是模板运行时的一部分，仅用于演示从 Model → Schema → Service →
> Router 的最小分层。所有示例代码都不应在生产里保留。

## 它包含什么

| 文件 | 作用 |
| --- | --- |
| `model.py` | SQLAlchemy ORM Model：自增主键、唯一约束、可空字段的写法 |
| `schema.py` | Pydantic 输入输出；演示 `extra="forbid"`、PATCH 区分“未传”与“显式 null” |
| `service.py` | 查询编排 + 事务边界 + IntegrityError → 业务异常映射 |
| `router.py` | FastAPI 路由；只做依赖注入与 HTTP 状态码映射 |

## 为什么独立于 `app/`

- 模板运行时不应被任何业务代码污染；
- 删除本目录后 `app/` 仍然可以正常启动、跑测试；
- Alembic 不会扫描 `examples/`，也就不会把这些表加进 `Base.metadata`。

## 如何把示例复制进自己的项目

1. 把 `model.py` 复制到 `app/models/xxx.py`；
2. 把 `schema.py` 复制到 `app/schemas/xxx.py`，按真实字段裁剪；
3. 把 `service.py` 复制到 `app/services/xxx.py`，按真实业务改函数体；
4. 把 `router.py` 复制到 `app/api/routes/xxx.py`；
5. 在 `app/models/__init__.py` 中 `from app.models.xxx import Xxx`；
6. 在 `app/api/router.py` 中 `api_router.include_router(router)`；
7. 跑：

   ```powershell
   uv run alembic revision --autogenerate -m "create xxx tables"
   uv run alembic upgrade head
   ```

## PATCH 语义

- **未传字段**：保持数据库原值；
- **显式 `null`**：把对应列写成 `NULL`；
- **对 NOT NULL 字段显式 `null`**：请求校验阶段直接返回 `422`，不进 Service。

这是这份示例里**最容易抄错**的一处，请保留 `schema.py` 中
`field_validator` 的写法。

## 是否需要在生产保留

不需要。任何时候你的项目已经决定用 `user / order / product / ...` 之类
真实模型时，把本目录整组删除即可。
