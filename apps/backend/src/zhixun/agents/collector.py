"""采集员 —— 从各信源抓取 AI 开源项目与技术动态。

职责边界（写死在提示词模板 `prompts/collector.md` 里）：
- **只管"抓"**，不做价值判断（筛选是分析师的事）
- 不做跨期去重（知识层统一负责，见第 4 篇）
- 输入：信源清单 + 时间窗
- 输出：`CollectResult`（结构化）

设计说明：
- 这是全项目**唯一用 light 档模型**的 Agent —— 抓取是机械活，
  让便宜模型干，把预算留给写作与审校
- 输出用了 `output_schema`，好处是下游步骤拿到的是 `CollectResult` 而不是一段文本，
  **LLM 的不确定性被收敛在 schema 边界内**

第 2 篇：落地提示词与输出契约。
第 3 篇：注入 `zhixun.tools` 的采集工具（github + search + hackernews）。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from pydantic import BaseModel, Field

from zhixun.agents.base import AgentSpec, build_agent, spec_from_prompt
from zhixun.config.logging import get_logger
from zhixun.config.settings import settings
from zhixun.tools import resolve_toolset

logger = get_logger(__name__)


class RawItem(BaseModel):
    """一条原始素材。"""

    name: str = Field(description="项目名，如 agno-agi/agno")
    url: str = Field(description="仓库或文章地址")
    one_liner: str = Field(default="", description="一句话简介，原文照抄，不要改写")
    stars: int | None = Field(default=None, description="star 数，纯数字；拿不到就留空")
    updated_at: str = Field(default="", description="最近更新时间，ISO 格式")
    source: str = Field(default="", description="来源信源标识，如 github-trending")


class CollectResult(BaseModel):
    """采集结果（结构化输出契约）。"""

    items: list[RawItem] = Field(default_factory=list, description="本期抓到的全部素材")
    failed_sources: list[str] = Field(
        default_factory=list, description="抓取失败的信源，便于人工排查"
    )


COLLECTOR_SPEC: AgentSpec = spec_from_prompt(
    "collector",
    role="collector",
    output_schema=CollectResult,
    variables={"max_items": settings.collector_max_items},
)


def build_collector(*, max_items: int | None = None, with_tools: bool = True, **overrides: object) -> Any:
    """构建采集员 Agent。

    Args:
        max_items: 本次采集条数上限（覆盖配置默认值）
        with_tools: 是否挂载采集工具。默认开启；测试里关掉可以完全离线跑。
    """
    spec = COLLECTOR_SPEC
    if max_items is not None:
        spec = spec_from_prompt(
            "collector",
            role="collector",
            output_schema=CollectResult,
            variables={"max_items": max_items},
        )

    if with_tools:
        # 按角色取工具，而不是手写一份工具清单 —— 授权集中在 tools/__init__.py 里
        resolved = resolve_toolset("collector")
        # 用 replace 复制一份，绝不原地改模块级常量（否则第二次调用会拿到脏数据）
        spec = replace(spec, tools=resolved.tools)
        if resolved.missing:
            # 降级不是错误，但必须留痕：第 8 篇的评估要能看出"这周少了哪个信源"
            logger.warning(
                "collector.tools_degraded",
                missing=resolved.missing,
                loaded=resolved.names,
            )

    return build_agent(spec, **overrides)
