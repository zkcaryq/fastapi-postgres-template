"""教学示例 Model：PostgreSQL IDENTITY 主键与 NOT NULL 语义。"""
# ↑ 模块 docstring：测试学生表的模型定义（主键、约束）。

# 导入 BigInteger 和 Identity（用于类型判断）。
from sqlalchemy import BigInteger, Identity

# 导入学生表模型。
from examples.student_crud.model import StuTable


def test_stu_id_uses_postgres_identity():
    # ↑ 测试：主键应使用 PostgreSQL 的 IDENTITY，而不是 SERIAL/autoincrement。

    """主键应声明为 PostgreSQL IDENTITY，而不是 SERIAL / autoincrement。"""
    # ↑ docstring。
    stu_id = StuTable.__table__.c.stu_id
    # ↑ 通过模型取到 stu_id 列的定义（__table__.c 是"列集合"）。
    assert isinstance(stu_id.type, BigInteger)
    # ↑ 断言列类型是 BigInteger。
    # ``Identity()`` 必须出现在列定义里：autoincrement=True 会让 SQLAlchemy
    # 在 PostgreSQL 上回退到 SERIAL，与 IDENTITY 不等价。
    # ↑ 说明。
    assert stu_id.identity is not None
    # ↑ 断言列上有 identity 配置。
    assert isinstance(stu_id.identity, Identity)
    # ↑ 断言 identity 是 Identity 类型。
    # SQLAlchemy 给 Identity 列默认 ``autoincrement='auto'``，由 dialect 决定。
    # 关键是它**不是** ``True``（那会强制生成 SERIAL）。
    # ↑ 说明。
    assert stu_id.autoincrement is not True
    # ↑ 断言 autoincrement 不是 True（关键：True 会退化成 SERIAL）。


def test_stu_id_is_primary_key():
    # ↑ 测试：stu_id 是主键。

    stu_id = StuTable.__table__.c.stu_id
    # ↑ 取列定义。
    assert stu_id.primary_key is True
    # ↑ 断言是主键。


def test_stu_name_is_not_null():
    # ↑ 测试：姓名字段不允许为 NULL。

    stu_name = StuTable.__table__.c.stu_name
    # ↑ 取列定义。
    assert stu_name.nullable is False
    # ↑ 断言不可空。


def test_stu_number_is_unique_and_not_null():
    # ↑ 测试：学号既唯一又不可空。

    stu_number = StuTable.__table__.c.stu_number
    # ↑ 取列定义。
    assert stu_number.nullable is False
    # ↑ 断言不可空。
    assert stu_number.unique is True
    # ↑ 断言唯一。


def test_stu_class_is_nullable():
    # ↑ 测试：班级字段可空。

    stu_class = StuTable.__table__.c.stu_class
    # ↑ 取列定义。
    assert stu_class.nullable is True
    # ↑ 断言可空。
