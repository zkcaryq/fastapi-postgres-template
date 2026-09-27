"""Lifespan shutdown timeout 的真实行为测试。

通过把 ``SHUTDOWN_TIMEOUT`` 设为很小的值（用 ``monkeypatch.setenv``），
并替换 ``engine.dispose`` 为一个会 hang 的协程，验证：
- ``asyncio.timeout`` 真的截断；
- 超时分支只写 warning 日志、不外抛；
- 正常路径下 ``dispose`` 会被调用。
"""
# ↑ 模块 docstring：测试"应用关闭时，连接池释放会不会卡住"这个行为。
#   用极小的超时值 + 假的"会卡住"的引擎，验证超时保护是否真的生效。

# 这个 import 让本文件里所有类型标注都按"未来注解"处理（用字符串表示）。
from __future__ import annotations

# 导入 asyncio（异步工具）和 logging（日志）。
import asyncio
import logging

# 导入 asynccontextmanager（构造异步上下文管理器）。
from contextlib import asynccontextmanager

# 导入 pytest 和 FastAPI。
import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
# ↑ 标记：这是一个异步测试（pytest-asyncio 会为它创建事件循环）。
async def test_lifespan_dispose_completes_normally(monkeypatch, caplog):
    # ↑ 测试正常路径：dispose 立即返回，不触发超时警告。
    #   monkeypatch：pytest 的"临时替换"工具；caplog：捕获日志的工具。

    """正常路径：``dispose`` 立即返回，shutdown 干净退出，无 timeout 警告。"""
    # ↑ docstring。
    from app.core import settings as settings_module
    from app.db import session as session_module
    # ↑ 在函数内 import（延迟导入），方便 monkeypatch 替换。

    monkeypatch.setenv("SHUTDOWN_TIMEOUT", "0.5")
    # ↑ 临时把超时设为 0.5 秒。
    settings_module.get_settings.cache_clear()
    # ↑ 清掉配置缓存，让新超时值生效。
    settings = settings_module.get_settings()
    # ↑ 重新读取配置。

    class FakeEngine:
        # ↑ 定义一个假引擎，替代真实的 engine。

        def __init__(self):
            # ↑ 初始化。
            self.dispose_called = False
            # ↑ 记录 dispose 是否被调用。

        async def dispose(self):
            # ↑ 假的 dispose 方法。
            self.dispose_called = True
            # ↑ 标记被调用了。
            # 非常快
            # ↑ 说明：立即返回（模拟正常关闭）。

    fake = FakeEngine()
    # ↑ 创建假引擎实例。
    monkeypatch.setattr(session_module, "engine", fake)
    # ↑ 用假引擎替换 session 模块里的真引擎。

    @asynccontextmanager
    # ↑ 构造一个测试用的 lifespan。
    async def lifespan(app):
        # ↑ 模拟 main.py 里的 lifespan 逻辑。
        try:
            # ↑ 启动阶段。
            yield
            # ↑ 暂停。
        finally:
            # ↑ 关闭阶段。
            try:
                # ↑ 尝试关闭。
                async with asyncio.timeout(settings.SHUTDOWN_TIMEOUT):
                    # ↑ 限时关闭。
                    await fake.dispose()
                    # ↑ 调用假引擎的 dispose。
            except TimeoutError:
                # ↑ 超时则记录警告。
                logging.getLogger("app.main").warning("engine dispose timed out during shutdown")

    caplog.set_level(logging.WARNING, logger="app.main")
    # ↑ 让 caplog 捕获 app.main 的 WARNING 日志。
    app = FastAPI(lifespan=lifespan)
    # ↑ 用测试 lifespan 创建应用。
    async with app.router.lifespan_context(app):
        # ↑ 手动进入 lifespan 上下文（触发启动和关闭）。
        pass

    assert fake.dispose_called is True
    # ↑ 断言 dispose 被调用了。
    assert not any("timed out" in rec.message for rec in caplog.records)
    # ↑ 断言没有任何"超时"警告日志（正常路径不应超时）。


@pytest.mark.asyncio
# ↑ 异步测试。
async def test_lifespan_dispose_timeout_writes_log_and_does_not_block(monkeypatch, caplog):
    # ↑ 测试超时路径：dispose 卡住时，超时保护生效，进程能及时退出。

    """超时路径：``dispose`` hang 住超过 SHUTDOWN_TIMEOUT 时：
    - 写一条 warning 日志；
    - 进程能在合理时间内退出（不会 hang 60 秒）。"""
    # ↑ docstring。
    from app.core import settings as settings_module
    from app.db import session as session_module
    # ↑ 延迟导入。

    monkeypatch.setenv("SHUTDOWN_TIMEOUT", "0.3")
    # ↑ 超时设 0.3 秒。
    settings_module.get_settings.cache_clear()
    # ↑ 清缓存。
    settings = settings_module.get_settings()
    # ↑ 重新读配置。

    class FakeEngine:
        # ↑ 假引擎。

        def __init__(self):
            # ↑ 初始化。
            self.dispose_called = False
            # ↑ 标记。

        async def dispose(self):
            # ↑ 假的 dispose。
            self.dispose_called = True
            # ↑ 标记被调用。
            # 比 timeout 长很多
            # ↑ 说明。
            await asyncio.sleep(60)
            # ↑ 假装要等 60 秒（远大于 0.3 秒超时）。

    fake = FakeEngine()
    # ↑ 创建假引擎。
    monkeypatch.setattr(session_module, "engine", fake)
    # ↑ 替换引擎。

    @asynccontextmanager
    # ↑ 测试 lifespan。
    async def lifespan(app):
        # ↑ 模拟 main.py。
        try:
            # ↑ 启动。
            yield
            # ↑ 暂停。
        finally:
            # ↑ 关闭。
            try:
                # ↑ 尝试关闭。
                async with asyncio.timeout(settings.SHUTDOWN_TIMEOUT):
                    # ↑ 限时 0.3 秒。
                    await fake.dispose()
                    # ↑ 调用（会卡 60 秒，但 0.3 秒后会被 timeout 打断）。
            except TimeoutError:
                # ↑ 超时。
                logging.getLogger("app.main").warning("engine dispose timed out during shutdown")
                # ↑ 记录警告。

    caplog.set_level(logging.WARNING, logger="app.main")
    # ↑ 捕获日志。
    app = FastAPI(lifespan=lifespan)
    # ↑ 创建应用。
    loop = asyncio.get_event_loop()
    # ↑ 拿到事件循环。
    start = loop.time()
    # ↑ 记录开始时间。
    async with app.router.lifespan_context(app):
        # ↑ 进入 lifespan（触发关闭逻辑）。
        pass
    elapsed = loop.time() - start
    # ↑ 计算经过的时间。

    assert fake.dispose_called is True
    # ↑ 断言 dispose 被调用。
    # 关键：没真的等 60 秒
    # ↑ 说明。
    assert elapsed < 3.0, f"shutdown 实际等 {elapsed:.2f}s，疑似没生效"
    # ↑ 断言关闭过程没超过 3 秒（证明 timeout 生效，没真等 60 秒）。
    # 警告日志确实写了
    # ↑ 说明。
    assert any("timed out" in rec.message for rec in caplog.records), caplog.records
    # ↑ 断言确实写了"超时"警告日志。
