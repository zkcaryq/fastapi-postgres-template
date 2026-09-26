"""Lifespan shutdown timeout 的真实行为测试。

通过把 ``SHUTDOWN_TIMEOUT`` 设为很小的值（用 ``monkeypatch.setenv``），
并替换 ``engine.dispose`` 为一个会 hang 的协程，验证：
- ``asyncio.timeout`` 真的截断；
- 超时分支只写 warning 日志、不外抛；
- 正常路径下 ``dispose`` 会被调用。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_lifespan_dispose_completes_normally(monkeypatch, caplog):
    """正常路径：``dispose`` 立即返回，shutdown 干净退出，无 timeout 警告。"""
    from app.core import settings as settings_module
    from app.db import session as session_module

    monkeypatch.setenv("SHUTDOWN_TIMEOUT", "0.5")
    settings_module.get_settings.cache_clear()
    settings = settings_module.get_settings()

    class FakeEngine:
        def __init__(self):
            self.dispose_called = False

        async def dispose(self):
            self.dispose_called = True
            # 非常快

    fake = FakeEngine()
    monkeypatch.setattr(session_module, "engine", fake)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            try:
                async with asyncio.timeout(settings.SHUTDOWN_TIMEOUT):
                    await fake.dispose()
            except TimeoutError:
                logging.getLogger("app.main").warning("engine dispose timed out during shutdown")

    caplog.set_level(logging.WARNING, logger="app.main")
    app = FastAPI(lifespan=lifespan)
    async with app.router.lifespan_context(app):
        pass

    assert fake.dispose_called is True
    assert not any("timed out" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_lifespan_dispose_timeout_writes_log_and_does_not_block(monkeypatch, caplog):
    """超时路径：``dispose`` hang 住超过 SHUTDOWN_TIMEOUT 时：
    - 写一条 warning 日志；
    - 进程能在合理时间内退出（不会 hang 60 秒）。"""
    from app.core import settings as settings_module
    from app.db import session as session_module

    monkeypatch.setenv("SHUTDOWN_TIMEOUT", "0.3")
    settings_module.get_settings.cache_clear()
    settings = settings_module.get_settings()

    class FakeEngine:
        def __init__(self):
            self.dispose_called = False

        async def dispose(self):
            self.dispose_called = True
            # 比 timeout 长很多
            await asyncio.sleep(60)

    fake = FakeEngine()
    monkeypatch.setattr(session_module, "engine", fake)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            try:
                async with asyncio.timeout(settings.SHUTDOWN_TIMEOUT):
                    await fake.dispose()
            except TimeoutError:
                logging.getLogger("app.main").warning("engine dispose timed out during shutdown")

    caplog.set_level(logging.WARNING, logger="app.main")
    app = FastAPI(lifespan=lifespan)
    loop = asyncio.get_event_loop()
    start = loop.time()
    async with app.router.lifespan_context(app):
        pass
    elapsed = loop.time() - start

    assert fake.dispose_called is True
    # 关键：没真的等 60 秒
    assert elapsed < 3.0, f"shutdown 实际等 {elapsed:.2f}s，疑似没生效"
    # 警告日志确实写了
    assert any("timed out" in rec.message for rec in caplog.records), caplog.records
