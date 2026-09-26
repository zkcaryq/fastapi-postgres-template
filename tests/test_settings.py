"""配置层校验：必填、非法 Schema、production + DEBUG、shutdown timeout、迁移账号回退。"""

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from pydantic_settings import SettingsConfigDict

from app.core.settings import Settings


def _build_isolated_settings_cls(monkeypatch):
    """构造一个不读 .env 也不读 os.environ 的 Settings 子类用于测试。"""

    for key in (
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

    class _IsolatedSettings(Settings):
        model_config = SettingsConfigDict(
            env_file=None,
            case_sensitive=True,
            extra="ignore",
            hide_input_in_errors=True,
            frozen=True,
        )

    return _IsolatedSettings


def _base_kwargs(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "DB_HOST": "127.0.0.1",
        "DB_PORT": 5432,
        "DB_NAME": "test_db",
        "DB_USER": "test_user",
        "DB_PASSWORD": SecretStr("test-password-not-a-real-secret"),
        "DB_SCHEMA": "app_schema",
    }
    data.update(overrides)
    return data


def test_minimum_required_settings_succeed(monkeypatch):
    cls = _build_isolated_settings_cls(monkeypatch)
    settings = cls(**_base_kwargs())
    assert settings.DB_SCHEMA == "app_schema"
    assert settings.SHUTDOWN_TIMEOUT == 10


def test_missing_db_schema_is_rejected(monkeypatch):
    cls = _build_isolated_settings_cls(monkeypatch)
    data = _base_kwargs()
    data.pop("DB_SCHEMA")
    with pytest.raises(ValidationError):
        cls(**data)


def test_invalid_schema_pattern_is_rejected(monkeypatch):
    cls = _build_isolated_settings_cls(monkeypatch)
    with pytest.raises(ValidationError):
        cls(**_base_kwargs(DB_SCHEMA="1_leading_digit"))


def test_system_schema_is_rejected(monkeypatch):
    cls = _build_isolated_settings_cls(monkeypatch)
    with pytest.raises(ValidationError):
        cls(**_base_kwargs(DB_SCHEMA="pg_catalog"))


def test_empty_password_is_rejected(monkeypatch):
    cls = _build_isolated_settings_cls(monkeypatch)
    with pytest.raises(ValidationError):
        cls(**_base_kwargs(DB_PASSWORD=SecretStr("")))


def test_blank_host_is_rejected(monkeypatch):
    cls = _build_isolated_settings_cls(monkeypatch)
    with pytest.raises(ValidationError):
        cls(**_base_kwargs(DB_HOST="   "))


def test_production_cannot_enable_debug(monkeypatch):
    cls = _build_isolated_settings_cls(monkeypatch)
    with pytest.raises(ValidationError):
        cls(**_base_kwargs(APP_ENV="production", DEBUG=True))


def test_shutdown_timeout_bounds(monkeypatch):
    cls = _build_isolated_settings_cls(monkeypatch)
    with pytest.raises(ValidationError):
        cls(**_base_kwargs(SHUTDOWN_TIMEOUT=0))
    with pytest.raises(ValidationError):
        cls(**_base_kwargs(SHUTDOWN_TIMEOUT=61))


def test_migration_user_without_password_is_rejected(monkeypatch):
    cls = _build_isolated_settings_cls(monkeypatch)
    with pytest.raises(ValidationError, match="必须同时设置 MIGRATION_DB_PASSWORD"):
        cls(**_base_kwargs(MIGRATION_DB_USER="migration_user"))


def test_migration_password_without_user_is_rejected(monkeypatch):
    cls = _build_isolated_settings_cls(monkeypatch)
    with pytest.raises(ValidationError, match="必须同时设置 MIGRATION_DB_USER"):
        cls(**_base_kwargs(MIGRATION_DB_PASSWORD=SecretStr("migration-secret")))


def test_migration_url_falls_back_to_runtime_when_not_configured(monkeypatch):
    cls = _build_isolated_settings_cls(monkeypatch)
    settings = cls(**_base_kwargs())
    assert settings.migration_database_url.username == settings.DB_USER
    assert settings.migration_database_url.password == settings.DB_PASSWORD.get_secret_value()


def test_migration_url_uses_independent_account_when_configured(monkeypatch):
    cls = _build_isolated_settings_cls(monkeypatch)
    settings = cls(
        **_base_kwargs(
            MIGRATION_DB_USER="migration_user",
            MIGRATION_DB_PASSWORD=SecretStr("migration-secret"),
        )
    )
    assert settings.migration_database_url.username == "migration_user"
    assert settings.migration_database_url.password == "migration-secret"
    assert settings.database_url.username == "test_user"


def test_runtime_url_always_uses_runtime_account(monkeypatch):
    """即使配了迁移账号，运行时连接也只用运行时账号。"""
    cls = _build_isolated_settings_cls(monkeypatch)
    settings = cls(
        **_base_kwargs(
            MIGRATION_DB_USER="migration_user",
            MIGRATION_DB_PASSWORD=SecretStr("migration-secret"),
        )
    )
    assert settings.database_url.username == "test_user"
    assert settings.database_url.password == "test-password-not-a-real-secret"
