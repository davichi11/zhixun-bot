"""Harness 中间件链 —— 驾驭层的统一挂载点（见第一篇 4.2 节 ⑦ / 第 7 篇）。

核心约定（**可拆卸性 Rippable**）：
- 业务层**不 import 具体护栏实现**，只依赖这里的 `Middleware` 协议
- 想换一套 Harness（LangSmith / OpenTelemetry / 自研）只需替换本目录
- 中间件按顺序链式处理，任一环节 `blocked=True` 立即短路

第 1 篇：定义协议与空实现（保证 `enable_harness=False` 时行为完全等价）。
第 7 篇：落地 guards / context / entropy 三大支柱，并接入模型调用链。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings

logger = get_logger(__name__)


@dataclass(slots=True)
class HarnessContext:
    """中间件之间流转的上下文包。"""

    task: str
    agent_name: str | None = None
    session_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    block_reason: str = ""
    injected_feedback: list[str] = field(default_factory=list)


@runtime_checkable
class Middleware(Protocol):
    """中间件协议。"""

    name: str

    async def process(self, ctx: HarnessContext) -> HarnessContext: ...


class NoopMiddleware:
    """空中间件（用于占位与测试）。"""

    name = "noop"

    async def process(self, ctx: HarnessContext) -> HarnessContext:
        return ctx


class HarnessChain:
    """中间件链。"""

    def __init__(self, middlewares: list[Middleware] | None = None) -> None:
        self.middlewares: list[Middleware] = middlewares or []

    def add(self, mw: Middleware) -> HarnessChain:
        self.middlewares.append(mw)
        return self

    async def run(self, ctx: HarnessContext) -> HarnessContext:
        """顺序执行中间件，遇到 blocked 立即短路。"""
        for mw in self.middlewares:
            ctx = await mw.process(ctx)
            if ctx.blocked:
                logger.warning("harness.blocked", middleware=mw.name, reason=ctx.block_reason)
                break
        return ctx


def build_default_chain() -> HarnessChain:
    """按配置装配默认中间件链。

    第 1 篇返回空链（不改变任何行为）；
    第 7 篇会按 `settings.enable_harness` 装配：
        ContextMiddleware → GuardMiddleware → EntropyMiddleware
    """
    if not settings.enable_harness:
        logger.debug("harness.disabled")
        return HarnessChain()
    # TODO(第 7 篇): 装配三大支柱中间件
    return HarnessChain()
