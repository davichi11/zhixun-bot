"""Harness 支柱一 · 动态上下文工程（Dynamic Context Engineering）。

核心思想：**渐进式披露（Progressive Disclosure）**
- 不要一次性把整本规范塞进提示词
- 基础规则常驻，细节按需加载
- 接近窗口上限时自动卸载历史、保留关键决策点

与知识层的关系：知识层负责"有哪些信息"，本模块负责"这一刻该放多少进去"。

第 1 篇：定义策略接口。
第 4 篇：基础压缩能力来自 `knowledge.memory.compressor`。
第 7 篇：接管 `UnifiedRetriever`，形成完整的上下文预算与卸载机制。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings
from zhixun.knowledge.memory.compressor import estimate_tokens

logger = get_logger(__name__)


@dataclass(slots=True)
class ContextPlan:
    """一次调用的上下文装配方案。"""

    blocks: list[str] = field(default_factory=list)
    total_tokens: int = 0
    unloaded: list[str] = field(default_factory=list)


@runtime_checkable
class ContextStrategy(Protocol):
    """上下文装配协议。"""

    name: str

    def plan(self, *, base: list[str], optional: list[str]) -> ContextPlan: ...


class ProgressiveContextStrategy:
    """渐进式披露：基础块常驻，可选块按剩余预算装入。"""

    name = "progressive"

    def __init__(self, max_tokens: int | None = None) -> None:
        self.max_tokens = max_tokens or settings.context_max_tokens

    def plan(self, *, base: list[str], optional: list[str]) -> ContextPlan:
        plan = ContextPlan(blocks=list(base))
        plan.total_tokens = sum(estimate_tokens(b) for b in plan.blocks)
        budget = self.max_tokens * settings.context_unload_threshold

        for block in optional:
            cost = estimate_tokens(block)
            if plan.total_tokens + cost <= budget:
                plan.blocks.append(block)
                plan.total_tokens += cost
            else:
                plan.unloaded.append(block[:40])

        logger.debug(
            "context.planned",
            blocks=len(plan.blocks),
            tokens=plan.total_tokens,
            unloaded=len(plan.unloaded),
        )
        return plan

    # TODO(第 7 篇): 接入真实 tokenizer；加入"关键决策点保留"策略；
    #                与 UnifiedRetriever 打通，实现按需回查。
