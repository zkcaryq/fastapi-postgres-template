"""请求体大小限制：把过大的请求挡在业务代码之前，防止占满内存。

两道闸：
1. 声明了 Content-Length 且超过上限：直接 413，**完全不读取 body**，也不反序列化。
2. 没有 Content-Length（chunked 传输）或 Content-Length 撒谎：转发时累计实际字节数，
   超限立刻中断转发并返回 413，业务代码不会被调用、payload 不会进对象。

实现为纯 ASGI 中间件：只在 ASGI 消息层面统计字节，不构造 Request 对象，
不缓冲完整 body，也不依赖具体的 ASGI 服务器。
"""
# ↑ 模块 docstring：解释这是"请求体大小限制"中间件，有两道防护，
#   防止攻击者发超大请求体把服务器内存占满。

# 从 Starlette 导入两个响应类：JSONResponse（JSON 响应）和 Response（通用响应）。
from starlette.responses import JSONResponse, Response

# 从 Starlette 导入 ASGI 类型标注。
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.schemas.apiresponse import ApiResponse


class _BodyTooLarge(Exception):
    # ↑ 自定义一个内部异常，用于"请求体超限"时打断下游处理。
    #   加下划线前缀表示"这是内部用的，外部不要引用"。

    """内部信号：转发 body 时超过上限，用于中断下游。"""


class BodySizeLimitMiddleware:
    # ↑ 请求体大小限制中间件类。

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        # ↑ 初始化：接收内层应用和最大允许字节数。
        self.app = app
        # ↑ 保存内层应用。
        self.max_bytes = max_bytes
        # ↑ 保存上限字节数。

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # ↑ ASGI 入口：处理每个请求。

        if scope["type"] != "http":
            # ↑ 非 HTTP 请求（lifespan/websocket）……
            await self.app(scope, receive, send)
            # ↑ 直接透传，不限制。
            return
            # ↑ 结束。

        declared = _content_length(scope.get("headers"))
        # ↑ 读取请求头里声明的 Content-Length（请求体字节数）。返回值可能是：
        #   整数（有声明）、0（无声明或无 body）、None（声明了但解析失败）。
        if declared is None:
            # ↑ 如果 Content-Length 存在但无法解析成数字……
            await self._respond(400, "Content-Length格式无效", scope, receive, send)
            # ↑ 返回 400（客户端请求错误）。
            return
            # ↑ 结束。
        if declared > self.max_bytes:
            # ↑ 如果声明的长度已经超过上限（第一道闸）……
            await self._reject(scope, receive, send)
            # ↑ 直接返回 413，完全不读 body。
            return
            # ↑ 结束。

        seen = 0
        # ↑ 记录"实际已读取的字节数"。
        started = False
        # ↑ 记录"响应是否已经开始"（用于判断还能不能改状态码）。

        async def counting_receive() -> Message:
            # ↑ 包装 receive：在接收请求体时累计字节数，超限就抛异常。
            nonlocal seen
            # ↑ 声明要修改外层函数的 seen 变量（闭包）。
            message = await receive()
            # ↑ 真正接收一条 ASGI 消息。
            if message["type"] == "http.request":
                # ↑ 如果这条消息是请求体的一部分……
                seen += len(message.get("body") or b"")
                # ↑ 累加这部分 body 的字节数（body 不存在则算 0）。
                if seen > self.max_bytes:
                    # ↑ 如果累计字节数超过上限（第二道闸，防"撒谎"和 chunked）……
                    # 从 receive 侧中断：下游的请求读取会直接结束，
                    # 既不把剩余 payload 读进内存，也不会走到业务代码。
                    raise _BodyTooLarge
                    # ↑ 抛出内部异常，中断下游。
            return message
            # ↑ 没超限就正常返回消息。

        async def tracking_send(message: Message) -> None:
            # ↑ 包装 send：跟踪响应是否已开始。
            nonlocal started
            # ↑ 声明要修改外层的 started 变量。
            if message["type"] == "http.response.start":
                # ↑ 如果消息是"响应开始"……
                started = True
                # ↑ 标记响应已开始（之后就不能再改状态码了）。
            await send(message)
            # ↑ 转发消息。

        try:
            # ↑ 尝试用包装过的 receive/send 调用内层应用。
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            # ↑ 如果捕获到"请求体超限"的异常……
            if started:
                # ↑ 如果响应已经开始（状态码已发出去）……
                # 流式响应已经开始，状态码无法再改；交给外层处理而不是伪造 413。
                raise
                # ↑ 把异常继续往上抛，交给外层中间件处理。
            await self._reject(scope, receive, send)
            # ↑ 否则返回 413。

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        # ↑ 返回 413 响应的辅助方法。
        await self._respond(413, "请求体超过允许大小", scope, receive, send)
        # ↑ 调用通用响应方法，状态码 413。

    async def _respond(
        self,
        status_code: int,
        message: str,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """让Router之前产生的400/413也使用统一响应格式。"""

        body = ApiResponse.error(code=status_code, message=message)
        response: Response = JSONResponse(
            body.model_dump(mode="json"),
            status_code=status_code,
        )
        await response(scope, receive, send)
        # ↑ 把这个响应对象作为 ASGI 应用调用，发出响应。


def _content_length(headers) -> int | None:
    # ↑ 辅助函数：从请求头解析 Content-Length，返回整数、0 或 None。

    """返回声明的请求体长度；没有该头返回 0（无 body），解析失败返回 None。"""
    if not headers:
        # ↑ 没有请求头……
        return 0
        # ↑ 返回 0（表示没有 body）。
    for key, value in headers:
        # ↑ 遍历请求头。
        if bytes(key).lower() == b"content-length":
            # ↑ 找到 Content-Length 头（比较时转小写字节）。
            try:
                # ↑ 尝试把值解析成整数。
                return int(value.decode("latin-1"))
                # ↑ 解码后转整数返回。
            except ValueError:
                # ↑ 解析失败（不是数字）……
                return None
                # ↑ 返回 None 表示"声明了但格式非法"。
    # 没有 Content-Length 时无法预判大小：交给转发阶段的字节计数。
    # ↑ 说明：没找到这个头，就返回 0，靠后面的实际计数来防。
    return 0
    # ↑ 返回 0。
