"""APScheduler 运行器 —— 与 FastAPI 的 lifespan 绑定。

为什么调度器要独立成模块而不是塞进 API？
- Agent 应该是"被动调用"的，调度是触发源之一（另一个是人工触发 API）
- 独立后可以在没有 Web 的纯 worker 进程里运行，方便水平扩展
"""

from __future__ import annotations

from typing import Any

from zhixun.config.logging import get_logger
from zhixun.scheduler.jobs import build_job_specs

logger = get_logger(__name__)

_scheduler: Any | None = None


def get_scheduler() -> Any:
    """获取全局调度器（惰性创建）。"""
    global _scheduler
    if _scheduler is None:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    return _scheduler


def register_jobs() -> int:
    """按任务清单注册定时任务，返回注册数量。"""
    scheduler = get_scheduler()
    count = 0

    for spec in build_job_specs():
        if not spec.get("enabled"):
            logger.info("scheduler.job_skipped", job_id=spec["id"], reason="disabled")
            continue

        if spec["trigger"] == "cron":
            from apscheduler.triggers.cron import CronTrigger

            minute, hour, day, month, weekday = spec["cron"].split()
            trigger = CronTrigger(
                minute=minute, hour=hour, day=day, month=month, day_of_week=weekday
            )
        else:
            from apscheduler.triggers.interval import IntervalTrigger

            trigger = IntervalTrigger(hours=spec.get("hours", 6))

        scheduler.add_job(spec["func"], trigger=trigger, id=spec["id"], replace_existing=True)
        count += 1
        logger.info("scheduler.job_registered", job_id=spec["id"])

    return count


def start_scheduler() -> None:
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("scheduler.started")


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler.stopped")
