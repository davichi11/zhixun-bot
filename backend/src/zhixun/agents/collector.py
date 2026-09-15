"""采集员 —— 从各信源抓取 AI 开源项目与技术动态。

职责边界：
- **只管"抓"**，不做筛选与判断（筛选是 analyst 的事）
- 输入：信源清单（GitHub Trending / Hacker News / arXiv）
- 输出：原始项目列表（未打分、未去重）

第 1 篇：仅声明 Agent 规格。
第 2 篇：补齐提示词与结构化输出。
第 3 篇：接入 `zhixun.tools.github` 等采集工具。
"""

from __future__ import annotations

from zhixun.agents.base import AgentSpec, build_agent

COLLECTOR_SPEC = AgentSpec(
    name="采集员",
    role="collector",
    description="负责从指定信源抓取 AI 领域的开源项目与技术动态，产出结构化的原始素材。",
    instructions=[
        "你是智讯助手的采集员，只负责『抓取』，不做价值判断。",
        "按给定的信源清单依次抓取，保持原始信息完整（标题、链接、star 数、更新时间）。",
        "抓取失败要记录失败原因并继续下一个信源，绝不能因为单个信源失败而中断。",
        "输出必须是结构化列表，不要输出解释性文字。",
    ],
    tier="light",  # 采集是机械活，用便宜模型
)


def build_collector() -> object:
    """构建采集员 Agent。"""
    # TODO(第 3 篇): 注入 GitHub / HN / arXiv 采集工具
    return build_agent(COLLECTOR_SPEC)
