"""Agent 基类 / 统一构建入口。

设计意图（见第一篇 4.2 节）：
- 所有 Agent 都通过 `build_agent()` 创建，**不允许在业务代码里直接 new Agent**，
  这样才能保证公共配置（模型、日志、护栏、监控）一次性生效
- Harness 的护栏以「可选钩子」形式注入，业务层只依赖接口，不依赖实现（第 7 篇展开）

第 1 篇：只搭骨架，把统一的构建入口定下来。
第 2 篇：在这里补齐四个业务 Agent 的提示词工程与结构化输出。
第 3 篇：把 tools 参数接进来。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from zhixun.config.llm import get_model
from zhixun.config.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class AgentSpec:
    """一个 Agent 的声明式描述（与框架解耦，便于测试与复用）。"""

    name: str
    role: str
    description: str
    instructions: list[str] = field(default_factory=list)
    tools: list[Any] = field(default_factory=list)
    output_schema: type | None = None
    tier: str = "primary"
    markdown: bool = True


def build_agent(spec: AgentSpec, **overrides: Any) -> Any:
    """按 AgentSpec 构建一个 Agno Agent。

    Args:
        spec: Agent 声明
        **overrides: 临时覆盖 Agno Agent 的构造参数（主要给测试用）

    Returns:
        agno.agent.Agent 实例。

    Notes:
        - Harness 护栏在 `zhixun.harness.middlewares` 中以中间件形式挂载，
          这里只预留 `post_hooks` 挂载点，具体实现见第 7 篇。
    """
    from agno.agent import Agent

    kwargs: dict[str, Any] = {
        "name": spec.name,
        "description": spec.description,
        "instructions": spec.instructions,
        "model": get_model(spec.tier),  # type: ignore[arg-type]
        "tools": spec.tools,
        "markdown": spec.markdown,
    }
    if spec.output_schema is not None:
        kwargs["output_schema"] = spec.output_schema
    kwargs.update(overrides)

    logger.debug("agent.build", agent_name=spec.name, tools=len(spec.tools))
    return Agent(**kwargs)


def collect_specs(specs: Sequence[AgentSpec]) -> dict[str, AgentSpec]:
    """把提示词清单注册成 {name: spec}，供 API 层与文档站复用。"""
    return {s.name: s for s in specs}
