"""API 挂载入口。

模板本身不包含任何业务路由。新模块在这里
``api_router.include_router(xxx_router)``。
"""
# ↑ 模块 docstring：这是"业务 API 的汇总入口"，所有业务路由都在这里挂载。

# 从 FastAPI 导入 APIRouter（创建路由组用的类）。
from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")
# ↑ 创建一个汇总路由，所有挂进来的业务接口都会带 /api/v1 前缀。
#   比如挂一个 /students 路由，最终地址就是 /api/v1/students。
#   版本号 v1 是 API 版本管理的好习惯：以后有大改动可以再加个 /api/v2 并存。
