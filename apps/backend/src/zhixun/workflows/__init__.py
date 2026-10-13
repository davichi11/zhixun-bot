"""流水线层 —— 把 Agent / Team / 工具编排成确定性业务流程（见第一篇 4.2 节 ⑤）。

架构：**Workflow 主导 + Team 局部嵌套**（ADR-002）。

对外入口：
    from zhixun.workflows import run_weekly_report, approve, reject

    # 1) 跑一次（dry_run 走完全流程但不调 LLM、不发布）
    out = await run_weekly_report(dry_run=True, skip_review=True)

    # 2) 正式跑，会在"人工审校"处挂起
    out = await run_weekly_report(issue_no=42)

    # 3) 人工点"通过" → 恢复
    if pending_approvals(out):
        out = await approve(out)
"""

from __future__ import annotations

from zhixun.workflows.states import (
    Draft,
    RawItem,
    ReviewOutcome,
    ScoredItem,
    Summary,
    WorkflowState,
)
from zhixun.workflows.weekly_report import (
    MIN_CANDIDATES,
    approve,
    build_weekly_report_workflow,
    describe_pending,
    dump_steps,
    find_latest_pending_run,
    find_latest_pending_session,
    get_workflow_db,
    has_enough_candidates,
    load_pending_run,
    new_session_id,
    pending_approvals,
    reject,
    run_weekly_report,
)

__all__ = [
    "MIN_CANDIDATES",
    "Draft",
    "RawItem",
    "ReviewOutcome",
    "ScoredItem",
    "Summary",
    "WorkflowState",
    "approve",
    "build_weekly_report_workflow",
    "describe_pending",
    "dump_steps",
    "find_latest_pending_run",
    "find_latest_pending_session",
    "get_workflow_db",
    "has_enough_candidates",
    "load_pending_run",
    "new_session_id",
    "pending_approvals",
    "reject",
    "run_weekly_report",
]