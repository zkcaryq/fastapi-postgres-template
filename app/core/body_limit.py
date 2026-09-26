"""请求体大小限制：把过大的请求挡在业务代码之前，防止占满内存。

两道闸：
1. 声明了 Content-Length 且超过上限：直接 413，**完全不读取 body**，也不反序列化。
2. 没有 Content-Length（chunked 传输）或 Content-Length 撒谎：转发时累计实际字节数，
   超限立刻中断转发并返回 413，业务代码不会被调用、payload 不会进对象。

实现为纯 ASGI 中间件：只在 ASGI 消息层面统计字节，不构造 Request 对象，
不缓冲完整 body，也不依赖具体的 ASGI 服务器。
"""

from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _BodyTooLarge(Exception):
    """内部信号：转发 body 时超过上限，用于中断下游。"""


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _content_length(scope.get("headers"))
        if declared is None:
            await self._respond(400, {"detail": "Invalid Content-Length"}, scope, receive, send)
            return
        if declared > self.max_bytes:
            await self._reject(scope, receive, send)
            return

        seen = 0
        started = False

        async def counting_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body") or b"")
                if seen > self.max_bytes:
                    # 从 receive 侧中断：下游的请求读取会直接结束，
                    # 既不把剩余 payload 读进内存，也不会走到业务代码。
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            if started:
                # 流式响应已经开始，状态码无法再改；交给外层处理而不是伪造 413。
                raise
            await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._respond(413, {"detail": "Request body too large"}, scope, receive, send)

    async def _respond(
        self, status: int, payload: dict[str, str], scope: Scope, receive: Receive, send: Send
    ) -> None:
        response: Response = JSONResponse(payload, status_code=status)
        await response(scope, receive, send)


def _content_length(headers) -> int | None:
    """返回声明的请求体长度；没有该头返回 0（无 body），解析失败返回 None。"""
    if not headers:
        return 0
    for key, value in headers:
        if bytes(key).lower() == b"content-length":
            try:
                return int(value.decode("latin-1"))
            except ValueError:
                return None
    # 没有 Content-Length 时无法预判大小：交给转发阶段的字节计数。
    return 0
