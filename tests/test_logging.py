"""日志层：密码脱敏、异常文本不泄露、绝对路径不泄露。"""

import logging
import sys
import uuid
from pathlib import Path

import pytest

from app.core.logging import SafeFormatter


def _make_formatter(tmp_path: Path) -> SafeFormatter:
    return SafeFormatter(
        secrets=("super-secret-password",),
        json_output=True,
        project_root=tmp_path,
    )


def test_password_in_message_is_redacted(tmp_path):
    formatter = _make_formatter(tmp_path)
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=str(tmp_path / "app" / "main.py"),
        lineno=1,
        msg="connecting with super-secret-password",
        args=(),
        exc_info=None,
    )
    out = formatter.format(record)
    assert "super-secret-password" not in out
    assert "[REDACTED]" in out


def test_exception_message_is_not_in_output(tmp_path):
    formatter = _make_formatter(tmp_path)
    try:
        raise ValueError("user-id=42 leaked")
    except ValueError:
        record = logging.LogRecord(
            name="x",
            level=logging.ERROR,
            pathname=str(tmp_path / "app" / "main.py"),
            lineno=1,
            msg="oops",
            args=(),
            exc_info=sys.exc_info(),
        )
    out = formatter.format(record)
    assert "ValueError" in out
    assert "user-id=42 leaked" not in out
    assert "leaked" not in out


def test_relative_frame_converts_paths_inside_project_root(tmp_path):
    formatter = SafeFormatter(secrets=(), json_output=True, project_root=tmp_path)
    inside = tmp_path / "app" / "services" / "student.py"
    assert formatter._relative_frame(str(inside)) == "app/services/student.py"


def test_relative_frame_falls_back_to_basename_outside_project_root(tmp_path):
    formatter = SafeFormatter(secrets=(), json_output=True, project_root=tmp_path)
    outside = "/usr/lib/python3.13/somewhere/deep/file.py"  # noqa: S108
    assert formatter._relative_frame(outside) == "file.py"


def test_relative_frame_handles_relative_input(tmp_path):
    formatter = SafeFormatter(secrets=(), json_output=True, project_root=tmp_path)
    result = formatter._relative_frame("app/main.py")
    assert isinstance(result, str)
    assert "/" not in result or result.startswith("app/") or result == "main.py"


@pytest.mark.parametrize("secret", ["", "   "])
def test_blank_secrets_are_ignored(tmp_path, secret):
    formatter = SafeFormatter(secrets=(secret,), json_output=True, project_root=tmp_path)
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname="app/main.py",
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    out = formatter.format(record)
    assert "hello" in out


# ---------------------------------------------------------------------------
# 真实配置触发的全链路脱敏
# ---------------------------------------------------------------------------


def test_safe_formatter_redacts_password_from_real_settings_password(tmp_path, monkeypatch):
    """用一份真实 Settings 的 ``DB_PASSWORD`` 字面量作为 secret，
    验证 SafeFormatter 在日志里能把它替换成 ``[REDACTED]``。
    """
    unique = f"unique-secret-{uuid.uuid4().hex}"
    formatter = SafeFormatter(
        secrets=(unique,),
        json_output=True,
        project_root=tmp_path,
    )
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname="app/main.py",
        lineno=1,
        msg=f"connection string: postgresql://u:{unique}@host/db",
        args=(),
        exc_info=None,
    )
    out = formatter.format(record)
    assert unique not in out
    assert "[REDACTED]" in out


# ---------------------------------------------------------------------------
# 真实 configure_logging 链路：把 password 写进 message 后必须被脱敏
# ---------------------------------------------------------------------------


def test_configure_logging_redacts_real_db_password(monkeypatch, capsys):
    """用一份独立配置的 Settings（密码 = unique marker），
    验证 ``configure_logging()`` 之后真实日志输出里不出现密码字面量。

    关键：``app.core.logging`` 在 import 时已经绑定了对
    ``app.core.settings.get_settings`` 的引用，所以 monkeypatch 必须在
    两个 module 都替换。
    """
    from pydantic import SecretStr
    from pydantic_settings import SettingsConfigDict

    from app.core import logging as logging_module
    from app.core import settings as settings_module

    unique = f"pw-marker-{uuid.uuid4().hex}"

    class _IsolatedSettings(settings_module.Settings):
        model_config = SettingsConfigDict(
            env_file=None,
            case_sensitive=True,
            extra="ignore",
            hide_input_in_errors=True,
            frozen=True,
        )

    s = _IsolatedSettings(
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
    monkeypatch.setattr(logging_module, "get_settings", lambda: s)

    logging_module.configure_logging()
    logging.getLogger("app.test").info("postgresql://u:%s@host/db", unique)
    captured = capsys.readouterr()
    assert unique not in captured.out, captured.out
    assert "[REDACTED]" in captured.out
