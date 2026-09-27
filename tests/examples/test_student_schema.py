"""教学示例的 Schema 校验。

重点：
- PATCH 语义下"未传"与"显式 null"必须能区分；
- NOT NULL 字段收到显式 null 直接 422，不让请求撞数据库变成 500；
- 可空字段的显式 null 仍然被允许。
"""
# ↑ 模块 docstring：测试学生 Schema 的校验规则，尤其是 PATCH 的"未传 vs 显式 null"。

# 导入 pytest 和 Pydantic 的 ValidationError。
import pytest
from pydantic import ValidationError

# 导入学生 Schema（创建和更新）。
from examples.student_crud.schema import StuCreate, StuUpdate

# ---------------------------------------------------------------------------
# StuUpdate：PATCH 字段语义
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测"更新"（PATCH）语义。


def test_stu_update_accepts_empty_payload():
    # ↑ 测试：PATCH 传空对象（什么都不改）也是合法的。

    """PATCH 不传任何字段也算合法：调用方选择什么都不改。"""
    # ↑ docstring。
    payload = StuUpdate.model_validate({})
    # ↑ 用空字典构造更新对象。
    assert payload.model_fields_set == set()
    # ↑ 断言"本次显式给出的字段集合"是空集。


def test_stu_update_omitted_and_explicit_null_are_distinguishable():
    # ↑ 测试："未传"和"显式 null"能被区分开。

    """``model_fields_set`` 是区分"未传"与"显式 null"的唯一可靠依据。"""
    # ↑ docstring。
    omitted = StuUpdate.model_validate({})
    # ↑ 空对象（什么都没传）。
    explicit_none = StuUpdate.model_validate({"stu_class": None})
    # ↑ 显式传了 stu_class=null。

    assert "stu_class" not in omitted.model_fields_set
    # ↑ 断言"未传"场景里，stu_class 不在"显式给出"集合里。
    assert omitted.stu_class is None  # 默认值
    # ↑ 断言未传时它的值是默认值 None。

    assert "stu_class" in explicit_none.model_fields_set
    # ↑ 断言"显式 null"场景里，stu_class 在"显式给出"集合里。
    assert explicit_none.stu_class is None
    # ↑ 断言值也是 None（但语义不同：这次是"显式清空"）。


def test_stu_update_accepts_explicit_null_on_nullable_field():
    # ↑ 测试：可空字段允许显式传 null（清空语义）。

    """可空字段显式 null 必须被接受（清空语义）。"""
    # ↑ docstring。
    payload = StuUpdate.model_validate({"stu_class": None, "stu_major": None, "stu_phone": None})
    # ↑ 显式传三个可空字段为 null。
    assert payload.model_fields_set == {"stu_class", "stu_major", "stu_phone"}
    # ↑ 断言这三个字段都在"显式给出"集合里。
    assert payload.stu_class is None
    # ↑ 断言值都是 None。
    assert payload.stu_major is None
    # ↑ 同上。
    assert payload.stu_phone is None
    # ↑ 同上。


def test_stu_update_rejects_explicit_null_on_not_null_field():
    # ↑ 测试：对 NOT NULL 字段显式传 null 会被拒绝（422）。

    """对 NOT NULL 字段显式 null 直接 422，不让 null 进 Service 撞数据库。"""
    # ↑ docstring。
    with pytest.raises(ValidationError) as excinfo:
        # ↑ 断言会抛 ValidationError，并捕获异常对象。
        StuUpdate.model_validate({"stu_name": None})
        # ↑ 对 NOT NULL 的姓名显式传 null。
    assert "stu_name" in str(excinfo.value)
    # ↑ 断言错误信息里包含字段名。
    assert "NOT NULL" in str(excinfo.value)
    # ↑ 断言错误信息里提到 NOT NULL。


def test_stu_update_rejects_explicit_null_on_not_null_unique_field():
    # ↑ 测试：对 NOT NULL 且唯一的字段（学号）显式传 null 也被拒绝。

    with pytest.raises(ValidationError):
        # ↑ 断言抛错。
        StuUpdate.model_validate({"stu_number": None})
        # ↑ 对学号显式传 null。


def test_stu_update_accepts_real_value_for_not_null_field():
    # ↑ 测试：给 NOT NULL 字段传正常值是被允许的。

    """正常更新值不被拒绝。"""
    # ↑ docstring。
    payload = StuUpdate.model_validate({"stu_name": "张三", "stu_number": "S001"})
    # ↑ 传正常值。
    assert payload.stu_name == "张三"
    # ↑ 断言姓名。
    assert payload.stu_number == "S001"
    # ↑ 断言学号。
    assert payload.model_fields_set == {"stu_name", "stu_number"}
    # ↑ 断言这两个字段在"显式给出"集合里。


def test_stu_update_strips_whitespace():
    # ↑ 测试：字符串会自动去掉首尾空格。

    payload = StuUpdate.model_validate({"stu_name": "  张三  "})
    # ↑ 传入带空格的姓名。
    assert payload.stu_name == "张三"
    # ↑ 断言空格被去掉了。


def test_stu_update_forbids_unknown_fields():
    # ↑ 测试：传入未定义的字段会被拒绝。

    with pytest.raises(ValidationError):
        # ↑ 断言抛错。
        StuUpdate.model_validate({"stu_id": 1, "stu_name": "x"})
        # ↑ 传了未定义的 stu_id 字段。


def test_stu_update_rejects_blank_string_for_not_null_field():
    # ↑ 测试：对 NOT NULL 字段传空字符串也被拒绝。

    with pytest.raises(ValidationError):
        # ↑ 断言抛错。
        StuUpdate.model_validate({"stu_name": ""})
        # ↑ 传空字符串（min_length=1 会拒绝）。


def test_exclude_unset_does_not_carry_omitted_fields():
    # ↑ 测试：model_dump(exclude_unset=True) 只输出"显式给出"的字段。

    """``exclude_unset=True`` 后，``model_fields_set`` 之外的字段不出现在 dump 里。"""
    # ↑ docstring。
    payload = StuUpdate.model_validate({"stu_name": "张三"})
    # ↑ 只传姓名。
    dumped = payload.model_dump(exclude_unset=True)
    # ↑ 用 exclude_unset=True 导出。
    assert dumped == {"stu_name": "张三"}
    # ↑ 断言只包含姓名（未传的字段都不出现）。
    assert "stu_class" not in dumped
    # ↑ 断言班级不在导出结果里。
    assert "stu_major" not in dumped
    # ↑ 断言专业不在导出结果里。


# ---------------------------------------------------------------------------
# StuCreate：POST 入参校验
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测"创建"（POST）的入参校验。


def test_stu_create_requires_mandatory_fields():
    # ↑ 测试：创建时缺必填字段会被拒绝。

    with pytest.raises(ValidationError):
        # ↑ 断言抛错。
        StuCreate.model_validate({"stu_number": "S001"})
        # ↑ 只传学号、缺姓名（姓名必填）。


def test_stu_create_rejects_explicit_null_on_required_field():
    # ↑ 测试：创建时对必填字段传 null 会被拒绝。

    with pytest.raises(ValidationError):
        # ↑ 断言抛错。
        StuCreate.model_validate({"stu_number": None, "stu_name": "张三"})
        # ↑ 学号传 null（必填字段不能为 null）。


def test_stu_create_forbids_unknown_fields():
    # ↑ 测试：创建时传未知字段（如伪造主键）会被拒绝。

    with pytest.raises(ValidationError):
        # ↑ 断言抛错。
        StuCreate.model_validate({"stu_number": "S001", "stu_name": "张三", "stu_id": 1})
        # ↑ 传了未定义的 stu_id（客户端不该自己指定主键）。
