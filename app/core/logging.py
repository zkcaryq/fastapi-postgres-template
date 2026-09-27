"""标准库日志：开发可读、生产 JSON；不记录请求体、查询串或原始异常文本。"""
# ↑ 模块级说明：这个文件负责"打日志"。开发环境日志是人能读的文本，
#   生产环境日志是 JSON（机器能解析）；并且日志里绝不记录敏感内容。

# 导入 json 标准库：用于把字典转成 JSON 字符串（生产日志格式）。
import json

# 导入 logging 标准库：Python 自带的日志模块。
import logging

# 导入 sys 标准库：这里用它拿 sys.stdout（标准输出流，即"打印到终端"）。
import sys

# 导入 traceback 标准库：用于提取异常发生时的调用堆栈（代码执行路径）。
import traceback

# 从 datetime 导入 UTC 和 datetime：用于给日志打上带时区的时间戳。
from datetime import UTC, datetime

# 从 pathlib 导入 Path：用于处理文件路径。
from pathlib import Path

# 导入"当前请求的 ID"读取函数（阶段 8 讲过，用于把同一请求的日志串联起来）。
from app.core.request_id import current_request_id

# 导入项目根目录路径常量，和读取配置的单例函数。
from app.core.settings import PROJECT_ROOT, get_settings


class SafeFormatter(logging.Formatter):
    # ↑ 自定义一个日志格式化器，继承 Python 自带的 Formatter。
    #   它比默认格式化器多做了两件事：脱敏（替换密码）+ 相对路径（不泄露本机目录）。

    def __init__(self, secrets: tuple[str, ...], json_output: bool, project_root: Path) -> None:
        # ↑ 初始化方法。参数含义：
        #   secrets：需要被脱敏的敏感字符串（比如密码）。
        #   json_output：是否输出 JSON 格式（生产环境为 True）。
        #   project_root：项目根目录，用于把绝对路径转成相对路径。

        super().__init__()
        # ↑ 先调用父类 Formatter 的初始化，完成基础设置。

        # 密钥与项目根在配置时采集一次，避免每条日志重复读取配置和做空值替换。
        # ↑ 上面是设计说明：这些值只在创建 formatter 时读一次，后面每条日志复用。
        self._secrets = tuple(item for item in secrets if item)
        # ↑ 把 secrets 里的空字符串过滤掉，转成元组存起来。
        #   过滤空值是防止把"空串"当成敏感词去替换（那样会误伤正常内容）。
        self._json_output = json_output
        # ↑ 记住是否输出 JSON。
        self._project_root = project_root
        # ↑ 记住项目根目录。

    def _relative_frame(self, raw_path: str) -> str:
        # ↑ 辅助方法：把绝对路径转成相对项目根的路径，避免泄露本机目录结构。

        """把绝对路径转换成项目根目录下的相对路径，避免泄露本机布局。

        不在项目内的文件（如站点包里的某个库）原样保留 basename，
        仍然不暴露绝对路径。
        """
        # ↑ 上面的 docstring 是原说明。

        try:
            # ↑ 尝试做路径转换。
            path = Path(raw_path).resolve()
            # ↑ 把传入的字符串路径变成 Path 对象，并 resolve() 成绝对路径。
            relative = path.relative_to(self._project_root)
            # ↑ 计算它相对项目根目录的相对路径。
            return relative.as_posix()
            # ↑ 转成用正斜杠分隔的字符串返回（跨平台统一格式）。
        except ValueError:
            # ↑ 如果路径不在项目根目录下，relative_to 会抛 ValueError，走这里。
            return Path(raw_path).name
            # ↑ 那就只返回文件名（basename），同样不暴露绝对路径。

    def format(self, record: logging.LogRecord) -> str:
        # ↑ 核心方法：把一条日志记录 record 格式化成最终字符串。

        message = record.getMessage()
        # ↑ 取出这条日志的文本内容。

        # 基础保护不等于万能脱敏；业务代码仍禁止记录 Token、请求体和配置对象。
        # ↑ 设计说明：这里的脱敏只是兜底，不能指望它兜住一切敏感信息。
        for secret in self._secrets:
            # ↑ 遍历所有需要脱敏的敏感字符串。
            if secret in message:
                # ↑ 如果日志内容里出现了这个敏感字符串……
                message = message.replace(secret, "[REDACTED]")
                # ↑ 就把它替换成 [REDACTED]（"已打码"）。
        data = {
            # ↑ 组装一条结构化日志，用一个字典装所有字段。
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            # ↑ 时间戳：把记录的创建时间转成带 UTC 时区的 ISO 格式字符串。
            "level": record.levelname,
            # ↑ 日志级别（DEBUG/INFO/WARNING/ERROR 等）。
            "logger": record.name,
            # ↑ 日志来源的名称（哪个模块打的）。
            "message": message,
            # ↑ 脱敏后的日志正文。
            "request_id": current_request_id(),
            # ↑ 当前请求的 ID，用于把同一请求的多条日志串起来。
        }
        if record.exc_info:
            # ↑ 如果这条日志带着异常信息（exc_info 不为空）……
            exc_type, _, tb = record.exc_info
            # ↑ 解包异常信息：异常类型、异常值（用 _ 忽略）、堆栈对象 tb。
            data["exception_type"] = exc_type.__name__ if exc_type else "unknown"
            # ↑ 只记录异常类型名（如 ValueError），不记录异常值。
            # 保留定位信息，但不包含异常值、源码行或局部变量，避免泄露 SQL 参数。
            # 路径一律转成项目根的相对路径，避免在响应/日志里出现本机绝对路径。
            # ↑ 上面的注释是设计说明。
            data["frames"] = "; ".join(
                # ↑ 把堆栈里的每一帧格式化后，用分号连成一行字符串。
                f"{self._relative_frame(frame.filename)}:{frame.lineno}:{frame.name}"
                # ↑ 每帧格式：相对路径:行号:函数名。
                for frame in traceback.extract_tb(tb)
                # ↑ extract_tb 把堆栈对象解成一个个 FrameSummary（每一帧）。
            )
        if self._json_output:
            # ↑ 如果是生产环境（需要 JSON）……
            return json.dumps(data, ensure_ascii=False)
            # ↑ 把字典转成 JSON 字符串返回（ensure_ascii=False 保留中文原文）。
        return " | ".join(f"{key}={value}" for key, value in data.items())
        # ↑ 否则（开发环境）用"键=值"的可读文本格式，用竖线分隔。


def configure_logging() -> None:
    # ↑ 全局日志配置函数：在应用启动时调用一次，设置好日志的格式和级别。

    settings = get_settings()
    # ↑ 读取配置单例（里面含密码、环境等）。

    formatter = SafeFormatter(
        # ↑ 创建上面定义的脱敏格式化器。
        secrets=(settings.DB_PASSWORD.get_secret_value(),),
        # ↑ 把数据库密码的真实值作为需要脱敏的敏感词传进去。
        json_output=settings.APP_ENV == "production",
        # ↑ 生产环境才输出 JSON。
        project_root=PROJECT_ROOT,
        # ↑ 项目根目录，用于相对路径转换。
    )
    handler = logging.StreamHandler(sys.stdout)
    # ↑ 创建一个日志处理器，把日志写到标准输出（终端/容器日志收集）。
    handler.setFormatter(formatter)
    # ↑ 让这个处理器使用我们的脱敏格式化器。
    root = logging.getLogger()
    # ↑ 拿到根日志器（所有日志的"总入口"）。
    root.handlers = [handler]
    # ↑ 把根日志器的处理器替换成我们刚建的这个（清掉默认的，避免重复打印）。
    root.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    # ↑ 设置日志级别：开了 DEBUG 就记录 DEBUG 及以上，否则只记 INFO 及以上。
    for name in ("uvicorn", "uvicorn.error", "sqlalchemy", "alembic"):
        # ↑ 逐个处理这些第三方库的日志器。
        logger = logging.getLogger(name)
        # ↑ 拿到对应名字的日志器。
        logger.handlers = []
        # ↑ 清空它自己的处理器（防止它自己打一遍，跟根日志器重复）。
        logger.propagate = True
        # ↑ 让它的日志向上"传播"到根日志器，由根日志器统一格式输出。
        logger.setLevel(logging.WARNING if name == "sqlalchemy" else logging.INFO)
        # ↑ sqlalchemy 太啰嗦，只记 WARNING 及以上；其他记 INFO 及以上。
    # Uvicorn 默认 access log 含完整查询串；模板默认关闭，避免未来 Token 泄漏。
    # ↑ 设计说明：uvicorn 的访问日志会打印完整 URL（可能含查询串里的敏感信息），
    #   所以干脆关掉它。
    logging.getLogger("uvicorn.access").disabled = True
    # ↑ 禁用 uvicorn 的访问日志。
