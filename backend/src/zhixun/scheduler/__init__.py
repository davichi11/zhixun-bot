"""调度层 —— 定时触发流水线（见第一篇 4.2 节 ⑧、五层架构的调度层）。"""

from __future__ import annotations

from zhixun.scheduler.jobs import (
    JOB_ENTROPY_SCAN,
    JOB_WEEKLY_REPORT,
    build_job_specs,
    run_entropy_scan_job,
    run_weekly_report_job,
)
from zhixun.scheduler.runner import (
    get_scheduler,
    register_jobs,
    shutdown_scheduler,
    start_scheduler,
)

__all__ = [
    "JOB_ENTROPY_SCAN",
    "JOB_WEEKLY_REPORT",
    "build_job_specs",
    "get_scheduler",
    "register_jobs",
    "run_entropy_scan_job",
    "run_weekly_report_job",
    "shutdown_scheduler",
    "start_scheduler",
]
