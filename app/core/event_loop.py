"""事件循环工厂：根据操作系统返回合适的事件循环。

为什么需要这个文件：
FastAPI 是异步框架，底层靠"事件循环"来调度所有异步任务（可以理解为
"餐厅里只有一个服务员，靠轮转来同时服务很多桌客人"）。不同操作系统
提供不同"型号"的事件循环，PostgreSQL 的异步驱动 psycopg 只在其中
一种型号上能正常工作，所以这里专门写一个函数来挑出正确的型号。
"""

# 导入 asyncio 标准库：提供事件循环相关的类和函数。
import asyncio

# 导入 sys 标准库：可以读取当前操作系统平台等信息（sys.platform）。
import sys


def loop_factory() -> asyncio.AbstractEventLoop:
    # ↑ 定义一个函数，返回值类型是"抽象事件循环"。uvicorn 启动时会调用它来拿事件循环。

    # psycopg 在 Windows 不支持 Proactor；工厂同时适用于 reload 和普通运行。
    # 不在 app import 时修改全局事件循环策略，避免影响宿主或测试框架。
    # ↑ 上面的注释说明：Windows 默认的事件循环型号叫 Proactor，但 psycopg 驱动
    #   不认它，必须换成另一个型号 Selector。下面两行就是做这个判断。

    if sys.platform == "win32":
        # ↑ 判断当前是不是 Windows 系统。sys.platform 在 Windows 上等于字符串 "win32"。

        return asyncio.SelectorEventLoop()
        # ↑ 是 Windows：返回 Selector 型号的事件循环（psycopg 认这个）。

    return asyncio.new_event_loop()
    # ↑ 不是 Windows（如 Linux/Mac）：用 asyncio 默认方式新建一个事件循环即可。
    #   这两个 return 只会执行其中一个，因为上面的 if 分支是二选一的。
