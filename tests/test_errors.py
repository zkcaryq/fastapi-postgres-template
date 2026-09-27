"""通用 500：回到客户端的只有 error_id / request_id，不含异常内容。

注意中间件的注册顺序必须与 app/main.py 一致（RequestId 在外、Error 在内），
否则 request_id 会退化成 '-'：最后 add 的排在最外层。
"""
# ↑ 模块 docstring：测试"未捕获异常兜底中间件"的行为。

# 导入 FastAPI 和测试客户端。
from fastapi import FastAPI
from fastapi.testclient import TestClient

# 导入要测试的两个中间件。
from app.core.errors import UnexpectedErrorMiddleware
from app.core.request_id import RequestIdMiddleware


def build_app() -> FastAPI:
    # ↑ 辅助函数：构造一个带中间件的最小测试应用。

    app = FastAPI()
    # ↑ 创建应用。
    # UnexpectedError 先注册 → 更内层 → 处在 RequestId 的 contextvar 范围内。
    # ↑ 说明：先 add 的在内层（和 main.py 的顺序一致）。
    app.add_middleware(UnexpectedErrorMiddleware)
    # ↑ 先注册异常兜底中间件（在里层）。
    app.add_middleware(RequestIdMiddleware)
    # ↑ 后注册请求 ID 中间件（在外层，能先设置 request_id）。

    @app.get("/boom")
    # ↑ 定义一个会抛异常的接口。
    async def boom() -> None:
        # ↑ 处理函数。
        raise ValueError("connection string postgresql://u:p@host/db leaked")
        # ↑ 故意抛一个异常，异常文本里含"连接串"——用于验证不会泄露给客户端。

    return app
    # ↑ 返回构造好的应用。


def test_unexpected_error_returns_ids_only():
    # ↑ 测试：异常时只返回 error_id 和 request_id，不返回异常内容。

    client = TestClient(build_app())
    # ↑ 创建测试客户端。
    response = client.get("/boom", headers={"X-Request-ID": "trace-9"})
    # ↑ 请求 /boom，并带上自定义的 X-Request-ID。

    assert response.status_code == 500
    # ↑ 断言状态码是 500。
    body = response.json()
    # ↑ 解析响应体。
    assert body["detail"] == "Internal server error"
    # ↑ 断言 detail 是固定的"服务器内部错误"，不是异常原文。
    assert len(body["error_id"]) == 32
    # ↑ 断言 error_id 是 32 位（UUID 的 hex 格式）。
    assert body["request_id"] == "trace-9"
    # ↑ 断言 request_id 正确透传了客户端给的值。
    assert response.headers["X-Request-ID"] == "trace-9"
    # ↑ 断言响应头里的 X-Request-ID 也一致。
    # 异常原文绝不出现在客户端响应里。
    # ↑ 说明。
    assert "postgresql://" not in response.text
    # ↑ 断言响应文本里没有连接串。
    assert "leaked" not in response.text
    # ↑ 断言响应文本里没有异常里的关键词。


def test_unexpected_error_has_unique_error_id():
    # ↑ 测试：每次错误的 error_id 都不同（便于唯一定位）。

    client = TestClient(build_app())
    # ↑ 创建客户端。
    first = client.get("/boom").json()["error_id"]
    # ↑ 第一次请求，取出 error_id。
    second = client.get("/boom").json()["error_id"]
    # ↑ 第二次请求，取出 error_id。
    assert first != second
    # ↑ 断言两次不同。


def test_http_exception_keeps_its_own_status():
    # ↑ 测试：HTTPException（如 404）不能被通用 500 吃掉。

    """404/405 这类 HTTPException 不能被通用 500 吃掉。"""
    # ↑ docstring。
    response = TestClient(build_app()).get("/missing")
    # ↑ 请求一个不存在的路径（触发 404）。
    assert response.status_code == 404
    # ↑ 断言状态码是 404（而不是被吞成 500）。
    assert response.json()["detail"] == "Not Found"
    # ↑ 断言 detail 是"Not Found"。
