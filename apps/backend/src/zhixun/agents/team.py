"""平台写手 Team —— 本项目**唯一**使用 Agno Team 的地方。

为什么只在"改写"这一步用 Team？
内容生产整体是确定性流水线（见第一篇 / 第 5 篇），主干必须是 Workflow；
但「一份素材 → 三个平台版本」天然是**并行 + 各自有独立人格**的任务：
  - 公众号写手：深度、结构完整、有观点
  - 知乎写手：技术细节、可复现、带代码
  - Twitter 写手：犀利短句、钩子前置

三者互不依赖 → 适合并行；风格差异大 → 适合各自独立的 Agent。
所以这里用 Team（coordinate 模式）做局部嵌套，由协调者统一把关口吻一致性。

第 1 篇：搭出 Team 骨架与三个平台写手的规格。
第 5 篇：接入 Workflow 的"改写"步骤，真正跑起来。
"""

from __future__ import annotations

from typing import Any

from zhixun.agents.base import AgentSpec, build_agent
from zhixun.config.logging import get_logger

logger = get_logger(__name__)

# ------------------------------------------------------------------ 平台写手

_PLATFORM_STYLE: dict[str, str] = {
    "公众号": (
        "面向公众号读者：开头用一个具体场景钩住人，正文结构完整（问题→方案→亮点→适用场景），"
        "语气专业但不端着，段落短、有留白，结尾给一句可带走的判断。"
    ),
    "知乎": (
        "面向知乎读者：以技术细节取胜，讲清楚架构与实现取舍，允许适当展开对比与踩坑，"
        "可以在文末附关键代码或伪代码，语气克制、就事论事。"
    ),
    "Twitter": (
        "面向 Twitter/X：字数极简，第一条必须是最有冲击力的结论或反直觉事实，"
        "可以用短句分点，不要客套话，不要总结句。"
    ),
}

PLATFORM_WRITER_SPECS: list[AgentSpec] = [
    AgentSpec(
        name=f"{platform}写手",
        role=f"writer_{platform.lower()}",
        description=f"{platform}平台专用写手，把同一份素材改写成该平台的调性与结构。",
        instructions=[
            f"你是智讯助手的{platform}写手。",
            _PLATFORM_STYLE[platform],
            "素材事实不得改动，只能改变表达方式与结构。",
            "输出 Markdown。",
        ],
    )
    for platform in _PLATFORM_STYLE
]

# 协调者：不写作，只做风格一致性与事实一致性把关
TEAM_LEADER_SPEC = AgentSpec(
    name="改写协调者",
    role="team_leader",
    description="统筹三个平台写手并行改写，统一事实口径与品牌调性，汇总为多平台稿件包。",
    instructions=[
        "你负责协调三个平台写手，自己不写稿。",
        "确保三位写手使用同一版事实，不允许出现互相矛盾的数字或结论。",
        "汇总时按平台分组输出，并标注每个版本的字数与目标平台。",
    ],
)


def build_platform_writer_team(**overrides: Any) -> Any:
    """构建"改写"步骤用的平台写手 Team。

    Returns:
        agno.team.Team 实例（coordinate 模式）。
    """
    from agno.team import Team

    members = [build_agent(spec) for spec in PLATFORM_WRITER_SPECS]
    leader = build_agent(TEAM_LEADER_SPEC)

    logger.debug("team.build", members=[s.name for s in PLATFORM_WRITER_SPECS])

    kwargs: dict[str, Any] = {
        "name": "平台写手团",
        "mode": "coordinate",
        "members": members,
        "leader": leader,
        "markdown": True,
    }
    kwargs.update(overrides)
    # TODO(第 5 篇): 接入 Workflow 的"改写"步骤，并复用知识层的风格范文
    return Team(**kwargs)
