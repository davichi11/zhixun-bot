"""分析师 —— 对原始素材做去重、质量打分与相关度排序。

职责边界（见 `prompts/analyst.md`）：
- 输入：`CollectResult` + 知识层的历史上下文（已发项目、关注方向）
- 输出：`AnalysisResult`（Top N 候选，每项带三维评分与可解释理由）

它是本项目"**把主观判断量化**"的核心落地：
"这个项目值不值得写"本来是个模糊命题，拆成 novelty / relevance / momentum
三个可解释维度后，就有了可讨论、可回归测试的基线。

设计说明：
- 三个维度的**权重写进提示词**（novelty 权重最高），而不是写在代码里 ——
  调权重属于内容策略，应该让运营同学能改 `prompts/analyst.md` 就生效
- `is_duplicate` 由模型判断，但**真正的去重兜底在知识层**（第 4 篇）：
  LLM 会漏，代码不会

第 2 篇：落地评分维度与输出契约。
第 4 篇：注入知识层的历史上下文，实现跨期去重。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from zhixun.agents.base import AgentSpec, build_agent, spec_from_prompt

DEFAULT_FOCUS = "大模型 / 智能体 / 开源工具"


class ProjectScore(BaseModel):
    """单个项目的评分结果（结构化输出契约）。"""

    repo: str = Field(description="项目标识，如 owner/name")
    score: float = Field(ge=0, le=10, description="综合评分 0-10")
    novelty: float = Field(ge=0, le=10, description="新颖度：是否代表新方向")
    relevance: float = Field(ge=0, le=10, description="与读者关注方向的相关度")
    momentum: float = Field(ge=0, le=10, description="增长势头：star 增速等")
    reason: str = Field(description="一句话说明为什么给这个分，要具体")
    is_duplicate: bool = Field(default=False, description="是否与历史已发内容重复")


class AnalysisResult(BaseModel):
    """分析结果集合。"""

    items: list[ProjectScore] = Field(default_factory=list, description="Top N 候选，按综合分降序")
    summary: str = Field(default="", description="本期整体趋势的一句话总结")


ANALYST_SPEC: AgentSpec = spec_from_prompt(
    "analyst",
    role="analyst",
    output_schema=AnalysisResult,
    variables={"focus_topics": DEFAULT_FOCUS},
)


def build_analyst(
    *,
    focus_topics: str | None = None,
    top_n: int | None = None,
    novelty_weight: float | None = None,
    history_context: str | None = None,
    **overrides: object,
) -> object:
    """构建分析师 Agent。

    Args:
        focus_topics: 本期关注方向（覆盖默认值）
        top_n: 候选数量上限
        novelty_weight: 新颖度权重
        history_context: 历史已发项目的渲染文本（第 4 篇由知识层注入）
    """
    variables: dict[str, object] = {"focus_topics": focus_topics or DEFAULT_FOCUS}
    if top_n is not None:
        variables["top_n"] = top_n
    if novelty_weight is not None:
        variables["novelty_weight"] = novelty_weight

    extra: list[str] = []
    if history_context:
        extra.append(f"【历史已发项目（用于去重）】\n{history_context}")

    spec = spec_from_prompt(
        "analyst",
        role="analyst",
        output_schema=AnalysisResult,
        variables=variables,
        extra_instructions=extra,
    )
    # TODO(第 4 篇): 从知识层 unified_retriever 自动拉取 history_context
    return build_agent(spec, **overrides)
