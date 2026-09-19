"""平台写手 Team —— 本项目**唯一**使用 Agno Team 的地方。

为什么只在"改写"这一步用 Team？
内容生产整体是确定性流水线（见第一篇 / 第 5 篇），主干必须是 Workflow；
但「一份素材 → 三个平台版本」天然是**并行 + 各自有独立人格**的任务：
  - 公众号写手：深度、结构完整、有观点
  - 知乎写手：技术细节、可复现、带代码
  - Twitter 写手：犀利短句、钩子前置

三者互不依赖 → 适合并行；风格差异大 → 适合各自独立的 Agent。
所以这里用 Team（coordinate 模式）做局部嵌套，由团队协调者统一把关口吻一致性。

⚠️ Agno 3.x 迁移注意：
v3 的 `Team` **没有 `leader` 参数**（2.x 的写法会直接报 TypeError）。
协调者不再是一个成员 Agent，而是 **Team 自身** —— 用 Team 的 `model` + `instructions`
扮演协调角色，成员只负责各自的子任务。这正是 coordinate 模式的语义。

第 2 篇：把 Team 改成 v3 写法，并补齐三个平台写手的提示词模板。
第 5 篇：接入 Workflow 的"改写"步骤，真正跑起来。
"""

from __future__ import annotations

from typing import Any

from zhixun.agents.base import AgentSpec, build_agent
from zhixun.config.llm import get_model
from zhixun.config.logging import get_logger

logger = get_logger(__name__)

TEAM_NAME = "平台写手团"

# ------------------------------------------------------------------ 平台写手
# 每个平台的"调性"独立成条，方便单独迭代（改 Twitter 的钩子写法不影响公众号）

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
            "输出 Markdown，不要输出任何解释性前言。",
        ],
    )
    for platform in _PLATFORM_STYLE
]

# 协调者的职责写进 Team 的 instructions（v3 里 Team 自己就是协调者）
TEAM_INSTRUCTIONS: list[str] = [
    "你是「平台写手团」的协调者，自己不写稿，只做组织与把关。",
    "把同一份素材分派给三位平台写手，要求他们并行产出各自平台版本。",
    "确保三位写手使用同一版事实，不允许出现互相矛盾的数字或结论。",
    "汇总时按平台分组输出，并标注每个版本的字数与目标平台。",
    "如果某个平台版本偏离事实或过度发挥，打回重写，不要直接把问题版本交上去。",
]


def build_platform_writer_team(**overrides: Any) -> Any:
    """构建"改写"步骤用的平台写手 Team。

    Returns:
        agno.team.Team 实例（coordinate 模式）。
    """
    from agno.team import Team

    members = [build_agent(spec) for spec in PLATFORM_WRITER_SPECS]

    logger.debug("team.build", team=TEAM_NAME, members=[s.name for s in PLATFORM_WRITER_SPECS])

    kwargs: dict[str, Any] = {
        "name": TEAM_NAME,
        "mode": "coordinate",  # 协调模式：Team 自己当 leader，按需分派给成员
        "model": get_model("primary"),
        "members": members,
        "instructions": TEAM_INSTRUCTIONS,
        "markdown": True,
    }
    kwargs.update(overrides)
    # TODO(第 5 篇): 接入 Workflow 的"改写"步骤，并复用知识层的风格范文
    return Team(**kwargs)
