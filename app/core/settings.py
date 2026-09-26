"""配置只负责读取与校验，不创建数据库连接。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # 环境变量优先于 .env；固定项目根路径，避免从其他目录启动时误读配置。
    # 隐藏校验错误中的输入值，避免配置错误时连带打印密码。
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
    DEBUG: bool = False
    HOST: str = "127.0.0.1"
    PORT: int = Field(default=8000, ge=1, le=65535)

    # 运行时 DB 账号：理论上只需 SELECT/INSERT/UPDATE/DELETE。
    DB_HOST: str = Field(min_length=1)
    DB_PORT: int = Field(default=5432, ge=1, le=65535)
    DB_NAME: str = Field(min_length=1)
    DB_USER: str = Field(min_length=1)
    DB_PASSWORD: SecretStr

    # 迁移账号：独立配置时拥有 DDL；为空时回退到运行时账号（开发环境最常用）。
    # 迁移账号不要写进运行时日志；Alembic 在自己的进程里读取同一份 Settings。
    MIGRATION_DB_USER: str | None = None
    MIGRATION_DB_PASSWORD: SecretStr | None = None

    # 约束为普通小写标识符，减少 SQL 引号、大小写与工具兼容性差异。
    # 这不是默认值：缺失时直接阻止启动，不隐式回退到其他 Schema。
    DB_SCHEMA: str = Field(pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    DB_SSLMODE: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = (
        "prefer"
    )
    DB_SSLROOTCERT: Path | None = None
    DB_CONNECT_TIMEOUT: int = Field(default=5, ge=1, le=60)
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=100)
    DB_MAX_OVERFLOW: int = Field(default=5, ge=0, le=100)
    DB_POOL_TIMEOUT: float = Field(default=10, gt=0, le=120)
    # 单条 SQL 超过此秒数由数据库主动中止，避免慢查询把连接占满。
    DB_STATEMENT_TIMEOUT_MS: int = Field(default=30_000, ge=1_000, le=600_000)
    # 事务打开后空闲超过此秒数由数据库主动中止，避免应用 bug 留下长事务阻塞 vacuum / 持有锁。
    DB_IDLE_IN_TX_TIMEOUT_MS: int = Field(default=60_000, ge=1_000, le=600_000)
    HEALTH_TIMEOUT: float = Field(default=5, gt=0, le=60)
    # 任何 HTTP 请求体超过此字节数直接 413；防止恶意大 body 占内存。
    MAX_REQUEST_BODY_BYTES: int = Field(default=1_048_576, ge=1_024, le=33_554_432)
    # 关闭连接池时最多等待多久；超时只记日志，避免容器永远退不出。
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
    def production_debug(self) -> "Settings":
        if self.APP_ENV == "production" and self.DEBUG:
            raise ValueError("生产环境不能开启 DEBUG")
        # 迁移账号必须给出完整凭据：要么只给 user，要么 user/password 都给。
        # 半填的迁移账号会让生产环境悄悄退化为运行时权限。
        if self.MIGRATION_DB_USER is not None and self.MIGRATION_DB_PASSWORD is None:
            raise ValueError("设置了 MIGRATION_DB_USER 必须同时设置 MIGRATION_DB_PASSWORD")
        if self.MIGRATION_DB_PASSWORD is not None and self.MIGRATION_DB_USER is None:
            raise ValueError("设置了 MIGRATION_DB_PASSWORD 必须同时设置 MIGRATION_DB_USER")
        return self

    @property
    def database_url(self) -> URL:
        # URL 对象正确处理密码中的 @、:、% 等字符；不要把完整 URL 打印到日志。
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
        """迁移连接：独立账号优先；未配置时回退到运行时账号（开发环境）。

        返回的 URL 仍然由 ``MIGRATION_*`` 决定；运行时永远使用 ``database_url``。
        """
        user = self.MIGRATION_DB_USER or self.DB_USER
        password_secret = self.MIGRATION_DB_PASSWORD or self.DB_PASSWORD
        return URL.create(
            "postgresql+psycopg",
            username=user,
            password=password_secret.get_secret_value(),
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        )

    @property
    def connect_args(self) -> dict[str, str | int]:
        args: dict[str, str | int] = {
            "connect_timeout": self.DB_CONNECT_TIMEOUT,
            "sslmode": self.DB_SSLMODE,
            # 表通过 metadata 显式限定 Schema。固定系统查找路径，避免账号的
            # search_path 改变反射结果，或无 Schema SQL 意外访问其他业务表。
            # 同时设置 statement_timeout / idle_in_transaction_session_timeout，
            # 让数据库主动中止失控 SQL 与长事务，不依赖应用层超时。
            #
            # 注意：search_path=pg_catalog 不只影响 table，也会影响 type /
            # function / operator / extension object；以后用 pgvector / PostGIS
            # / uuid-ossp 等扩展时，按扩展默认 schema 做显式限定。
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
    # 同一进程复用配置；应用与迁移各自在自己的进程中读取。
    return Settings()
