from fastapi import APIRouter

from app.api.routes.students import router as students_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(students_router)

# 新模块在这里显式注册。学生示例照搬学习项目的 stu_table，替换业务时整组删除。