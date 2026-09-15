"""分析师 —— 对原始素材做去重、质量打分与相关度排序。

职责边界：
- 输入：原始项目列表 + 知识层的历史上下文（已发过的项目、你的关注方向）
- 输出：Top N 候选，每项带评分与理由

它是「主观判断可量化」的落地环节：把"这个项目值不值得写"拆成几个可解释的维度打分。

第 1 篇：仅声明 Agent 规格与输出契约。
第 2 篇：补齐评分维度的提示词工程。
第 4 篇：从知识层注入历史上下文，实现跨期去重。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from zhixun.agents.base import AgentSpec, build_agent


class ProjectScore(BaseModel):
    """单个项目的评分结果（结构化输出契约）。"""

    repo: str = Field(description="项目标识，如 owner/name")
    score: float = Field(ge=0, le=10, description="综合评分 0-10")
    novelty: float = Field(ge=0, le=10, description="新颖度：是否代表新方向")
    relevance: float = Field(ge=0, le=10, description="与读者关注方向的相关度")
    momentum: float = Field(ge=0, le=10, description="增长势头：star 增速等")
    reason: str = Field(description="一句话说明为什么给这个分")
    is_duplicate: bool = Field(default=False, description="是否与历史已发内容重复")


class AnalysisResult(BaseModel):
    """分析结果集合。"""

    items: list[ProjectScore]
    summary: str = Field(description="本期整体趋势的一句话总结")


ANALYST_SPEC = AgentSpec(
    name="分析师",
    role="analyst",
    description="对采集到的原始素材进行去重、质量打分与相关度排序，选出本期最值得写的项目。",
    instructions=[
        "你是智讯助手的分析师，负责把一堆原始项目筛成一份高质量候选清单。",
        "评分必须给出可解释的理由，禁止只给分不说原因。",
        "已出现过的项目直接标记 is_duplicate=true，不要进入候选。",
        "评分维度：新颖度（技术是否代表新方向）、相关度（与读者关注方向的匹配）、势头（增长趋势）。",
        "宁可少选，不要把平庸项目塞进来凑数。",
    ],
    output_schema=AnalysisResult,
)


def build_analyst() -> object:
    """构建分析师 Agent。"""
    # TODO(第 4 篇): 注入知识层的 unified_retriever，拿到历史已发项目与关注方向
    return build_agent(ANALYST_SPEC)
