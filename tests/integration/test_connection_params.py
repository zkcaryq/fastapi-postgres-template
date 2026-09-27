"""连接层参数在真实 PostgreSQL 上的验证。

覆盖：
- ``SHOW search_path`` = ``pg_catalog``（模板核心安全设定）
- ``SHOW statement_timeout`` 与 ``Settings.DB_STATEMENT_TIMEOUT_MS`` 一致
- ``SHOW idle_in_transaction_session_timeout`` 与
  ``Settings.DB_IDLE_IN_TX_TIMEOUT_MS`` 一致
- idle-in-transaction 超时**真实行为**：用测试专用短超时值，
  事务内空闲超过阈值后服务器主动断开连接（不动数据库全局配置）
"""
# ↑ 模块 docstring：验证连接时设置的参数（search_path、超时）在真实 PG 上真的生效。

# 这个 import 让类型标注用"未来注解"。
from __future__ import annotations

# 导入 asyncio。
import asyncio

# 导入 pytest、SQLAlchemy 的引擎/text、DBAPIError、异步引擎相关。
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration
# ↑ 打 integration 标记（默认跳过）。


def _parse_pg_duration_ms(value: str) -> int:
    # ↑ 辅助函数：把 PostgreSQL 的时长字符串转成毫秒数。

    """解析 PostgreSQL ``SHOW`` 返回的时长（如 ``30000ms`` / ``60s`` / ``1min``）。"""
    # ↑ docstring。
    v = value.strip()
    # ↑ 去掉首尾空白。
    if v.endswith("ms"):
        # ↑ 毫秒结尾。
        return int(v[:-2])
        # ↑ 去掉 "ms" 转整数。
    if v.endswith("min"):
        # ↑ 分钟结尾。
        return int(v[:-3]) * 60_000
        # ↑ 去掉 "min" 乘以 60000。
    if v.endswith("s"):
        # ↑ 秒结尾。
        return int(v[:-1]) * 1_000
        # ↑ 去掉 "s" 乘以 1000。
    return int(v)
    # ↑ 其他情况直接转整数。


def _engine_with_overrides(database_url: str, **overrides_ms: int):
    # ↑ 辅助函数：构造引擎，可覆盖个别超时参数（只影响本连接）。

    """基于生产 ``connect_args`` 构造 engine，可覆盖个别超时（仅本连接生效）。"""
    # ↑ docstring。
    from app.core.settings import get_settings
    # ↑ 函数内导入。

    settings = get_settings()
    # ↑ 读配置。
    connect_args = dict(settings.connect_args)
    # ↑ 复制一份连接参数（避免改到原始配置）。
    options = connect_args["options"]
    # ↑ 取出 options 字符串。
    for key, value in overrides_ms.items():
        # ↑ 遍历要覆盖的参数。
        # options 形如 "-csearch_path=pg_catalog -ctimezone=UTC -cstatement_timeout=30000 ..."
        # ↑ 说明 options 的格式。
        parts = options.split(" ")
        # ↑ 按空格拆成片段。
        parts = [p if not p.startswith(f"-c{key}=") else f"-c{key}={value}" for p in parts]
        # ↑ 找到要覆盖的片段并替换成新值，其余保持不变。
        options = " ".join(parts)
        # ↑ 重新拼起来。
    connect_args["options"] = options
    # ↑ 更新 options。
    return create_async_engine(database_url, connect_args=connect_args)
    # ↑ 用修改后的参数创建异步引擎。


def test_search_path_is_pg_catalog_on_production_connect_args(integration_database_url: str):
    # ↑ 测试：连接后 search_path 确实是 pg_catalog。

    from app.core.settings import get_settings
    # ↑ 函数内导入。

    settings = get_settings()
    # ↑ 读配置。
    engine = create_engine(integration_database_url, connect_args=settings.connect_args)
    # ↑ 用生产同款连接参数创建同步引擎。
    try:
        # ↑ 尝试。
        with engine.connect() as conn:
            # ↑ 连接。
            sp = conn.execute(text("SHOW search_path")).scalar()
            # ↑ 查询 search_path。
        assert sp.split(",")[0].strip() == "pg_catalog", sp
        # ↑ 断言第一项是 pg_catalog（失败时打印 sp）。
    finally:
        # ↑ 最后。
        engine.dispose()
        # ↑ 释放引擎。


def test_statement_timeout_matches_settings(integration_database_url: str):
    # ↑ 测试：statement_timeout 与配置值一致。

    from app.core.settings import get_settings
    # ↑ 函数内导入。

    settings = get_settings()
    # ↑ 读配置。
    engine = create_engine(integration_database_url, connect_args=settings.connect_args)
    # ↑ 创建引擎。
    try:
        # ↑ 尝试。
        with engine.connect() as conn:
            # ↑ 连接。
            value = conn.execute(text("SHOW statement_timeout")).scalar()
            # ↑ 查询 statement_timeout。
        assert _parse_pg_duration_ms(value) == settings.DB_STATEMENT_TIMEOUT_MS, value
        # ↑ 断言解析后等于配置值。
    finally:
        # ↑ 最后。
        engine.dispose()
        # ↑ 释放引擎。


def test_idle_in_transaction_timeout_matches_settings(integration_database_url: str):
    # ↑ 测试：idle_in_transaction_session_timeout 与配置值一致。

    from app.core.settings import get_settings
    # ↑ 函数内导入。

    settings = get_settings()
    # ↑ 读配置。
    engine = create_engine(integration_database_url, connect_args=settings.connect_args)
    # ↑ 创建引擎。
    try:
        # ↑ 尝试。
        with engine.connect() as conn:
            # ↑ 连接。
            value = conn.execute(text("SHOW idle_in_transaction_session_timeout")).scalar()
            # ↑ 查询该参数。
        assert _parse_pg_duration_ms(value) == settings.DB_IDLE_IN_TX_TIMEOUT_MS, value
        # ↑ 断言一致。
    finally:
        # ↑ 最后。
        engine.dispose()
        # ↑ 释放引擎。


@pytest.mark.asyncio
# ↑ 异步测试。
async def test_idle_in_transaction_timeout_terminates_idle_transaction(
    # ↑ 测试：事务空闲超时后，PG 真的会主动断开连接。
    integration_database_url: str,
):
    """真实行为：事务打开后空闲超过阈值，PostgreSQL 主动终止连接。

    使用测试专用短超时（1000ms），只影响本测试的连接；
    不执行 ALTER SYSTEM、不改 postgresql.conf。
    """
    # ↑ docstring。
    eng = _engine_with_overrides(integration_database_url, idle_in_transaction_session_timeout=1000)
    # ↑ 用覆盖后的参数（空闲超时 1000ms）创建引擎。
    session_factory = async_sessionmaker(eng, expire_on_commit=False, autoflush=False)
    # ↑ 创建会话工厂。
    try:
        # ↑ 尝试。
        with pytest.raises(DBAPIError) as excinfo:
            # ↑ 断言会抛 DBAPIError。
            async with session_factory() as session, session.begin():
                # ↑ 开启会话和事务。
                await session.execute(text("SELECT 1"))
                # ↑ 执行一条语句。
                # 事务保持打开但空闲 2 秒，超过 1000ms 阈值
                # ↑ 说明。
                await asyncio.sleep(2.0)
                # ↑ 空闲 2 秒（超过 1 秒阈值）。
                # 下一条语句应发现连接已被服务器终止
                # ↑ 说明。
                await session.execute(text("SELECT 2"))
                # ↑ 再执行，此时连接已被服务器断开。
        msg = str(excinfo.value).lower()
        # ↑ 取出异常信息（转小写）。
        assert "idle-in-transaction" in msg or "terminating connection" in msg, msg
        # ↑ 断言错误信息里有关键词。
    finally:
        # ↑ 最后。
        await eng.dispose()
        # ↑ 释放引擎。
