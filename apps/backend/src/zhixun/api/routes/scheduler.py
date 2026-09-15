"""调度管理接口（前端「调度面板」对接）。"""

from __future__ import annotations

from fastapi import APIRouter

from zhixun.api.schemas import JobOut
from zhixun.config.settings import settings

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.get("/jobs", response_model=list[JobOut], summary="列出定时任务")
async def list_jobs() -> list[JobOut]:
    """列出已注册的定时任务。"""
    return [
        JobOut(
            id="weekly-report",
            name="每周周报自动生成",
            cron=settings.weekly_report_cron,
            enabled=settings.scheduler_enabled,
        )
    ]


@router.post("/jobs/{job_id}/toggle", summary="启用/停用某个任务")
async def toggle_job(job_id: str, enabled: bool) -> dict[str, object]:
    """启用或停用任务。

    TODO(第 5 篇): 与 APScheduler 实例联动，持久化开关状态。
    """
    return {"job_id": job_id, "enabled": enabled, "note": "第 5 篇实现运行时联动"}
