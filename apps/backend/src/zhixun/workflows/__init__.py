"""流水线层 —— 把 Agent / Team / 工具编排成确定性业务流程（见第一篇 4.2 节 ⑤）。

对外入口：
    from zhixun.workflows import build_weekly_report_workflow, run_weekly_report
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
from zhixun.workflows.weekly_report import build_weekly_report_workflow, new_state, run_weekly_report

__all__ = [
    "Draft",
    "RawItem",
    "ReviewOutcome",
    "ScoredItem",
    "Summary",
    "WorkflowState",
    "build_weekly_report_workflow",
    "new_state",
    "run_weekly_report",
]
