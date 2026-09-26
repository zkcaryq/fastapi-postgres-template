"""教学示例：API 输入/输出 Schema。

PATCH 语义的三个关键点：

1. **未传字段**：保持数据库原值（在 Service 中用 ``model_dump(exclude_unset=True)`` 区分）；
2. **显式 ``null``**：如果对应列允许 NULL，把列改成 NULL；
3. **对 NOT NULL 字段显式 ``null``**：在请求校验阶段直接返回 ``422``，
   不让请求进 Service 后撞数据库变成 500。

``model_fields_set`` 是 Pydantic v2 提供的“本次输入里被显式给出”的字段集合，
与字段值无关。这是区分“未传”与“显式 null”的唯一可靠方式。
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 数据库中 NOT NULL 的列在 PATCH 里不允许显式 null。
# 这是“业务字段 ↔ 数据库可空性”的契约：Schema 必须知道这点，
# 否则 null 进 Service 后会被 setattr 成 None，撞出 23502。
_NOT_NULL_DB_COLUMNS: frozenset[str] = frozenset({"stu_number", "stu_name"})


class StuCreate(BaseModel):
    # extra="forbid" 拒绝未知字段（含客户端伪造的主键）；
    # str_strip_whitespace=True 自动去掉首尾空白，避免脏数据进库。
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    stu_number: str = Field(min_length=1, max_length=32)
    stu_name: str = Field(min_length=1, max_length=100)
    stu_class: str | None = Field(default=None, max_length=100)
    stu_major: str | None = Field(default=None, max_length=100)
    stu_college: str | None = Field(default=None, max_length=150)
    stu_phone: str | None = Field(default=None, max_length=32)
    stu_email: str | None = Field(default=None, max_length=255)
    stu_address: str | None = Field(default=None, max_length=255)


class StuUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # 这里允许 None 是为了在 Pydantic 序列化时类型合法；
    # 显式 null 是否被接受，交给下面的 model_validator 决定。
    stu_number: str | None = Field(default=None, min_length=1, max_length=32)
    stu_name: str | None = Field(default=None, min_length=1, max_length=100)
    stu_class: str | None = Field(default=None, max_length=100)
    stu_major: str | None = Field(default=None, max_length=100)
    stu_college: str | None = Field(default=None, max_length=150)
    stu_phone: str | None = Field(default=None, max_length=32)
    stu_email: str | None = Field(default=None, max_length=255)
    stu_address: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def reject_explicit_null_for_not_null_columns(self) -> "StuUpdate":
        # model_fields_set 包含“输入里被显式给出”的字段，与字段值无关：
        # {"stu_name": null} → 包含 'stu_name'；{} → 不包含。
        for field in _NOT_NULL_DB_COLUMNS:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"字段 {field} 在数据库中为 NOT NULL，不能显式设为 null")
        return self


class StuResponse(BaseModel):
    # from_attributes=True 允许直接从 ORM 对象构造；
    # 只声明允许返回的字段，避免把内部属性意外暴露给客户端。
    model_config = ConfigDict(from_attributes=True)

    stu_id: int
    stu_number: str
    stu_name: str
    stu_class: str | None
    stu_major: str | None
    stu_college: str | None
    stu_phone: str | None
    stu_email: str | None
    stu_address: str | None
