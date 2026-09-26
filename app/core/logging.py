"""标准库日志：开发可读、生产 JSON；不记录请求体、查询串或原始异常文本。"""

import json
import logging
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

from app.core.request_id import current_request_id
from app.core.settings import PROJECT_ROOT, get_settings


class SafeFormatter(logging.Formatter):
    def __init__(self, secrets: tuple[str, ...], json_output: bool, project_root: Path) -> None:
        super().__init__()
        # 密钥与项目根在配置时采集一次，避免每条日志重复读取配置和做空值替换。
        self._secrets = tuple(item for item in secrets if item)
        self._json_output = json_output
        self._project_root = project_root

    def _relative_frame(self, raw_path: str) -> str:
        """把绝对路径转换成项目根目录下的相对路径，避免泄露本机布局。

        不在项目内的文件（如站点包里的某个库）原样保留 basename，
        仍然不暴露绝对路径。
        """
        try:
            path = Path(raw_path).resolve()
            relative = path.relative_to(self._project_root)
            return relative.as_posix()
        except ValueError:
            return Path(raw_path).name

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        # 基础保护不等于万能脱敏；业务代码仍禁止记录 Token、请求体和配置对象。
        for secret in self._secrets:
            if secret in message:
                message = message.replace(secret, "[REDACTED]")
        data = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "request_id": current_request_id(),
        }
        if record.exc_info:
            exc_type, _, tb = record.exc_info
            data["exception_type"] = exc_type.__name__ if exc_type else "unknown"
            # 保留定位信息，但不包含异常值、源码行或局部变量，避免泄露 SQL 参数。
            # 路径一律转成项目根的相对路径，避免在响应/日志里出现本机绝对路径。
            data["frames"] = "; ".join(
                f"{self._relative_frame(frame.filename)}:{frame.lineno}:{frame.name}"
                for frame in traceback.extract_tb(tb)
            )
        if self._json_output:
            return json.dumps(data, ensure_ascii=False)
        return " | ".join(f"{key}={value}" for key, value in data.items())


def configure_logging() -> None:
    settings = get_settings()
    formatter = SafeFormatter(
        secrets=(settings.DB_PASSWORD.get_secret_value(),),
        json_output=settings.APP_ENV == "production",
        project_root=PROJECT_ROOT,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "sqlalchemy", "alembic"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
        logger.setLevel(logging.WARNING if name == "sqlalchemy" else logging.INFO)
    # Uvicorn 默认 access log 含完整查询串；模板默认关闭，避免未来 Token 泄漏。
    logging.getLogger("uvicorn.access").disabled = True
