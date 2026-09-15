"""周报主流程 —— 全项目的业务主干。

架构决策（见第一篇 4.2 / 第 5 篇）：
**Workflow 主导 + Team 局部嵌套**。
- 主干用 Workflow：确定性、可审计、可断点恢复
- 只有"改写"这一步内部嵌套 Team（三平台并行）

流程：

    collect → filter → summarize → rewrite → review →(人工)→ publish
                                        └── 内嵌 Team：公众号/知乎/Twitter 三写手并行

第 1 篇：把流程骨架与状态串起来（各步骤目前是空实现，只打印日志）。
第 5 篇：补齐全部步骤、条件分支、状态持久化与 HITL 挂起/恢复。
"""

from __future__ import annotations

import uuid
from typing import Any

from zhixun.config.logging import get_logger
from zhixun.workflows.states import WorkflowState
from zhixun.workflows.steps import ALL_STEPS

logger = get_logger(__name__)

STEP_LABELS = {
    "step_collect": "① 采集",
    "step_filter": "② 筛选",
    "step_summarize": "③ 摘要",
    "step_rewrite": "④ 改写（内嵌 Team）",
    "step_review": "⑤ 审校（HITL）",
    "step_publish": "⑥ 发布",
}


def build_weekly_report_workflow() -> Any:
    """构建周报 Workflow（Agno Workflow 实例）。"""
    from agno.workflow import Step, Workflow

    steps = [
        Step(name=STEP_LABELS.get(fn.__name__, fn.__name__), executor=fn) for fn in ALL_STEPS
    ]

    workflow = Workflow(
        name="weekly-report",
        description="智讯助手周报流水线：采集 → 筛选 → 摘要 → 改写 → 审校 → 发布",
        steps=steps,
    )
    logger.info("workflow.built", steps=len(steps))
    return workflow


def new_state(*, dry_run: bool = False, issue_no: int | None = None) -> WorkflowState:
    """创建一个新的运行状态。"""
    return WorkflowState(run_id=uuid.uuid4().hex, dry_run=dry_run, issue_no=issue_no)


async def run_weekly_report(*, dry_run: bool = False) -> WorkflowState:
    """跑一次周报流水线。

    Args:
        dry_run: 干跑模式 —— 走完全部步骤但不真正发布（推荐 CI 与本地调试使用）
    """
    state = new_state(dry_run=dry_run)
    logger.info("workflow.start", run_id=state.run_id, dry_run=dry_run)

    for fn in ALL_STEPS:
        state = await fn(state)
        if fn is ALL_STEPS[-1] and dry_run:
            logger.info("workflow.dry_run_skip_publish", run_id=state.run_id)

    logger.info("workflow.done", run_id=state.run_id)
    return state


# TODO(第 5 篇): 用 Agno Workflow 的 run() 替换上面的手写 for 循环，
#                以获得官方的 checkpoint / 并行 / 条件分支能力。
