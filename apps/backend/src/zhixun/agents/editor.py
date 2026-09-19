"""编辑 —— 稿件终审：事实核查、合规检查、格式与语气统一。

职责边界（见 `prompts/editor.md`）：
- 输入：写手产出的稿件
- 输出：`ReviewResult`（审校意见；通过时视为定稿）
- **敏感内容不自行发布**，标记 `need_human=True`，交给 Workflow 的 HITL 节点

它同时是 Harness「机械强制」的落地位置之一（第 7 篇）：
提示词层面的审校之外，还会叠加 Agno 3.x 原生 guardrails 与代码级 Linter。
**两者不是二选一** —— 提示词负责"理解语义后判断"，代码负责"无论如何都拦住"。

设计说明：
- 审校清单分四类（fact / compliance / format / tone），分类的价值在于
  **可以按类别统计**：如果 80% 的 blocker 都来自 fact，说明问题在上游采集，
  而不是编辑不够努力
- `level` 用 blocker/major/minor 三档，只有 blocker 会阻断发布 ——
  否则审校会变成无止境的挑刺

第 2 篇：落地审校清单与输出契约。
第 5 篇：被接入 Workflow 的审校步骤。
第 7 篇：叠加 Harness 机械强制护栏。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from zhixun.agents.base import AgentSpec, build_agent, spec_from_prompt

IssueLevel = Literal["blocker", "major", "minor"]
IssueCategory = Literal["fact", "compliance", "format", "tone"]


class ReviewIssue(BaseModel):
    """单条审校意见。"""

    level: IssueLevel = Field(description="严重级别：blocker 阻断发布 / major 需修 / minor 建议")
    category: IssueCategory = Field(description="问题类别：fact / compliance / format / tone")
    detail: str = Field(description="问题描述，要具体到句子")
    suggestion: str = Field(description="可直接执行的修改建议")


class ReviewResult(BaseModel):
    """审校结果（结构化输出契约）。"""

    passed: bool = Field(description="是否可通过（无 blocker 即可）")
    need_human: bool = Field(default=False, description="是否需要人工复核")
    issues: list[ReviewIssue] = Field(default_factory=list, description="审校意见列表")

    @property
    def blockers(self) -> list[ReviewIssue]:
        return [i for i in self.issues if i.level == "blocker"]

    @property
    def by_category(self) -> dict[str, int]:
        """按类别统计问题数（用于质量分析，见第 8 篇评估）。"""
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.category] = counts.get(issue.category, 0) + 1
        return counts


EDITOR_SPEC: AgentSpec = spec_from_prompt(
    "editor",
    role="editor",
    output_schema=ReviewResult,
)


def build_editor(*, extra_rules: list[str] | None = None, **overrides: object) -> object:
    """构建编辑 Agent。

    Args:
        extra_rules: 本期临时追加的合规规则（如"本期不要提到具体公司名"）
    """
    spec = spec_from_prompt(
        "editor",
        role="editor",
        output_schema=ReviewResult,
        extra_instructions=extra_rules or [],
    )
    # TODO(第 7 篇): 叠加 Harness 机械强制护栏 + Agno 原生 guardrails
    return build_agent(spec, **overrides)
