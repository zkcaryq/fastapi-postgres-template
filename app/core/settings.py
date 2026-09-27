"""配置只负责读取与校验，不创建数据库连接。"""
# ↑ 模块级 docstring：说明这个文件只做"读配置 + 校验"，不在这里建数据库连接。
#   真正的连接在别处（比如 db 会话模块）创建，职责分离。

from functools import lru_cache

# ↑ 导入 lru_cache 装饰器，用来缓存函数结果（这里用于让 Settings 只实例化一次）。
from pathlib import Path

# ↑ 导入 Path，用于跨平台处理文件路径。
from typing import Literal

# ↑ 导入 Literal，用于限定字段只能取指定的几个字面量值（类似枚举）。
from pydantic import Field, SecretStr, field_validator, model_validator

# ↑ 从 pydantic 导入：
#   - Field：给字段加默认值、约束（如最小长度、范围）。
#   - SecretStr：敏感字符串类型，repr/打印时不暴露内容。
#   - field_validator：单个字段的校验器装饰器。
#   - model_validator：整个模型级别的校验器装饰器（可访问多个字段）。
from pydantic_settings import BaseSettings, SettingsConfigDict

# ↑ 从 pydantic_settings 导入：
#   - BaseSettings：能从环境变量/.env 读取配置的基类。
#   - SettingsConfigDict：配置 BaseSettings 行为的字典类型（如 env_file）。
from sqlalchemy import URL

# ↑ 从 SQLAlchemy 导入 URL 类，用于安全地构造数据库连接 URL。

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# ↑ __file__ 是当前文件路径；.resolve() 转成绝对路径；
#   .parents[2] 往上两级：假设文件在 src/app/config.py，则 parents[0]=app, [1]=src, [2]=项目根。
#   这样无论从哪个目录启动程序，都能定位到项目根目录下的 .env。


class Settings(BaseSettings):
    # ↑ 定义配置类，继承 BaseSettings，实例化时自动读取环境变量和 .env。

    # 环境变量优先于 .env；固定项目根路径，避免从其他目录启动时误读配置。
    # 隐藏校验错误中的输入值，避免配置错误时连带打印密码。
    model_config = SettingsConfigDict(
        # ↑ 通过 model_config 配置 BaseSettings 的读取行为。
        env_file=PROJECT_ROOT / ".env",
        # ↑ 指定 .env 文件路径（项目根目录下）。
        env_file_encoding="utf-8",
        # ↑ .env 文件使用 UTF-8 编码读取。
        case_sensitive=True,
        # ↑ 环境变量名区分大小写（DB_HOST 与 db_host 不同）。
        extra="ignore",
        # ↑ 遇到未声明的环境变量时忽略，不报错（避免别人机器上多出的变量导致启动失败）。
        hide_input_in_errors=True,
        # ↑ 校验失败时不在错误信息里回显输入值，防止密码等敏感信息泄漏到日志。
        frozen=True,
        # ↑ 实例创建后不可修改字段（不可变对象），防止运行中被意外改动。
    )

    APP_NAME: str = Field(default="FastAPI Backend", min_length=1)
    # ↑ 应用名称，字符串，默认 "FastAPI Backend"，至少 1 个字符。

    APP_ENV: Literal["development", "testing", "production"] = "development"
    # ↑ 运行环境，只能是这三个值之一，默认 development。

    DEBUG: bool = False
    # ↑ 调试开关，布尔值，默认 False。

    HOST: str = "127.0.0.1"
    # ↑ 服务监听地址，默认本机回环地址。

    PORT: int = Field(default=8000, ge=1, le=65535)
    # ↑ 端口号，整数，默认 8000，范围 1~65535（ge=大于等于，le=小于等于）。

    # 运行时 DB 账号：理论上只需 SELECT/INSERT/UPDATE/DELETE。
    DB_HOST: str = Field(min_length=1)
    # ↑ 数据库主机，字符串，至少 1 字符（无默认值 → 必须提供）。

    DB_PORT: int = Field(default=5432, ge=1, le=65535)
    # ↑ 数据库端口，默认 5432（PostgreSQL 默认），范围 1~65535。

    DB_NAME: str = Field(min_length=1)
    # ↑ 数据库名，至少 1 字符，必须提供。

    DB_USER: str = Field(min_length=1)
    # ↑ 数据库用户名，至少 1 字符，必须提供。

    DB_PASSWORD: SecretStr
    # ↑ 数据库密码，SecretStr 类型，打印时不暴露内容，必须提供。

    # 迁移账号：独立配置时拥有 DDL；为空时回退到运行时账号（开发环境最常用）。
    # 迁移账号不要写进运行时日志；Alembic 在自己的进程里读取同一份 Settings。
    MIGRATION_DB_USER: str | None = None
    # ↑ 迁移用数据库用户名，可空，默认 None（表示不单独配置，回退到 DB_USER）。

    MIGRATION_DB_PASSWORD: SecretStr | None = None
    # ↑ 迁移用数据库密码，可空，默认 None（回退到 DB_PASSWORD）。

    # 约束为普通小写标识符，减少 SQL 引号、大小写与工具兼容性差异。
    # 这不是默认值：缺失时直接阻止启动，不隐式回退到其他 Schema。
    DB_SCHEMA: str = Field(pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    # ↑ 数据库 Schema 名，必须匹配正则：小写字母或下划线开头，后面可跟小写字母/数字/下划线，
    #   总长 1~63 字符（PostgreSQL 标识符上限）。没有默认值 → 必须显式提供。

    DB_SSLMODE: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = (
        "prefer"
    )
    # ↑ SSL 模式，只能是这 6 个值之一，默认 "prefer"（优先 SSL，连不上再退回明文）。
    #   括号换行只是为了满足行宽，不影响语义。

    DB_SSLROOTCERT: Path | None = None
    # ↑ SSL 根证书路径，可为 Path 或 None，默认 None（不校验根证书）。

    DB_CONNECT_TIMEOUT: int = Field(default=5, ge=1, le=60)
    # ↑ 建立连接超时秒数，默认 5，范围 1~60。

    DB_POOL_SIZE: int = Field(default=5, ge=1, le=100)
    # ↑ 连接池常驻连接数，默认 5，范围 1~100。

    DB_MAX_OVERFLOW: int = Field(default=5, ge=0, le=100)
    # ↑ 连接池溢出时可额外创建的连接数，默认 5，范围 0~100。

    DB_POOL_TIMEOUT: float = Field(default=10, gt=0, le=120)
    # ↑ 从连接池取连接的最长等待秒数，默认 10，范围 (0,120]（gt=大于）。

    # 单条 SQL 超过此秒数由数据库主动中止，避免慢查询把连接占满。
    DB_STATEMENT_TIMEOUT_MS: int = Field(default=30_000, ge=1_000, le=600_000)
    # ↑ 单条 SQL 语句超时毫秒数，默认 30000ms（30秒），范围 1000~600000。
    #   数字里的下划线是 Python 的可读性写法，等价于 30000。

    # 事务打开后空闲超过此秒数由数据库主动中止，避免应用 bug 留下长事务阻塞 vacuum / 持有锁。
    DB_IDLE_IN_TX_TIMEOUT_MS: int = Field(default=60_000, ge=1_000, le=600_000)
    # ↑ 事务空闲超时毫秒数，默认 60000ms（60秒），范围 1000~600000。

    HEALTH_TIMEOUT: float = Field(default=5, gt=0, le=60)
    # ↑ 健康检查超时秒数，默认 5，范围 (0,60]。

    # 任何 HTTP 请求体超过此字节数直接 413；防止恶意大 body 占内存。
    MAX_REQUEST_BODY_BYTES: int = Field(default=1_048_576, ge=1_024, le=33_554_432)
    # ↑ 请求体最大字节数，默认 1048576（1 MiB），范围 1024（1 KiB）~33554432（32 MiB）。

    # 关闭连接池时最多等待多久；超时只记日志，避免容器永远退不出。
    SHUTDOWN_TIMEOUT: float = Field(default=10, gt=0, le=60)
    # ↑ 关闭超时秒数，默认 10，范围 (0,60]。

    @field_validator("DB_PASSWORD")
    # ↑ 装饰器：为 DB_PASSWORD 字段注册一个校验函数。
    @classmethod
    # ↑ 声明为类方法（Pydantic v2 要求校验器是 classmethod）。
    def nonempty_password(cls, value: SecretStr) -> SecretStr:
        # ↑ 校验函数：接收字段值，返回处理后的值（或抛异常）。
        if not value.get_secret_value():
            # ↑ 取出真实密码内容，如果为空字符串……
            raise ValueError("DB_PASSWORD 不能为空")
            # ↑ 抛出错误，阻止启动。
        return value
        # ↑ 校验通过，原样返回。

    @field_validator("DB_SCHEMA")
    # ↑ 为 DB_SCHEMA 字段注册校验函数。
    @classmethod
    def application_schema(cls, value: str) -> str:
        # ↑ 校验 Schema 名是否是系统保留 Schema。
        if value.startswith("pg_") or value == "information_schema":
            # ↑ pg_ 开头的是 PostgreSQL 系统 Schema；information_schema 也是系统的。
            raise ValueError("不能使用 PostgreSQL 系统 Schema")
            # ↑ 报错，禁止使用系统 Schema。
        return value
        # ↑ 通过，返回原值。

    @field_validator("DB_HOST", "DB_NAME", "DB_USER", "APP_NAME", "HOST")
    # ↑ 一次性给这 5 个字段注册同一个校验函数。
    @classmethod
    def nonblank_value(cls, value: str) -> str:
        # ↑ 校验字符串不能只有空白字符。
        if not value.strip():
            # ↑ strip() 去掉首尾空白后为空 → 说明全是空白。
            raise ValueError("配置不能仅包含空白")
            # ↑ 报错。
        return value
        # ↑ 通过，返回原值。

    @model_validator(mode="after")
    # ↑ 模型级校验器：mode="after" 表示在所有字段都校验完之后再执行。
    def production_debug(self) -> "Settings":
        # ↑ 校验跨字段逻辑；返回 self（必须）。
        if self.APP_ENV == "production" and self.DEBUG:
            # ↑ 生产环境 + DEBUG=True 的组合……
            raise ValueError("生产环境不能开启 DEBUG")
            # ↑ 报错，禁止生产环境开调试。
        # 迁移账号必须给出完整凭据：要么只给 user，要么 user/password 都给。
        # 半填的迁移账号会让生产环境悄悄退化为运行时权限。
        if self.MIGRATION_DB_USER is not None and self.MIGRATION_DB_PASSWORD is None:
            # ↑ 只给了迁移用户名，却没给密码……
            raise ValueError("设置了 MIGRATION_DB_USER 必须同时设置 MIGRATION_DB_PASSWORD")
            # ↑ 报错，防止半配置导致权限悄悄降级。
        if self.MIGRATION_DB_PASSWORD is not None and self.MIGRATION_DB_USER is None:
            # ↑ 只给了迁移密码，却没给用户名……
            raise ValueError("设置了 MIGRATION_DB_PASSWORD 必须同时设置 MIGRATION_DB_USER")
            # ↑ 报错，同理。
        return self
        # ↑ 校验全部通过，返回自身。

    @property
    # ↑ 把方法变成属性，访问时不用加括号：settings.database_url。
    def database_url(self) -> URL:
        # ↑ 返回运行时数据库 URL 对象。
        # URL 对象正确处理密码中的 @、:、% 等字符；不要把完整 URL 打印到日志。
        return URL.create(
            # ↑ 用 SQLAlchemy 的工厂方法安全构造 URL。
            "postgresql+psycopg",
            # ↑ 驱动标识：PostgreSQL + psycopg（v3）。
            username=self.DB_USER,
            # ↑ 用户名。
            password=self.DB_PASSWORD.get_secret_value(),
            # ↑ 取出真实密码传入（URL.create 内部会做转义）。
            host=self.DB_HOST,
            # ↑ 主机。
            port=self.DB_PORT,
            # ↑ 端口。
            database=self.DB_NAME,
            # ↑ 数据库名。
        )

    @property
    def migration_database_url(self) -> URL:
        # ↑ 返回迁移用数据库 URL。
        """迁移连接：独立账号优先；未配置时回退到运行时账号（开发环境）。

        返回的 URL 仍然由 ``MIGRATION_*`` 决定；运行时永远使用 ``database_url``。
        """
        # ↑ docstring：说明回退规则和用途。
        user = self.MIGRATION_DB_USER or self.DB_USER
        # ↑ 如果配置了迁移用户名就用它，否则回退到运行时用户名。
        password_secret = self.MIGRATION_DB_PASSWORD or self.DB_PASSWORD
        # ↑ 同理处理密码（SecretStr 的 or 判断基于"是否为 None"）。
        return URL.create(
            # ↑ 构造 URL。
            "postgresql+psycopg",
            # ↑ 同样的驱动。
            username=user,
            # ↑ 上面选定的用户名。
            password=password_secret.get_secret_value(),
            # ↑ 上面选定的密码。
            host=self.DB_HOST,
            # ↑ 主机（运行时和迁移共用同一台）。
            port=self.DB_PORT,
            # ↑ 端口。
            database=self.DB_NAME,
            # ↑ 数据库名。
        )

    @property
    def connect_args(self) -> dict[str, str | int]:
        # ↑ 返回传给数据库驱动的连接参数字典。
        args: dict[str, str | int] = {
            # ↑ 显式标注类型：键为 str，值为 str 或 int。
            "connect_timeout": self.DB_CONNECT_TIMEOUT,
            # ↑ 连接超时（秒）。
            "sslmode": self.DB_SSLMODE,
            # ↑ SSL 模式。
            # 表通过 metadata 显式限定 Schema。固定系统查找路径，避免账号的
            # search_path 改变反射结果，或无 Schema SQL 意外访问其他业务表。
            # 同时设置 statement_timeout / idle_in_transaction_session_timeout，
            # 让数据库主动中止失控 SQL 与长事务，不依赖应用层超时。
            #
            # 注意：search_path=pg_catalog 不只影响 table，也会影响 type /
            # function / operator / extension object；以后用 pgvector / PostGIS
            # / uuid-ossp 等扩展时，按扩展默认 schema 做显式限定。
            "options": (
                # ↑ PostgreSQL 的 options 字符串，通过 -c 设置各种运行时参数。
                "-csearch_path=pg_catalog "
                # ↑ 只把 pg_catalog 放进搜索路径，防止误访问其他业务 Schema。
                "-ctimezone=UTC "
                # ↑ 时区统一 UTC，避免跨时区混乱。
                f"-cstatement_timeout={self.DB_STATEMENT_TIMEOUT_MS} "
                # ↑ f-string 插入语句超时毫秒数。
                f"-cidle_in_transaction_session_timeout={self.DB_IDLE_IN_TX_TIMEOUT_MS}"
                # ↑ 插入事务空闲超时毫秒数（最后一个没有尾随空格）。
            ),
        }
        if self.DB_SSLROOTCERT is not None:
            # ↑ 如果配置了 SSL 根证书路径……
            args["sslrootcert"] = str(self.DB_SSLROOTCERT)
            # ↑ 把 Path 转成字符串加入参数（驱动需要字符串）。
        return args
        # ↑ 返回最终参数字典。


@lru_cache(maxsize=1)
# ↑ 装饰器：缓存结果，maxsize=1 表示只缓存一次调用结果（即单例）。
def get_settings() -> Settings:
    # ↑ 工厂函数：返回全局唯一的 Settings 实例。
    # 同一进程复用配置；应用与迁移各自在自己的进程中读取。
    return Settings()
    # ↑ 第一次调用时创建 Settings（读环境变量+.env 并校验）；
    #   之后直接返回缓存对象，避免重复读取文件与校验。
