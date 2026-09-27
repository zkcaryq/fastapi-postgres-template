"""启动入口：让 `python -m app` 这个命令能启动服务器。"""
# ↑ 模块 docstring：这个文件让"用 python -m app 启动"成为可能。
#   当你运行 `python -m app` 时，Python 会执行这个文件。

# 导入 argparse 标准库：用于解析命令行参数（比如 --reload）。
import argparse

# 导入 uvicorn：真正跑 FastAPI 的服务器。
import uvicorn

# 导入配置读取函数。
from app.core.settings import get_settings


def main() -> None:
    # ↑ 主函数：解析参数并启动服务器。

    parser = argparse.ArgumentParser(description="运行 FastAPI，读取 HOST/PORT 并兼容 Windows")
    # ↑ 创建命令行参数解析器，description 是帮助说明文字。

    parser.add_argument("--reload", action="store_true")
    # ↑ 添加一个可选参数 --reload：只要命令行里出现了它，值就是 True。
    #   reload 是"热重载"——代码改动后自动重启，开发时很方便。

    args = parser.parse_args()
    # ↑ 解析实际传入的命令行参数，结果存到 args。

    settings = get_settings()
    # ↑ 读取配置（含 HOST、PORT、APP_ENV）。

    if args.reload and settings.APP_ENV == "production":
        # ↑ 如果用户在生产环境还想开热重载……
        parser.error("生产环境禁止 --reload")
        # ↑ 直接报错并退出（生产环境开热重载很危险，会反复重启）。

    uvicorn.run(
        # ↑ 启动 uvicorn 服务器。
        "app.main:app",
        # ↑ 要运行的应用：app 包下的 main 模块里的 app 对象。
        host=settings.HOST,
        # ↑ 监听地址（来自配置）。
        port=settings.PORT,
        # ↑ 监听端口（来自配置）。
        reload=args.reload,
        # ↑ 是否热重载（来自命令行参数）。
        loop="app.core.event_loop:loop_factory",
        # ↑ 指定事件循环工厂（解决 Windows 上 psycopg 的事件循环兼容问题）。
        access_log=False,
        # ↑ 关闭 uvicorn 的访问日志（避免泄露查询串，见日志模块的说明）。
    )


if __name__ == "__main__":
    # ↑ Python 惯例：只有当这个文件被"直接运行"（而不是被 import）时才执行下面的代码。
    #   如果别人 import 了这个模块，main() 不会被自动调用。
    main()
    # ↑ 调用主函数。
