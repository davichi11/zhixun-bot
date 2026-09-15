"""流水线步骤节点（六步：采集 → 筛选 → 摘要 → 改写 → 审校 → 发布）。

每个步骤都是一个**独立的可测试单元**，签名统一：

    async def step_xxx(state: WorkflowState) -> WorkflowState

为什么步骤里不直接 new Agent？
步骤负责**编排与数据搬运**，Agent 负责**推理**。两者分离后：
- 步骤可以 mock 掉 Agent 做单元测试（LLM 不确定性不外溢）
- Agent 换模型/换提示词不影响流程结构

第 1 篇：定义六个步骤的签名与职责。
第 3 篇：实现 step_collect。
第 4 篇：实现 step_filter（去重 + 打分）。
第 5 篇：实现 step_summarize / step_rewrite / step_review / step_publish。
"""

from __future__ import annotations

from zhixun.config.logging import get_logger
from zhixun.workflows.states import WorkflowState

logger = get_logger(__name__)


async def step_collect(state: WorkflowState) -> WorkflowState:
    """① 采集：把各信源的原始项目抓进 state.raw_items。"""
    # TODO(第 3 篇): 调用 collector Agent + github/scraper 工具
    logger.info("workflow.step", step="collect", run_id=state.run_id)
    return state


async def step_filter(state: WorkflowState) -> WorkflowState:
    """② 筛选：去重 + 打分排序，产出 state.scored_items（Top N）。"""
    # TODO(第 4 篇): 知识层去重 + analyst Agent 打分
    logger.info("workflow.step", step="filter", run_id=state.run_id)
    return state


async def step_summarize(state: WorkflowState) -> WorkflowState:
    """③ 摘要：为每个候选压缩出 2-3 条技术亮点。"""
    # TODO(第 5 篇)
    logger.info("workflow.step", step="summarize", run_id=state.run_id)
    return state


async def step_rewrite(state: WorkflowState) -> WorkflowState:
    """④ 改写：**嵌套 Team**，三个平台写手并行产出多平台版本。"""
    # TODO(第 5 篇): 调用 agents.team.build_platform_writer_team()
    logger.info("workflow.step", step="rewrite", run_id=state.run_id)
    return state


async def step_review(state: WorkflowState) -> WorkflowState:
    """⑤ 审校：编辑 Agent 初审 + 需要时挂起等待人工（HITL）。"""
    # TODO(第 5 篇)
    logger.info("workflow.step", step="review", run_id=state.run_id)
    return state


async def step_publish(state: WorkflowState) -> WorkflowState:
    """⑥ 发布：把终稿推送到各平台（需人工批准标记）。"""
    # TODO(第 6 篇): 经 MCP 调用平台 API
    logger.info("workflow.step", step="publish", run_id=state.run_id)
    return state


ALL_STEPS = [
    step_collect,
    step_filter,
    step_summarize,
    step_rewrite,
    step_review,
    step_publish,
]
