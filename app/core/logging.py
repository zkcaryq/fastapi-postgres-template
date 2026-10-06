"""终端与轮转文件日志，并对已配置的数据库密码做基础脱敏。"""

import logging
import os
import sys
import traceback
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

from app.core.request_id import current_request_id
from app.core.settings import PROJECT_ROOT, get_settings

# 每个进程在导入本模块时确定一次启动时间。开发热重载会启动新进程，
# 因而也会得到新的日志文件；PID 用于避免同一秒启动多个进程时文件名冲突。
PROCESS_START_TIME = datetime.now(UTC)
LOG_DIRECTORY = PROJECT_ROOT / "logs" / PROCESS_START_TIME.strftime("%Y-%m-%d")
LOG_FILE_NAME = f"app-{PROCESS_START_TIME.strftime('%H-%M-%S')}Z-pid-{os.getpid()}.log"
LOG_FILE = LOG_DIRECTORY / LOG_FILE_NAME
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5


class SafeFormatter(logging.Formatter):
    """输出可检索文本日志，并替换配置中已知的数据库密码。"""

    def __init__(self, secrets: tuple[str, ...]) -> None:
        super().__init__()
        self._secrets = tuple(secret for secret in secrets if secret)

    def _redact(self, value: str) -> str:
        for secret in self._secrets:
            value = value.replace(secret, "[REDACTED]")
        return value

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, UTC).isoformat()
        message = self._redact(record.getMessage())
        parts = [
            f"time={timestamp}",
            f"level={record.levelname}",
            f"logger={record.name}",
            f"request_id={current_request_id()}",
            f"message={message}",
        ]
        for field in ("error_id", "request_method", "request_path"):
            value = getattr(record, field, None)
            if value is not None:
                parts.append(f"{field}={self._redact(str(value))}")

        rendered = " | ".join(parts)
        if record.exc_info:
            exception = "".join(traceback.format_exception(*record.exc_info)).rstrip()
            rendered = f"{rendered}\n{self._redact(exception)}"
        return rendered


def configure_logging() -> None:
    """把日志写到终端和本次进程独立的按日期归档文件。"""

    settings = get_settings()
    migration_password = (
        settings.MIGRATION_DB_PASSWORD.get_secret_value()
        if settings.MIGRATION_DB_PASSWORD is not None
        else ""
    )
    formatter = SafeFormatter((settings.DB_PASSWORD.get_secret_value(), migration_password))

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()
    root_logger.setLevel(settings.LOG_LEVEL)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Uvicorn 启停日志也进入相同的终端和文件；逐请求 access log 在 __main__ 中关闭。
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    root_logger.info("logging configured file=%s", LOG_FILE)
