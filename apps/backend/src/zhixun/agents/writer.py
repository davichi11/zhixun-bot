"""写手 —— 把项目素材写成有观点、有风格的中文内容。

职责边界：
- **单平台版本**的写作（多平台并行改写交给 `team.py` 里的平台写手 Team）
- 输入：候选项目 + 知识层检索到的历史范文（风格参考）
- 输出：Markdown 稿件

第 1 篇：仅声明 Agent 规格。
第 2 篇：补齐写作提示词（结构模板、语气、长度约束）。
第 4 篇：接入 RAG 检索到的风格范文，实现风格迁移。
"""

from __future__ import annotations

from zhixun.agents.base import AgentSpec, build_agent

WRITER_SPEC = AgentSpec(
    name="写手",
    role="writer",
    description="把筛选后的项目素材写成结构清晰、有观点、符合读者阅读习惯的中文技术内容。",
    instructions=[
        "你是智讯助手的写手，读者是 AI 从业者与开发者。",
        "追求技术严谨与大众可读的平衡：先讲清楚『它解决了什么问题』，再讲『怎么做到的』。",
        "每个项目控制在 200-300 字：一句话定位 + 技术亮点 + 适用场景。",
        "禁止堆砌营销词（如『颠覆』『革命性』），用事实和细节说话。",
        "输出 Markdown，标题层级清晰，代码/项目名用反引号包裹。",
    ],
)


def build_writer() -> object:
    """构建写手 Agent。"""
    # TODO(第 4 篇): 注入风格范文（Few-shot）实现风格化改写
    return build_agent(WRITER_SPEC)
