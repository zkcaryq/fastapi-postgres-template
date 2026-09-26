"""教学示例 Model：PostgreSQL IDENTITY 主键与 NOT NULL 语义。"""

from sqlalchemy import BigInteger, Identity

from examples.student_crud.model import StuTable


def test_stu_id_uses_postgres_identity():
    """主键应声明为 PostgreSQL IDENTITY，而不是 SERIAL / autoincrement。"""
    stu_id = StuTable.__table__.c.stu_id
    assert isinstance(stu_id.type, BigInteger)
    # ``Identity()`` 必须出现在列定义里：autoincrement=True 会让 SQLAlchemy
    # 在 PostgreSQL 上回退到 SERIAL，与 IDENTITY 不等价。
    assert stu_id.identity is not None
    assert isinstance(stu_id.identity, Identity)
    # SQLAlchemy 给 Identity 列默认 ``autoincrement='auto'``，由 dialect 决定。
    # 关键是它**不是** ``True``（那会强制生成 SERIAL）。
    assert stu_id.autoincrement is not True


def test_stu_id_is_primary_key():
    stu_id = StuTable.__table__.c.stu_id
    assert stu_id.primary_key is True


def test_stu_name_is_not_null():
    stu_name = StuTable.__table__.c.stu_name
    assert stu_name.nullable is False


def test_stu_number_is_unique_and_not_null():
    stu_number = StuTable.__table__.c.stu_number
    assert stu_number.nullable is False
    assert stu_number.unique is True


def test_stu_class_is_nullable():
    stu_class = StuTable.__table__.c.stu_class
    assert stu_class.nullable is True
