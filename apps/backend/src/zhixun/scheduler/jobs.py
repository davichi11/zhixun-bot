"""定时任务定义。

第 1 篇：注册一个"每周周报"任务（默认停用，由配置控制）。
第 5 篇：补齐任务持久化、失败告警与重试。
第 7 篇：追加"熵扫描 GC"任务（每 6 小时一次）。
"""

from __future__ import annotations

from typing import Any

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings

logger = get_logger(__name__)

JOB_WEEKLY_REPORT = "weekly-report"
JOB_ENTROPY_SCAN = "entropy-scan"


async def run_weekly_report_job() -> None:
    """每周自动生成周报。"""
    from zhixun.workflows import run_weekly_report

    logger.info("job.weekly_report.start")
    await run_weekly_report(dry_run=False)
    logger.info("job.weekly_report.done")


async def run_entropy_scan_job() -> None:
    """熵扫描（Harness 支柱三）。"""
    # TODO(第 7 篇): 调用 EntropyScanner 并写心跳
    logger.info("job.entropy_scan.skipped", note="第 7 篇实现")


def build_job_specs() -> list[dict[str, Any]]:
    """返回需要注册的任务清单（供 runner 使用）。"""
    return [
        {
            "id": JOB_WEEKLY_REPORT,
            "func": run_weekly_report_job,
            "trigger": "cron",
            "cron": settings.weekly_report_cron,
            "enabled": settings.scheduler_enabled,
        },
        {
            "id": JOB_ENTROPY_SCAN,
            "func": run_entropy_scan_job,
            "trigger": "interval",
            "hours": 6,
            "enabled": settings.scheduler_enabled,
        },
    ]
