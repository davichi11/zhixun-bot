"""智讯助手 · FastAPI 入口。

启动：
    uv run uvicorn zhixun.main:app --reload --port 8000

约定（见第一篇 5.4 节 错误处理规范）：
- 业务错误 → BusinessError → 200 + 业务码
- 系统错误 → SystemError → 5xx
- Agent 错误 → 不在 API 层处理，由 Harness 护栏接管（第 7 篇）
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from zhixun.api import api_router
from zhixun.api.schemas import HealthResponse
from zhixun.config.logging import configure_logging, get_logger
from zhixun.config.settings import settings
from zhixun.db.session import dispose_db, init_db
from zhixun.scheduler import register_jobs, shutdown_scheduler, start_scheduler

logger = get_logger(__name__)


# ---------------------------------------------------------------- 业务异常


class BusinessError(Exception):
    """业务错误（可预期，返回 200 + 业务码）。"""

    def __init__(self, code: str, message: str, status_code: int = 200) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ---------------------------------------------------------------- 生命周期


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动时建库/起调度，关闭时优雅退出。"""
    configure_logging()
    logger.info("app.starting", env=settings.env, harness=settings.enable_harness)

    await init_db()
    if settings.scheduler_enabled:
        register_jobs()
        start_scheduler()
    else:
        logger.info("app.scheduler_disabled")

    yield

    shutdown_scheduler()
    await dispose_db()
    logger.info("app.stopped")


# ---------------------------------------------------------------- 应用装配


def create_app() -> FastAPI:
    """创建 FastAPI 应用（工厂模式，便于测试）。"""
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        description="AI 资讯聚合与内容创作智能体 —— 后端服务",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"] if settings.is_dev else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/health", response_model=HealthResponse, tags=["meta"], summary="健康检查")
    async def health() -> HealthResponse:
        return HealthResponse(
            app=settings.app_name,
            env=settings.env,
            harness_enabled=settings.enable_harness,
        )

    @app.exception_handler(BusinessError)
    async def business_error_handler(request: Request, exc: BusinessError) -> JSONResponse:
        logger.warning("api.business_error", code=exc.code, path=request.url.path)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    return app


app = create_app()
