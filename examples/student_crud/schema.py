"""教学示例：API 输入/输出 Schema。

PATCH 语义的三个关键点：

1. **未传字段**：保持数据库原值（在 Service 中用 ``model_dump(exclude_unset=True)`` 区分）；
2. **显式 ``null``**：如果对应列允许 NULL，把列改成 NULL；
3. **对 NOT NULL 字段显式 ``null``**：在请求校验阶段直接返回 ``422``，
   不让请求进 Service 后撞数据库变成 500。

``model_fields_set`` 是 Pydantic v2 提供的"本次输入里被显式给出"的字段集合，
与字段值无关。这是区分"未传"与"显式 null"的唯一可靠方式。
"""
# ↑ 模块 docstring：解释这个文件定义 API 的输入/输出结构，以及 PATCH 的
#   "未传 vs 显式 null" 难题（阶段 5 的核心内容）。

# 导入 Pydantic 的四个工具：
#   BaseModel 所有 Schema 的基类；ConfigDict 配置行为；Field 加约束；model_validator 模型校验器。
from pydantic import BaseModel, ConfigDict, Field, model_validator

# 数据库中 NOT NULL 的列在 PATCH 里不允许显式 null。
# 这是"业务字段 ↔ 数据库可空性"的契约：Schema 必须知道这点，
# 否则 null 进 Service 后会被 setattr 成 None，撞出 23502。
# ↑ 设计说明：解释下面这个集合的用途。
_NOT_NULL_DB_COLUMNS: frozenset[str] = frozenset({"stu_number", "stu_name"})
# ↑ 定义一个"不可变集合"，列出数据库里不允许为 NULL 的字段名。
#   frozenset 是不可变集合（和 set 的区别是不能修改），适合做常量。


class StuCreate(BaseModel):
    # ↑ 定义"创建学生"时客户端要提交的数据结构。

    # extra="forbid" 拒绝未知字段（含客户端伪造的主键）；
    # str_strip_whitespace=True 自动去掉首尾空白，避免脏数据进库。
    # ↑ 说明两个配置的含义。
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    # ↑ 配置：extra="forbid" 表示出现未声明字段就报错（拒绝 stu_id 这种伪造主键）；
    #   str_strip_whitespace=True 表示字符串字段自动去掉首尾空格。

    stu_number: str = Field(min_length=1, max_length=32)
    # ↑ "学号"字段：必填，长度 1~32。
    stu_name: str = Field(min_length=1, max_length=100)
    # ↑ "姓名"字段：必填，长度 1~100。
    stu_class: str | None = Field(default=None, max_length=100)
    # ↑ "班级"字段：可空，默认 None，最长 100。
    stu_major: str | None = Field(default=None, max_length=100)
    # ↑ "专业"字段：可空。
    stu_college: str | None = Field(default=None, max_length=150)
    # ↑ "学院"字段：可空。
    stu_phone: str | None = Field(default=None, max_length=32)
    # ↑ "手机号"字段：可空。
    stu_email: str | None = Field(default=None, max_length=255)
    # ↑ "邮箱"字段：可空。
    stu_address: str | None = Field(default=None, max_length=255)
    # ↑ "地址"字段：可空。


class StuUpdate(BaseModel):
    # ↑ 定义"更新学生"（PATCH）时客户端要提交的数据结构。

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    # ↑ 和 StuCreate 一样：拒绝未知字段、去首尾空白。

    # 这里允许 None 是为了在 Pydantic 序列化时类型合法；
    # 显式 null 是否被接受，交给下面的 model_validator 决定。
    # ↑ 说明：更新场景下所有字段都可空（因为可以"不改某个字段"），
    #   但"能不能显式传 null"由下面的校验器再判断。
    stu_number: str | None = Field(default=None, min_length=1, max_length=32)
    # ↑ "学号"字段：可空，默认 None（不传就表示不改这个字段）。
    stu_name: str | None = Field(default=None, min_length=1, max_length=100)
    # ↑ "姓名"字段：可空。
    stu_class: str | None = Field(default=None, max_length=100)
    # ↑ "班级"字段：可空。
    stu_major: str | None = Field(default=None, max_length=100)
    # ↑ "专业"字段：可空。
    stu_college: str | None = Field(default=None, max_length=150)
    # ↑ "学院"字段：可空。
    stu_phone: str | None = Field(default=None, max_length=32)
    # ↑ "手机号"字段：可空。
    stu_email: str | None = Field(default=None, max_length=255)
    # ↑ "邮箱"字段：可空。
    stu_address: str | None = Field(default=None, max_length=255)
    # ↑ "地址"字段：可空。

    @model_validator(mode="after")
    # ↑ 模型级校验器：在所有字段单独校验完成后执行（mode="after"）。
    def reject_explicit_null_for_not_null_columns(self) -> "StuUpdate":
        # ↑ 校验方法：拒绝"对 NOT NULL 字段显式传 null"。

        # model_fields_set 包含"输入里被显式给出"的字段，与字段值无关：
        # {"stu_name": null} → 包含 'stu_name'；{} → 不包含。
        # ↑ 说明 model_fields_set 的含义。
        for field in _NOT_NULL_DB_COLUMNS:
            # ↑ 遍历那些"数据库里不允许为 NULL"的字段。
            if field in self.model_fields_set and getattr(self, field) is None:
                # ↑ 如果这个字段在本次请求里被显式给出，且值是 None……
                raise ValueError(f"字段 {field} 在数据库中为 NOT NULL，不能显式设为 null")
                # ↑ 抛出错误，请求会变成 422（在进数据库前拦住）。
        return self
        # ↑ 校验通过，返回自身。


class StuResponse(BaseModel):
    # ↑ 定义"返回给客户端"的数据结构（响应模型）。

    # from_attributes=True 允许直接从 ORM 对象构造；
    # 只声明允许返回的字段，避免把内部属性意外暴露给客户端。
    # ↑ 说明两个点。
    model_config = ConfigDict(from_attributes=True)
    # ↑ 配置：from_attributes=True 表示可以从 ORM 对象（有属性的对象）直接构造，
    #   这样 Service 返回 ORM 对象时，FastAPI 能自动转成这个响应模型。

    stu_id: int
    # ↑ "主键 ID"：整数。
    stu_number: str
    # ↑ "学号"：字符串。
    stu_name: str
    # ↑ "姓名"：字符串。
    stu_class: str | None
    # ↑ "班级"：可空字符串。
    stu_major: str | None
    # ↑ "专业"：可空。
    stu_college: str | None
    # ↑ "学院"：可空。
    stu_phone: str | None
    # ↑ "手机号"：可空。
    stu_email: str | None
    # ↑ "邮箱"：可空。
    stu_address: str | None
    # ↑ "地址"：可空。
