"""未捕获异常的统一出口：给客户端一个可追踪、但不泄密的 500 响应。

这里不用 @app.exception_handler(Exception)，因为 Starlette 会把 Exception 处理器
挂到 ServerErrorMiddleware——它在所有用户中间件的最外层，
拿不到 RequestIdMiddleware 设置的 request_id contextvar（实测只能读到 '-'）。
改成中间件后，只要它比 RequestIdMiddleware 更靠内层，500 响应里就有正确的 request_id。

HTTPException 由 Starlette 的 ExceptionMiddleware 处理成对应状态码，不会传播到这里；
能到达这里的都是真正的意外错误。
"""

import logging
import uuid

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_id import REQUEST_ID_HEADER, current_request_id

logger = logging.getLogger(__name__)


class UnexpectedErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:  # 捕获所有异常本来就是这里的目的。
            if started:
                # 响应已经开始，状态码改不了；交给外层，不要伪造一个 500。
                raise
            await error_response(scope, receive, send, exc)


async def error_response(scope: Scope, receive: Receive, send: Send, exc: Exception) -> None:
    """响应里同时返回 error_id 与 request_id：error_id 是这一次的 UUID，
    request_id 与响应头 X-Request-ID 一致，便于客户端与日志双向关联。
    """
    rid = current_request_id()
    error_id = uuid.uuid4().hex
    logger.error(
        "unhandled_error request_id=%s error_id=%s method=%s path=%s",
        rid,
        error_id,
        scope.get("method"),
        scope.get("path"),
        exc_info=exc,
    )
    response = JSONResponse(
        {"detail": "Internal server error", "error_id": error_id, "request_id": rid},
        status_code=500,
        headers={REQUEST_ID_HEADER: rid},
    )
    await response(scope, receive, send)
