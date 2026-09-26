"""API 输入/输出：照搬 stu_table 的列；不是数据库表，不继承 ORM Base。"""

from pydantic import BaseModel, ConfigDict, Field


class StuCreate(BaseModel):
    # 不允许带外键创建请求里出现；客户端不该自己造主键。
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

    # PATCH：未传字段表示不动；显式 null 表示把数据库字段改成 NULL。
    # 学号与姓名如果允许 null，业务规则会冲突，请在 Router/Service 层拒绝。
    stu_number: str | None = Field(default=None, min_length=1, max_length=32)
    stu_name: str | None = Field(default=None, min_length=1, max_length=100)
    stu_class: str | None = Field(default=None, max_length=100)
    stu_major: str | None = Field(default=None, max_length=100)
    stu_college: str | None = Field(default=None, max_length=150)
    stu_phone: str | None = Field(default=None, max_length=32)
    stu_email: str | None = Field(default=None, max_length=255)
    stu_address: str | None = Field(default=None, max_length=255)


class StuResponse(BaseModel):
    # from_attributes=True 允许直接拿 ORM 对象构造响应；
    # 只在这里出现的字段才会被序列化，避免把内部属性意外暴露给客户端。
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