"""统一处理预期错误，并安全记录未知服务器异常。"""

import logging
import uuid

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_id import current_request_id
from app.schemas.apiresponse import ApiResponse

logger = logging.getLogger(__name__)


class UnexpectedErrorMiddleware:
    """捕获穿过 FastAPI 异常处理层的未知异常。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            error_id = uuid.uuid4().hex
            logger.error(
                "unhandled_error",
                extra={
                    "error_id": error_id,
                    "request_method": scope.get("method", "-"),
                    "request_path": scope.get("path", "-"),
                },
                exc_info=exc,
            )
            if response_started:
                raise

            response_body = ApiResponse.error(
                code=500,
                message="服务器内部错误",
                data={
                    "error_id": error_id,
                    "request_id": current_request_id(),
                },
            )
            response = JSONResponse(
                status_code=500,
                content=response_body.model_dump(mode="json"),
            )
            await response(scope, receive, send)


class BusinessException(Exception):
    """预期内且可以安全告知客户端的业务失败。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def business_exception_handler(
    _request: Request,
    exc: BusinessException,
) -> JSONResponse:
    """把业务异常转换成统一 JSON，同时保留真实 HTTP 状态码。"""

    body = ApiResponse.error(code=exc.status_code, message=exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(mode="json"),
    )


async def http_exception_handler(
    _request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """统一主动 HTTP 错误以及框架产生的 404、405。"""

    body = ApiResponse.error(code=exc.status_code, message=str(exc.detail))
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(mode="json"),
        headers=exc.headers,
    )


async def validation_exception_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """统一 Pydantic 请求校验错误，并避免回显原始敏感输入。"""

    issues = [
        {
            "loc": list(error["loc"]),
            "type": error["type"],
            "msg": error["msg"],
        }
        for error in exc.errors()
    ]
    body = ApiResponse.error(
        code=422,
        message="请求参数校验错误",
        data={"errors": issues},
    )
    return JSONResponse(
        status_code=422,
        content=body.model_dump(mode="json"),
    )
