"""写手 —— 把项目素材写成有观点、有风格的中文内容。

职责边界（见 `prompts/writer.md`）：
- **单平台版本**的写作（多平台并行改写交给 `team.py` 里的平台写手团）
- 输入：候选项目 + 知识层检索到的历史范文（风格参考，第 4 篇接入）
- 输出：Markdown 稿件

设计说明：
- 这个 Agent **故意不设 `output_schema`** —— 写文章本来就不该被 schema 框死。
  「哪些 Agent 需要结构化输出」是个需要判断的设计题，不是一律照搬：
    * 采集 / 打分 / 审校 → 要被下游程序消费 → 必须结构化
    * 写作 / 改写 → 最终交付给人看 → 保持自由的 Markdown
- 风格迁移靠"范文 Few-shot 注入"，不靠微调 —— 这是第 4 篇的伏笔

第 2 篇：落地写作结构模板与语气规范。
第 4 篇：接入 RAG 检索到的风格范文，实现风格迁移。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from zhixun.agents.base import AgentSpec, build_agent, spec_from_prompt

DEFAULT_FOCUS = "大模型 / 智能体 / 开源工具"


class Draft(BaseModel):
    """一篇稿件（**由流程步骤组装，不是模型输出**）。

    写手 Agent 输出的是自由 Markdown，步骤拿到文本后包装成 `Draft`
    —— 这样"内容"和"元数据"分开管，下游发布、审校、统计都能复用。
    """

    title: str = Field(default="", description="稿件标题")
    platform: str = Field(default="公众号", description="目标平台")
    markdown: str = Field(default="", description="正文 Markdown")
    word_count: int = Field(default=0, description="字数")
    source_repos: list[str] = Field(default_factory=list, description="本期覆盖的项目")


WRITER_SPEC: AgentSpec = spec_from_prompt(
    "writer",
    role="writer",
    markdown=True,
    variables={"focus_topics": DEFAULT_FOCUS},
)


def build_writer(
    *,
    focus_topics: str | None = None,
    per_item_words: int | None = None,
    style_samples: str | None = None,
    **overrides: object,
) -> object:
    """构建写手 Agent。

    Args:
        focus_topics: 本期主题侧重
        per_item_words: 单项目字数下限
        style_samples: 历史范文（第 4 篇由知识层注入，作为风格 Few-shot）
    """
    variables: dict[str, object] = {"focus_topics": focus_topics or DEFAULT_FOCUS}
    if per_item_words is not None:
        variables["per_item_words"] = per_item_words

    extra: list[str] = []
    if style_samples:
        extra.append(f"【历史范文（模仿节奏与句式，不要复制内容）】\n{style_samples}")

    spec = spec_from_prompt(
        "writer",
        role="writer",
        markdown=True,
        variables=variables,
        extra_instructions=extra,
    )
    return build_agent(spec, **overrides)
