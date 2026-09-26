"""教学示例的 Schema 校验。

重点：
- PATCH 语义下“未传”与“显式 null”必须能区分；
- NOT NULL 字段收到显式 null 直接 422，不让请求撞数据库变成 500；
- 可空字段的显式 null 仍然被允许。
"""

import pytest
from pydantic import ValidationError

from examples.student_crud.schema import StuCreate, StuUpdate

# ---------------------------------------------------------------------------
# StuUpdate：PATCH 字段语义
# ---------------------------------------------------------------------------


def test_stu_update_accepts_empty_payload():
    """PATCH 不传任何字段也算合法：调用方选择什么都不改。"""
    payload = StuUpdate.model_validate({})
    assert payload.model_fields_set == set()


def test_stu_update_omitted_and_explicit_null_are_distinguishable():
    """``model_fields_set`` 是区分“未传”与“显式 null”的唯一可靠依据。"""
    omitted = StuUpdate.model_validate({})
    explicit_none = StuUpdate.model_validate({"stu_class": None})

    assert "stu_class" not in omitted.model_fields_set
    assert omitted.stu_class is None  # 默认值

    assert "stu_class" in explicit_none.model_fields_set
    assert explicit_none.stu_class is None


def test_stu_update_accepts_explicit_null_on_nullable_field():
    """可空字段显式 null 必须被接受（清空语义）。"""
    payload = StuUpdate.model_validate({"stu_class": None, "stu_major": None, "stu_phone": None})
    assert payload.model_fields_set == {"stu_class", "stu_major", "stu_phone"}
    assert payload.stu_class is None
    assert payload.stu_major is None
    assert payload.stu_phone is None


def test_stu_update_rejects_explicit_null_on_not_null_field():
    """对 NOT NULL 字段显式 null 直接 422，不让 null 进 Service 撞数据库。"""
    with pytest.raises(ValidationError) as excinfo:
        StuUpdate.model_validate({"stu_name": None})
    assert "stu_name" in str(excinfo.value)
    assert "NOT NULL" in str(excinfo.value)


def test_stu_update_rejects_explicit_null_on_not_null_unique_field():
    with pytest.raises(ValidationError):
        StuUpdate.model_validate({"stu_number": None})


def test_stu_update_accepts_real_value_for_not_null_field():
    """正常更新值不被拒绝。"""
    payload = StuUpdate.model_validate({"stu_name": "张三", "stu_number": "S001"})
    assert payload.stu_name == "张三"
    assert payload.stu_number == "S001"
    assert payload.model_fields_set == {"stu_name", "stu_number"}


def test_stu_update_strips_whitespace():
    payload = StuUpdate.model_validate({"stu_name": "  张三  "})
    assert payload.stu_name == "张三"


def test_stu_update_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        StuUpdate.model_validate({"stu_id": 1, "stu_name": "x"})


def test_stu_update_rejects_blank_string_for_not_null_field():
    with pytest.raises(ValidationError):
        StuUpdate.model_validate({"stu_name": ""})


def test_exclude_unset_does_not_carry_omitted_fields():
    """``exclude_unset=True`` 后，``model_fields_set`` 之外的字段不出现在 dump 里。"""
    payload = StuUpdate.model_validate({"stu_name": "张三"})
    dumped = payload.model_dump(exclude_unset=True)
    assert dumped == {"stu_name": "张三"}
    assert "stu_class" not in dumped
    assert "stu_major" not in dumped


# ---------------------------------------------------------------------------
# StuCreate：POST 入参校验
# ---------------------------------------------------------------------------


def test_stu_create_requires_mandatory_fields():
    with pytest.raises(ValidationError):
        StuCreate.model_validate({"stu_number": "S001"})


def test_stu_create_rejects_explicit_null_on_required_field():
    with pytest.raises(ValidationError):
        StuCreate.model_validate({"stu_number": None, "stu_name": "张三"})


def test_stu_create_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        StuCreate.model_validate({"stu_number": "S001", "stu_name": "张三", "stu_id": 1})
