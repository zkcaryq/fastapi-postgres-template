"""应用配置：只负责读取与校验环境变量，不建立数据库连接。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """从系统环境变量和项目根目录的 .env 读取配置。"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        hide_input_in_errors=True,
        frozen=True,
    )

    APP_NAME: str = Field(default="FastAPI Backend", min_length=1)
    APP_ENV: Literal["development", "testing", "production"] = "development"
    HOST: str = "127.0.0.1"
    PORT: int = Field(default=8000, ge=1, le=65535)
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # 允许浏览器前端跨域访问的源；.env 覆盖值必须写成 JSON 数组。
    CORS_ORIGINS: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    # Bearer Token 不要求开启该选项；只有明确使用跨站 Cookie 等凭据时才开启。
    CORS_ALLOW_CREDENTIALS: bool = False

    DB_HOST: str = Field(min_length=1)
    DB_PORT: int = Field(default=5432, ge=1, le=65535)
    DB_NAME: str = Field(min_length=1)
    DB_USER: str = Field(min_length=1)
    DB_PASSWORD: SecretStr

    # 开发环境可留空并回退到运行账号；生产环境可配置单独的 DDL 账号。
    MIGRATION_DB_USER: str | None = None
    MIGRATION_DB_PASSWORD: SecretStr | None = None

    DB_SCHEMA: str = Field(pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    DB_SSLMODE: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = (
        "prefer"
    )
    DB_SSLROOTCERT: Path | None = None
    DB_CONNECT_TIMEOUT: int = Field(default=5, ge=1, le=60)
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=100)
    DB_MAX_OVERFLOW: int = Field(default=5, ge=0, le=100)
    DB_POOL_TIMEOUT: float = Field(default=10, gt=0, le=120)
    DB_STATEMENT_TIMEOUT_MS: int = Field(default=30_000, ge=1_000, le=600_000)
    DB_IDLE_IN_TX_TIMEOUT_MS: int = Field(default=60_000, ge=1_000, le=600_000)
    HEALTH_TIMEOUT: float = Field(default=5, gt=0, le=60)
    MAX_REQUEST_BODY_BYTES: int = Field(default=1_048_576, ge=1_024, le=33_554_432)
    SHUTDOWN_TIMEOUT: float = Field(default=10, gt=0, le=60)

    @field_validator("DB_PASSWORD")
    @classmethod
    def nonempty_password(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("DB_PASSWORD 不能为空")
        return value

    @field_validator("DB_SCHEMA")
    @classmethod
    def application_schema(cls, value: str) -> str:
        if value.startswith("pg_") or value == "information_schema":
            raise ValueError("不能使用 PostgreSQL 系统 Schema")
        return value

    @field_validator("DB_HOST", "DB_NAME", "DB_USER", "APP_NAME", "HOST")
    @classmethod
    def nonblank_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("配置不能仅包含空白")
        return value

    @model_validator(mode="after")
    def validate_cross_field_settings(self) -> "Settings":
        # 带凭据的CORS响应不能使用通配来源；启动时直接拒绝危险组合。
        if self.CORS_ALLOW_CREDENTIALS and "*" in self.CORS_ORIGINS:
            raise ValueError('CORS_ALLOW_CREDENTIALS=true 时不能使用 CORS_ORIGINS=["*"]')

        has_user = self.MIGRATION_DB_USER is not None
        has_password = self.MIGRATION_DB_PASSWORD is not None
        if has_user != has_password:
            raise ValueError("MIGRATION_DB_USER 和 MIGRATION_DB_PASSWORD 必须同时设置")
        return self

    @property
    def database_url(self) -> URL:
        """运行时连接；URL.create 会正确转义密码中的特殊字符。"""

        return URL.create(
            "postgresql+psycopg",
            username=self.DB_USER,
            password=self.DB_PASSWORD.get_secret_value(),
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        )

    @property
    def migration_database_url(self) -> URL:
        """Alembic 连接；没有单独配置时回退到运行时账号。"""

        user = self.MIGRATION_DB_USER or self.DB_USER
        password = self.MIGRATION_DB_PASSWORD or self.DB_PASSWORD
        return URL.create(
            "postgresql+psycopg",
            username=user,
            password=password.get_secret_value(),
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        )

    @property
    def connect_args(self) -> dict[str, str | int]:
        """传给 psycopg 的连接、SSL、时区和数据库级超时参数。"""

        args: dict[str, str | int] = {
            "connect_timeout": self.DB_CONNECT_TIMEOUT,
            "sslmode": self.DB_SSLMODE,
            "options": (
                "-csearch_path=pg_catalog "
                "-ctimezone=UTC "
                f"-cstatement_timeout={self.DB_STATEMENT_TIMEOUT_MS} "
                f"-cidle_in_transaction_session_timeout={self.DB_IDLE_IN_TX_TIMEOUT_MS}"
            ),
        }
        if self.DB_SSLROOTCERT is not None:
            args["sslrootcert"] = str(self.DB_SSLROOTCERT)
        return args


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """同一进程只读取并校验一次配置。"""

    return Settings()
