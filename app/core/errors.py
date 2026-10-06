"""未知异常兜底：服务端保留堆栈，客户端只获得安全追踪编号。"""

import logging
import uuid

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_id import current_request_id

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

            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal server error",
                    "error_id": error_id,
                    "request_id": current_request_id(),
                },
            )
            await response(scope, receive, send)
