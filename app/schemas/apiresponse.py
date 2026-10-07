"""业务 API 共用的最外层响应结构。"""

from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    """统一返回 ``code``、``message`` 和 ``data`` 三个字段。

    本类只描述 JSON 内容，不决定真实 HTTP 状态码。失败响应仍应使用
    对应的 4xx/5xx HTTP 状态，不能一律包装成 HTTP 200。
    """

    code: int
    message: str
    data: Any = None

    @classmethod
    def success(
        cls,
        *,
        code: int = 200,
        message: str = "请求成功",
        data: Any = None,
    ) -> "ApiResponse":
        """创建成功响应；默认对应 HTTP 200。"""

        return cls(code=code, message=message, data=data)

    @classmethod
    def error(
        cls,
        *,
        code: int,
        message: str,
        data: Any = None,
    ) -> "ApiResponse":
        """创建失败响应；真实 HTTP 状态码由处理器设置。"""

        return cls(code=code, message=message, data=data)
