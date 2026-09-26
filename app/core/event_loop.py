import asyncio
import sys


def loop_factory() -> asyncio.AbstractEventLoop:
    # psycopg 在 Windows 不支持 Proactor；工厂同时适用于 reload 和普通运行。
    # 不在 app import 时修改全局事件循环策略，避免影响宿主或测试框架。
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()
