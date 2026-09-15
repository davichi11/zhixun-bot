"""路由注册表 —— 所有子路由在这里汇总，`main.py` 只负责挂载。"""

from __future__ import annotations

from fastapi import APIRouter

from zhixun.api.routes import drafts, projects, scheduler, workflow

api_router = APIRouter()
api_router.include_router(projects.router)
api_router.include_router(drafts.router)
api_router.include_router(workflow.router)
api_router.include_router(scheduler.router)

__all__ = ["api_router"]
