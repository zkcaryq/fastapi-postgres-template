"""配置层校验：必填、非法 Schema、production + DEBUG、shutdown timeout、迁移账号回退。"""
# ↑ 模块 docstring：测试配置类 Settings 的各种校验规则。

# 导入 Any（任意类型标注）。
from typing import Any

# 导入 pytest、pydantic 的 SecretStr 和 ValidationError、SettingsConfigDict。
import pytest
from pydantic import SecretStr, ValidationError
from pydantic_settings import SettingsConfigDict

# 导入要测试的配置类。
from app.core.settings import Settings


def _build_isolated_settings_cls(monkeypatch):
    # ↑ 辅助函数：构造一个"完全隔离"的 Settings 子类——既不读 .env 也不读环境变量，
    #   这样测试不会受本机真实配置干扰。

    """构造一个不读 .env 也不读 os.environ 的 Settings 子类用于测试。"""
    # ↑ docstring。

    for key in (
        # ↑ 遍历所有配置项的名字。
        "APP_NAME",
        "APP_ENV",
        "DEBUG",
        "HOST",
        "PORT",
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "MIGRATION_DB_USER",
        "MIGRATION_DB_PASSWORD",
        "DB_SCHEMA",
        "DB_SSLMODE",
        "DB_CONNECT_TIMEOUT",
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT",
        "DB_STATEMENT_TIMEOUT_MS",
        "DB_IDLE_IN_TX_TIMEOUT_MS",
        "HEALTH_TIMEOUT",
        "MAX_REQUEST_BODY_BYTES",
        "SHUTDOWN_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)
        # ↑ 逐个删掉这些环境变量（raising=False 表示"不存在也不报错"），
        #   确保测试环境干净，不受本机环境变量影响。

    class _IsolatedSettings(Settings):
        # ↑ 定义一个继承 Settings 的子类。
        model_config = SettingsConfigDict(
            # ↑ 覆盖配置：不读 .env 文件。
            env_file=None,
            # ↑ 关键：不读 .env。
            case_sensitive=True,
            # ↑ 区分大小写。
            extra="ignore",
            # ↑ 忽略未知变量。
            hide_input_in_errors=True,
            # ↑ 报错时不回显输入值。
            frozen=True,
            # ↑ 不可变。
        )

    return _IsolatedSettings
    # ↑ 返回这个隔离的配置类。


def _base_kwargs(**overrides: Any) -> dict[str, Any]:
    # ↑ 辅助函数：构造一份"最小合法配置"的字典，可用 overrides 覆盖个别字段。

    data: dict[str, Any] = {
        # ↑ 基础配置字典。
        "DB_HOST": "127.0.0.1",
        # ↑ 主机。
        "DB_PORT": 5432,
        # ↑ 端口。
        "DB_NAME": "test_db",
        # ↑ 库名。
        "DB_USER": "test_user",
        # ↑ 用户名。
        "DB_PASSWORD": SecretStr("test-password-not-a-real-secret"),
        # ↑ 密码（用 SecretStr 包装，因为是测试占位值，明确非真实）。
        "DB_SCHEMA": "app_schema",
        # ↑ Schema 名。
    }
    data.update(overrides)
    # ↑ 用传入的覆盖值更新字典。
    return data
    # ↑ 返回。


def test_minimum_required_settings_succeed(monkeypatch):
    # ↑ 测试：最小必填配置能正常通过校验。

    cls = _build_isolated_settings_cls(monkeypatch)
    # ↑ 拿到隔离配置类。
    settings = cls(**_base_kwargs())
    # ↑ 用最小配置实例化。
    assert settings.DB_SCHEMA == "app_schema"
    # ↑ 断言 Schema 正确。
    assert settings.SHUTDOWN_TIMEOUT == 10
    # ↑ 断言默认关闭超时是 10 秒（未传时用默认值）。


def test_missing_db_schema_is_rejected(monkeypatch):
    # ↑ 测试：缺 DB_SCHEMA 时校验失败。

    cls = _build_isolated_settings_cls(monkeypatch)
    # ↑ 隔离类。
    data = _base_kwargs()
    # ↑ 基础配置。
    data.pop("DB_SCHEMA")
    # ↑ 删掉 Schema（模拟缺失）。
    with pytest.raises(ValidationError):
        # ↑ 断言会抛 ValidationError。
        cls(**data)
        # ↑ 实例化（应该失败）。


def test_invalid_schema_pattern_is_rejected(monkeypatch):
    # ↑ 测试：Schema 名以数字开头（违反正则）时校验失败。

    cls = _build_isolated_settings_cls(monkeypatch)
    # ↑ 隔离类。
    with pytest.raises(ValidationError):
        # ↑ 断言抛错。
        cls(**_base_kwargs(DB_SCHEMA="1_leading_digit"))
        # ↑ 传入以数字开头的非法 Schema 名。


def test_system_schema_is_rejected(monkeypatch):
    # ↑ 测试：用系统 Schema（pg_catalog）时校验失败。

    cls = _build_isolated_settings_cls(monkeypatch)
    # ↑ 隔离类。
    with pytest.raises(ValidationError):
        # ↑ 断言抛错。
        cls(**_base_kwargs(DB_SCHEMA="pg_catalog"))
        # ↑ 传入系统 Schema。


def test_empty_password_is_rejected(monkeypatch):
    # ↑ 测试：空密码校验失败。

    cls = _build_isolated_settings_cls(monkeypatch)
    # ↑ 隔离类。
    with pytest.raises(ValidationError):
        # ↑ 断言抛错。
        cls(**_base_kwargs(DB_PASSWORD=SecretStr("")))
        # ↑ 传入空密码。


def test_blank_host_is_rejected(monkeypatch):
    # ↑ 测试：全是空白的主机名校验失败。

    cls = _build_isolated_settings_cls(monkeypatch)
    # ↑ 隔离类。
    with pytest.raises(ValidationError):
        # ↑ 断言抛错。
        cls(**_base_kwargs(DB_HOST="   "))
        # ↑ 传入纯空白主机名。


def test_production_cannot_enable_debug(monkeypatch):
    # ↑ 测试：生产环境 + DEBUG 开启时校验失败。

    cls = _build_isolated_settings_cls(monkeypatch)
    # ↑ 隔离类。
    with pytest.raises(ValidationError):
        # ↑ 断言抛错。
        cls(**_base_kwargs(APP_ENV="production", DEBUG=True))
        # ↑ 生产环境 + DEBUG=True（非法组合）。


def test_shutdown_timeout_bounds(monkeypatch):
    # ↑ 测试：关闭超时必须在 (0, 60] 范围内。

    cls = _build_isolated_settings_cls(monkeypatch)
    # ↑ 隔离类。
    with pytest.raises(ValidationError):
        # ↑ 断言抛错。
        cls(**_base_kwargs(SHUTDOWN_TIMEOUT=0))
        # ↑ 超时 0（非法，必须 >0）。
    with pytest.raises(ValidationError):
        # ↑ 再断言一次。
        cls(**_base_kwargs(SHUTDOWN_TIMEOUT=61))
        # ↑ 超时 61（非法，必须 ≤60）。


def test_migration_user_without_password_is_rejected(monkeypatch):
    # ↑ 测试：只配迁移用户名、不配密码时校验失败。

    cls = _build_isolated_settings_cls(monkeypatch)
    # ↑ 隔离类。
    with pytest.raises(ValidationError, match="必须同时设置 MIGRATION_DB_PASSWORD"):
        # ↑ 断言抛错，且错误信息包含指定文本。
        cls(**_base_kwargs(MIGRATION_DB_USER="migration_user"))
        # ↑ 只给迁移用户名。


def test_migration_password_without_user_is_rejected(monkeypatch):
    # ↑ 测试：只配迁移密码、不配用户名时校验失败。

    cls = _build_isolated_settings_cls(monkeypatch)
    # ↑ 隔离类。
    with pytest.raises(ValidationError, match="必须同时设置 MIGRATION_DB_USER"):
        # ↑ 断言抛错，且包含指定文本。
        cls(**_base_kwargs(MIGRATION_DB_PASSWORD=SecretStr("migration-secret")))
        # ↑ 只给迁移密码。


def test_migration_url_falls_back_to_runtime_when_not_configured(monkeypatch):
    # ↑ 测试：未配迁移账号时，迁移 URL 回退用运行时账号。

    cls = _build_isolated_settings_cls(monkeypatch)
    # ↑ 隔离类。
    settings = cls(**_base_kwargs())
    # ↑ 基础配置（无迁移账号）。
    assert settings.migration_database_url.username == settings.DB_USER
    # ↑ 断言迁移 URL 的用户名回退为运行时用户名。
    assert settings.migration_database_url.password == settings.DB_PASSWORD.get_secret_value()
    # ↑ 断言迁移 URL 的密码回退为运行时密码。


def test_migration_url_uses_independent_account_when_configured(monkeypatch):
    # ↑ 测试：配了迁移账号时，迁移 URL 用独立的迁移账号。

    cls = _build_isolated_settings_cls(monkeypatch)
    # ↑ 隔离类。
    settings = cls(
        # ↑ 实例化。
        **_base_kwargs(
            # ↑ 基础配置。
            MIGRATION_DB_USER="migration_user",
            # ↑ 迁移用户名。
            MIGRATION_DB_PASSWORD=SecretStr("migration-secret"),
            # ↑ 迁移密码。
        )
    )
    assert settings.migration_database_url.username == "migration_user"
    # ↑ 断言迁移 URL 用迁移用户名。
    assert settings.migration_database_url.password == "migration-secret"
    # ↑ 断言迁移 URL 用迁移密码。
    assert settings.database_url.username == "test_user"
    # ↑ 断言运行时 URL 仍用运行时用户名（两者独立）。


def test_runtime_url_always_uses_runtime_account(monkeypatch):
    # ↑ 测试：即使配了迁移账号，运行时 URL 也只用运行时账号。

    """即使配了迁移账号，运行时连接也只用运行时账号。"""
    # ↑ docstring。
    cls = _build_isolated_settings_cls(monkeypatch)
    # ↑ 隔离类。
    settings = cls(
        # ↑ 实例化。
        **_base_kwargs(
            # ↑ 基础配置。
            MIGRATION_DB_USER="migration_user",
            # ↑ 迁移用户名。
            MIGRATION_DB_PASSWORD=SecretStr("migration-secret"),
            # ↑ 迁移密码。
        )
    )
    assert settings.database_url.username == "test_user"
    # ↑ 断言运行时用户名仍是 test_user。
    assert settings.database_url.password == "test-password-not-a-real-secret"
    # ↑ 断言运行时密码仍是原来的。
