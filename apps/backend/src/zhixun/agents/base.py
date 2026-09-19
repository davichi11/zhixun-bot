"""Agent 基类 / 统一构建入口 —— 全项目所有 Agent 的唯一出厂口。

## 为什么要一层工厂，而不是到处 `Agent(...)`？

项目里只要有第二个人开始写 Agent，就会出现这些问题：

| 直接 `Agent(...)` | 走 `build_agent()` |
|---|---|
| 模型 id 散落各处，换模型要全局搜索替换 | 模型只从 `config/llm.py` 出，改一处生效 |
| 有人忘了 `markdown=True`，有人忘了加护栏 | 公共配置一次性注入，不可能漏 |
| 单元测试没法构造 Agent（要真调 LLM） | 可注入 overrides / stub 掉模型 |
| 提示词内嵌在 Python 里，无法 review | 提示词从 `prompts/*.md` 装配 |

## 两层结构：AgentSpec（声明） → Agent（运行）

`AgentSpec` 是**与框架解耦的声明式描述**，好处是：

- 可以**脱离 Agno 单独测试**（纯数据，不 import 框架）
- 可以被 API 层 / 文档站直接复用（一篇「当前所有 Agent 的提示词」页面）
- 未来换框架（LangGraph / 自研）时，只需重写 `build_agent()`，业务声明不动

第 2 篇：补齐提示词装配与输出契约。
第 3 篇：把 tools 参数接进来。
第 7 篇：把 Harness 护栏以 hooks 形式注入（`pre_hooks` / `post_hooks`）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from zhixun.config.llm import Tier, get_model
from zhixun.config.logging import get_logger
from zhixun.config.settings import settings
from zhixun.prompts import load_prompt

logger = get_logger(__name__)


@dataclass(slots=True)
class AgentSpec:
    """一个 Agent 的声明式描述（与框架解耦，便于测试与复用）。

    Attributes:
        prompt: 提示词模板名（`prompts/<prompt>.md`）。为 None 表示内联提示词 ——
            生产环境禁止内联（见 `settings.allow_inline_prompts`），
            因为内联提示词无法 review、无法版本化。
    """

    name: str
    role: str
    description: str
    instructions: list[str] = field(default_factory=list)
    tools: list[Any] = field(default_factory=list)
    output_schema: type[BaseModel] | None = None
    tier: Tier = "primary"
    markdown: bool = True
    prompt: str | None = None
    prompt_version: int = 0

    @property
    def is_prompt_backed(self) -> bool:
        return self.prompt is not None


def spec_from_prompt(
    prompt_name: str,
    *,
    role: str | None = None,
    tools: list[Any] | None = None,
    output_schema: type[BaseModel] | None = None,
    tier: Tier | None = None,
    markdown: bool = True,
    extra_instructions: Sequence[str] = (),
    variables: dict[str, Any] | None = None,
) -> AgentSpec:
    """从提示词模板装配一个 AgentSpec。

    约定：**能写在提示词文件里的，就不要写在 Python 里**。
    `name` / `description` / `tier` / `instructions` 全部来自模板，
    调用方只声明"这个 Agent 用哪份模板 + 输出契约是什么"。

    Args:
        prompt_name: 模板名（不含 .md），如 `"analyst"`
        role: 覆盖模板里的 role（一般不用，模板自带）
        tools: 工具列表（第 3 篇起使用）
        output_schema: 结构化输出契约
        tier: 覆盖模板里的模型档位
        markdown: 是否让 Agno 按 Markdown 输出
        extra_instructions: 追加指令（少量动态补充才用，别把主体写在这里）
        variables: 注入模板的运行时变量，如 `{"focus_topics": "推理优化", "top_n": 5}`
    """
    prompt = load_prompt(prompt_name)
    meta = prompt.meta

    instructions = prompt.render_instructions(**(variables or {}))
    instructions.extend(extra_instructions)

    return AgentSpec(
        name=meta.title,
        role=role or meta.role or prompt_name,
        description=meta.description,
        instructions=instructions,
        tools=list(tools or []),
        output_schema=output_schema,
        tier=tier or meta.tier,
        markdown=markdown,
        prompt=prompt_name,
        prompt_version=meta.version,
    )


def build_agent(spec: AgentSpec, **overrides: Any) -> Any:
    """按 AgentSpec 构建一个 Agno Agent。

    Args:
        spec: Agent 声明
        **overrides: 临时覆盖 Agno Agent 的构造参数（主要给测试用）

    Returns:
        `agno.agent.Agent` 实例。

    Notes:
        Harness 护栏在 `zhixun.harness.middlewares` 中以 middlewares / hooks 形式挂载，
        这里只负责把挂载点（`pre_hooks` / `post_hooks`）接出去，具体实现见第 7 篇。
    """
    from agno.agent import Agent

    if not spec.is_prompt_backed and not settings.allow_inline_prompts:
        logger.warning(
            "agent.inline_prompt",
            agent=spec.name,
            hint="生产环境建议为每个 Agent 配置 prompts/<name>.md 模板",
        )

    kwargs: dict[str, Any] = {
        "name": spec.name,
        "description": spec.description,
        "instructions": spec.instructions,
        "model": get_model(spec.tier),
        "tools": spec.tools,
        "markdown": spec.markdown,
        # Agno 3.x：超长工具结果自动卸载到 AgentFS，避免上下文爆炸（详见第 7 篇）
        "offload_tool_results": settings.offload_tool_results,
        "debug_mode": settings.debug,
    }
    if spec.output_schema is not None:
        kwargs["output_schema"] = spec.output_schema

    hooks = _harness_hooks(spec)
    if hooks:
        kwargs.update(hooks)

    kwargs.update(overrides)

    logger.debug(
        "agent.build",
        agent=spec.name,
        tier=spec.tier,
        prompt=spec.prompt,
        prompt_version=spec.prompt_version,
        tools=len(spec.tools),
    )
    return Agent(**kwargs)


def _harness_hooks(spec: AgentSpec) -> dict[str, Any]:
    """收集 Harness 挂载点。

    第 2 篇返回空 —— 业务层此刻完全不感知 Harness 的存在，
    这正是"可拆卸性"的体现：第 7 篇往这里塞护栏，业务代码一行不改。
    """
    if not settings.enable_harness:
        return {}
    # TODO(第 7 篇): 装配 guards / context / entropy 对应的 pre_hooks / post_hooks
    return {}


# ------------------------------------------------------------------ 运行辅助


def extract_content(output: Any) -> Any:
    """从 Agno 的运行结果里取出内容（兼容 RunOutput / TeamRunOutput / 原始值）。"""
    content = getattr(output, "content", output)
    if isinstance(content, BaseModel):
        return content
    return content


def run_text(agent: Any, message: str | Any, **kwargs: Any) -> str:
    """同步跑一次并把结果转成字符串（脚本 / CLI / 测试用）。"""
    output = agent.run(message, **kwargs)
    return content_to_text(extract_content(output))


async def arun_text(agent: Any, message: str | Any, **kwargs: Any) -> str:
    """异步跑一次并把结果转成字符串（Workflow 步骤用）。"""
    output = await agent.arun(message, **kwargs)
    return content_to_text(extract_content(output))


def content_to_text(content: Any) -> str:
    """把 content 统一转成字符串。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, BaseModel):
        return content.model_dump_json(indent=2)
    return str(content)


def collect_specs(specs: Sequence[AgentSpec]) -> dict[str, AgentSpec]:
    """把提示词清单注册成 {name: spec}，供 API 层与文档站复用。"""
    return {s.name: s for s in specs}


def spec_summary(spec: AgentSpec) -> dict[str, Any]:
    """给 CLI / 文档站用的规格摘要。"""
    return {
        "name": spec.name,
        "role": spec.role,
        "tier": spec.tier,
        "prompt": spec.prompt,
        "prompt_version": spec.prompt_version,
        "instructions": len(spec.instructions),
        "schema": spec.output_schema.__name__ if spec.output_schema else None,
    }
