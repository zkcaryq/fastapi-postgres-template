import argparse

import uvicorn

from app.core.settings import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 FastAPI，读取 HOST/PORT 并兼容 Windows")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if args.reload and settings.APP_ENV == "production":
        parser.error("生产环境禁止 --reload")
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=args.reload,
        loop="app.core.event_loop:loop_factory",
        access_log=False,
    )


if __name__ == "__main__":
    main()
