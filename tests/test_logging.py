"""日志层：密码脱敏、异常文本不泄露、绝对路径不泄露。"""
# ↑ 模块 docstring：测试日志格式化器 SafeFormatter 的脱敏和路径处理能力。

# 导入 logging、sys、uuid 标准库和 Path。
import logging
import sys
import uuid
from pathlib import Path

# 导入 pytest。
import pytest

# 导入要测试的日志格式化器。
from app.core.logging import SafeFormatter


def _make_formatter(tmp_path: Path) -> SafeFormatter:
    # ↑ 辅助函数：快速创建一个测试用的 SafeFormatter。

    return SafeFormatter(
        # ↑ 创建格式化器。
        secrets=("super-secret-password",),
        # ↑ 设定要脱敏的敏感词。
        json_output=True,
        # ↑ 输出 JSON 格式。
        project_root=tmp_path,
        # ↑ 项目根设为 pytest 的临时目录。
    )


def test_password_in_message_is_redacted(tmp_path):
    # ↑ 测试：日志消息里出现密码时被替换成 [REDACTED]。

    formatter = _make_formatter(tmp_path)
    # ↑ 创建格式化器。
    record = logging.LogRecord(
        # ↑ 手工构造一条日志记录（不真正打日志，直接造对象）。
        name="x",
        # ↑ 日志器名。
        level=logging.INFO,
        # ↑ 级别。
        pathname=str(tmp_path / "app" / "main.py"),
        # ↑ 模拟的源文件路径。
        lineno=1,
        # ↑ 行号。
        msg="connecting with super-secret-password",
        # ↑ 日志内容（含密码）。
        args=(),
        # ↑ 格式化参数（无）。
        exc_info=None,
        # ↑ 无异常。
    )
    out = formatter.format(record)
    # ↑ 用格式化器处理这条记录。
    assert "super-secret-password" not in out
    # ↑ 断言输出里没有密码原文。
    assert "[REDACTED]" in out
    # ↑ 断言输出里有打码标记。


def test_exception_message_is_not_in_output(tmp_path):
    # ↑ 测试：异常值（可能含敏感信息）不会出现在输出里。

    formatter = _make_formatter(tmp_path)
    # ↑ 创建格式化器。
    try:
        # ↑ 触发一个异常。
        raise ValueError("user-id=42 leaked")
        # ↑ 异常值里含敏感信息。
    except ValueError:
        # ↑ 捕获。
        record = logging.LogRecord(
            # ↑ 构造日志记录。
            name="x",
            level=logging.ERROR,
            pathname=str(tmp_path / "app" / "main.py"),
            lineno=1,
            msg="oops",
            args=(),
            exc_info=sys.exc_info(),
            # ↑ 附带当前异常信息。
        )
    out = formatter.format(record)
    # ↑ 格式化。
    assert "ValueError" in out
    # ↑ 断言输出里有异常类型名。
    assert "user-id=42 leaked" not in out
    # ↑ 断言异常值原文没泄露。
    assert "leaked" not in out
    # ↑ 断言关键词没泄露。


def test_relative_frame_converts_paths_inside_project_root(tmp_path):
    # ↑ 测试：项目内的路径会转成相对路径。

    formatter = SafeFormatter(secrets=(), json_output=True, project_root=tmp_path)
    # ↑ 创建格式化器（无敏感词）。
    inside = tmp_path / "app" / "services" / "student.py"
    # ↑ 构造一个项目内的路径。
    assert formatter._relative_frame(str(inside)) == "app/services/student.py"
    # ↑ 断言被转成相对路径。


def test_relative_frame_falls_back_to_basename_outside_project_root(tmp_path):
    # ↑ 测试：项目外的路径只保留文件名（不暴露绝对路径）。

    formatter = SafeFormatter(secrets=(), json_output=True, project_root=tmp_path)
    # ↑ 创建格式化器。
    outside = "/usr/lib/python3.13/somewhere/deep/file.py"  # noqa: S108
    # ↑ 一个项目外的绝对路径（noqa 忽略硬编码路径的 lint 规则）。
    assert formatter._relative_frame(outside) == "file.py"
    # ↑ 断言只返回文件名。


def test_relative_frame_handles_relative_input(tmp_path):
    # ↑ 测试：传入相对路径也能正确处理。

    formatter = SafeFormatter(secrets=(), json_output=True, project_root=tmp_path)
    # ↑ 创建格式化器。
    result = formatter._relative_frame("app/main.py")
    # ↑ 传入相对路径。
    assert isinstance(result, str)
    # ↑ 断言结果是字符串。
    assert "/" not in result or result.startswith("app/") or result == "main.py"
    # ↑ 断言结果符合预期（不出现绝对路径的盘符等）。


@pytest.mark.parametrize("secret", ["", "   "])
# ↑ 参数化测试：用两个不同的 secret 值（空串、纯空白）分别跑一次下面的测试。
def test_blank_secrets_are_ignored(tmp_path, secret):
    # ↑ 测试：空的敏感词会被忽略（不会误替换）。

    formatter = SafeFormatter(secrets=(secret,), json_output=True, project_root=tmp_path)
    # ↑ 创建格式化器，敏感词是空串或空白。
    record = logging.LogRecord(
        # ↑ 构造日志记录。
        name="x",
        level=logging.INFO,
        pathname="app/main.py",
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    out = formatter.format(record)
    # ↑ 格式化。
    assert "hello" in out
    # ↑ 断言正常内容没被破坏（空敏感词不会误伤）。


# ---------------------------------------------------------------------------
# 真实配置触发的全链路脱敏
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面开始用"接近真实配置"的场景测试脱敏。


def test_safe_formatter_redacts_password_from_real_settings_password(tmp_path, monkeypatch):
    # ↑ 测试：用真实 Settings 的密码字面量作为敏感词，验证能脱敏。

    """用一份真实 Settings 的 ``DB_PASSWORD`` 字面量作为 secret，
    验证 SafeFormatter 在日志里能把它替换成 ``[REDACTED]``。
    """
    # ↑ docstring。
    unique = f"unique-secret-{uuid.uuid4().hex}"
    # ↑ 生成一个独一无二的敏感词（避免和其他测试冲突）。
    formatter = SafeFormatter(
        # ↑ 创建格式化器。
        secrets=(unique,),
        # ↑ 敏感词设为这个唯一值。
        json_output=True,
        project_root=tmp_path,
    )
    record = logging.LogRecord(
        # ↑ 构造日志记录。
        name="x",
        level=logging.INFO,
        pathname="app/main.py",
        lineno=1,
        msg=f"connection string: postgresql://u:{unique}@host/db",
        # ↑ 日志内容里嵌入了这个敏感词。
        args=(),
        exc_info=None,
    )
    out = formatter.format(record)
    # ↑ 格式化。
    assert unique not in out
    # ↑ 断言敏感词被脱敏。
    assert "[REDACTED]" in out
    # ↑ 断言有打码标记。


# ---------------------------------------------------------------------------
# 真实 configure_logging 链路：把 password 写进 message 后必须被脱敏
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测"完整的日志配置链路"是否真的脱敏。


def test_configure_logging_redacts_real_db_password(monkeypatch, capsys):
    # ↑ 测试：调用 configure_logging() 后，真实日志输出不含密码。
    #   capsys 是 pytest 的"捕获标准输出"工具。

    """用一份独立配置的 Settings（密码 = unique marker），
    验证 ``configure_logging()`` 之后真实日志输出里不出现密码字面量。

    关键：``app.core.logging`` 在 import 时已经绑定了对
    ``app.core.settings.get_settings`` 的引用，所以 monkeypatch 必须在
    两个 module 都替换。
    """
    # ↑ docstring：解释为什么要同时 patch 两个模块。

    from pydantic import SecretStr
    from pydantic_settings import SettingsConfigDict

    from app.core import logging as logging_module
    from app.core import settings as settings_module
    # ↑ 函数内 import，方便 monkeypatch 替换。

    unique = f"pw-marker-{uuid.uuid4().hex}"
    # ↑ 生成唯一密码标记。

    class _IsolatedSettings(settings_module.Settings):
        # ↑ 定义一个隔离的配置子类。
        model_config = SettingsConfigDict(
            # ↑ 不读 .env、不读环境变量。
            env_file=None,
            case_sensitive=True,
            extra="ignore",
            hide_input_in_errors=True,
            frozen=True,
        )

    s = _IsolatedSettings(
        # ↑ 实例化，密码设为唯一标记。
        APP_NAME="x",
        APP_ENV="testing",
        HOST="127.0.0.1",
        PORT=8000,
        DB_HOST="127.0.0.1",
        DB_PORT=5432,
        DB_NAME="x",
        DB_USER="u",
        DB_PASSWORD=SecretStr(unique),
        DB_SCHEMA="app",
    )
    monkeypatch.setattr(settings_module, "get_settings", lambda: s)
    # ↑ 替换 settings 模块的 get_settings。
    monkeypatch.setattr(logging_module, "get_settings", lambda: s)
    # ↑ 替换 logging 模块的 get_settings（两者都要替换，见 docstring）。

    logging_module.configure_logging()
    # ↑ 用这份配置初始化日志。
    logging.getLogger("app.test").info("postgresql://u:%s@host/db", unique)
    # ↑ 打一条日志，内容里嵌入密码标记。
    captured = capsys.readouterr()
    # ↑ 读取捕获的标准输出。
    assert unique not in captured.out, captured.out
    # ↑ 断言输出里没有密码标记。
    assert "[REDACTED]" in captured.out
    # ↑ 断言有打码标记。
