"""编辑 —— 稿件终审：事实核查、合规检查、格式统一。

职责边界：
- 输入：写手产出的稿件
- 输出：审校意见 +（通过时）定稿
- **敏感内容不自行发布**，标记为需人工审核，交给 Workflow 的 HITL 节点

它同时是 Harness「机械强制」的落地位置之一（第 7 篇）：
提示词层面的审校之外，还会叠加代码级的 Linter 护栏。

第 1 篇：仅声明 Agent 规格。
第 2 篇：补齐审校清单与输出契约。
第 5 篇：被接入 Workflow 的审校步骤。
第 7 篇：叠加机械强制护栏。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from zhixun.agents.base import AgentSpec, build_agent


class ReviewIssue(BaseModel):
    """单条审校意见。"""

    level: str = Field(description="blocker / major / minor")
    category: str = Field(description="fact / compliance / format / tone")
    detail: str = Field(description="问题描述")
    suggestion: str = Field(description="修改建议")


class ReviewResult(BaseModel):
    """审校结果。"""

    passed: bool = Field(description="是否可通过（无 blocker 即可）")
    need_human: bool = Field(default=False, description="是否需要人工复核")
    issues: list[ReviewIssue] = Field(default_factory=list)


EDITOR_SPEC = AgentSpec(
    name="编辑",
    role="editor",
    description="对稿件做终审：事实核查、合规检查、格式与语气统一，输出审校意见。",
    instructions=[
        "你是智讯助手的编辑，是内容出厂前的最后一道关。",
        "逐条核查：项目描述是否与事实相符、有无夸大、是否存在合规风险、格式是否统一。",
        "任何不确定的事实，一律标记为需要人工复核，不要替作者拍板。",
        "审校意见要具体到句子，避免『建议润色』这类空话。",
    ],
    output_schema=ReviewResult,
)


def build_editor() -> object:
    """构建编辑 Agent。"""
    # TODO(第 7 篇): 叠加 Harness 机械强制护栏（敏感词 / 事实核查 / 格式 Linter）
    return build_agent(EDITOR_SPEC)
