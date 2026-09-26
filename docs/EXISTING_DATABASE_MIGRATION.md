# 已有数据库接入 Alembic

模板默认假设：项目从空库开始，第一份迁移由
`uv run alembic revision --autogenerate -m "initial schema"` 生成。
如果你的数据库已经有表（来自历史脚本、其他 ORM、SQL 文件等），
就需要走**已有数据库接管**流程。

本文档列出**一次性**的接入步骤。接入完成后，新项目模板的常规流程继续生效。

## 总体原则

```text
1. 让 Model 与真实数据库 1:1 对齐
2. 跑 alembic check，确认无差异
3. 用 stamp / baseline 把当前库标记为某个 revision
4. 之后所有结构变更都通过 Alembic 累加 revision
```

任何时刻都不要回到“手动改库 + 改 Model + 重新生成”的循环：那样 Alembic
版本表就和真实状态对不上，autogenerate 会开始误判。

## 步骤

### 1. 备份

```bash
pg_dump --schema-only --no-owner --schema=<DB_SCHEMA> "$DATABASE_URL" > schema.sql
pg_dump --data-only --no-owner --schema=<DB_SCHEMA> "$DATABASE_URL" > data.sql
```

接管过程不修改数据，但备份是数据库变更的标准动作。

### 2. 让 Model 与真实数据库对齐

把数据库的每个表 / 字段 / 索引 / 约束写成 SQLAlchemy Model：

- 列名、类型、长度、`NOT NULL`、默认值完全一致；
- 主键使用 `Identity()`，不要写 `autoincrement=True`（那会回退到 SERIAL）；
- 唯一约束、检查约束、外键显式声明；
- `MetaData` 已经带 `DB_SCHEMA` 限定，不需要在每个 `__tablename__` 里加 schema。

`examples/student_crud/model.py` 是一个最小例子。

### 3. 验证 Schema 与 Model 完全一致

```powershell
uv run alembic check
```

`alembic check` 反映的是“目前数据库真实状态 vs Model 与 migration 推导出的状态”。
如果它报告差异，按报告调整 Model 或写额外 migration 补齐。

### 4. 生成空 baseline migration（如果当前 revision 链空）

```powershell
uv run alembic revision -m "baseline: existing schema"
```

打开生成的文件，把 `upgrade()` / `downgrade()` 改成 `pass`：
这条迁移**不**改任何对象，作用只是在 `alembic_version` 表里登记当前状态。

### 5. 用 stamp 把数据库标记到该 revision

```powershell
uv run alembic stamp head
```

这一步**只**写入 `alembic_version` 表，不执行 DDL。

### 6. 验证

```powershell
uv run alembic current    # 应输出当前 revision id
uv run alembic check      # 应无差异
uv run alembic heads      # 只有一个 head
```

### 7. 之后所有结构变更走正常流程

```powershell
# 改 Model → 生成 candidate → 人工 review → apply
uv run alembic revision --autogenerate -m "add column xxx"
uv run alembic upgrade head
```

不要在生产环境直接 `psql` 改结构，再回头修改 Model。

## 常见陷阱

### 不要混用“手工 DDL + 重新 autogenerate”

如果生产上已经手工 ALTER 了表，再回本地跑 `alembic revision --autogenerate`，
Alembic 不知道手工改了什么，可能生成分不清的差异。把手工 DDL 写成一条
明确的 revision，再做后续变更。

### 不要把 baseline 当成普通 migration 反复回滚

baseline 的目的是“注册起点”，不是“可以上下切换的迁移”。
`downgrade()` 必须保持 `pass`，否则会变成“在某个历史 Schema 上跑迁移”，
而那时 schema 早就不是那条 baseline 描述的状态了。

### 跨 Schema / 跨数据库搬迁不属于本文档范围

把业务表从一个 Schema 搬到另一个 Schema，或从一个库搬到另一个库，
都需要单独设计迁移，不通过“修改 DB_SCHEMA”实现。
`DB_SCHEMA` 在 import 阶段就由 `Base.metadata` 钉死，改 .env 不会让已有表搬家。

## 真正的安全边界

```text
- 模板不建库、不建 Schema、不改授权、不 stamp、不 reset；
- 已有数据库接管是一次性流程，不应进入新项目的 alembic/versions/；
- 模板随版本带的 alembic/versions/ 只放项目自己的真实迁移；
- 历史 baseline 应放在单独的分支或单独的项目里维护，不污染新模板。
```
