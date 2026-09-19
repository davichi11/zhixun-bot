"""zhixun.agents —— 四个核心 Agent + 统一注册表。

## 为什么要一张注册表？

有了 `AGENT_BUILDERS`，新增一个 Agent 只需要两步：
1. 在 `prompts/` 放一份模板
2. 在对应的 `agents/xxx.py` 里写 `spec_from_prompt(...)`

而 API 层、文档站、评估脚本都从注册表取，不需要知道具体模块路径。
第 8 篇的评估集、第 9 篇的 AgentOS 控制台都直接消费这张表。

## audit_specs()：提示词治理自检

`allow_inline_prompts=False` 时，任何没走模板的 Agent 都会被标记出来。
建议把它挂进 CI ——「提示词治理」和「代码规范」一样，靠自觉是守不住的。
"""

from __future__ import annotations

from typing import Any

from zhixun.agents.analyst import ANALYST_SPEC, AnalysisResult, ProjectScore, build_analyst
from zhixun.agents.base import (
    AgentSpec,
    build_agent,
    content_to_text,
    extract_content,
    run_text,
    spec_from_prompt,
    spec_summary,
)
from zhixun.agents.collector import COLLECTOR_SPEC, CollectResult, RawItem, build_collector
from zhixun.agents.editor import (
    EDITOR_SPEC,
    ReviewIssue,
    ReviewResult,
    build_editor,
)
from zhixun.agents.writer import WRITER_SPEC, Draft, build_writer

__all__ = [
    "AGENT_BUILDERS",
    "SPECS",
    "AgentSpec",
    "AnalysisResult",
    "CollectResult",
    "Draft",
    "ProjectScore",
    "RawItem",
    "ReviewIssue",
    "ReviewResult",
    "audit_specs",
    "build_agent",
    "build_agent_by_role",
    "build_analyst",
    "build_collector",
    "build_editor",
    "build_writer",
    "content_to_text",
    "extract_content",
    "run_text",
    "spec_from_prompt",
    "spec_summary",
]

# ---------------------------------------------------------------- 注册表

SPECS: dict[str, AgentSpec] = {
    "collector": COLLECTOR_SPEC,
    "analyst": ANALYST_SPEC,
    "writer": WRITER_SPEC,
    "editor": EDITOR_SPEC,
}

# role → 构建函数（函数的 keyword 参数即该 Agent 的可注入变量）
AGENT_BUILDERS: dict[str, Any] = {
    "collector": build_collector,
    "analyst": build_analyst,
    "writer": build_writer,
    "editor": build_editor,
}


def build_agent_by_role(role: str, **kwargs: Any) -> Any:
    """按 role 构建 Agent（API 层与工作流步骤的统一入口）。"""
    try:
        builder = AGENT_BUILDERS[role]
    except KeyError:
        available = ", ".join(sorted(AGENT_BUILDERS))
        raise KeyError(f"未知的 Agent role: {role!r}。可用：{available}") from None
    return builder(**kwargs)


def audit_specs() -> list[str]:
    """提示词治理自检，返回问题列表（空列表 = 通过）。

    检查项：
    1. 每个 Agent 都绑定提示词模板（否则提示词无法 review / 版本化）
    2. 模板存在且能被解析
    3. Agent 名称唯一（避免日志与面板里认不出谁是谁）
    """
    from zhixun.prompts import load_prompt

    problems: list[str] = []
    seen: dict[str, str] = {}

    for key, spec in SPECS.items():
        if not spec.is_prompt_backed:
            problems.append(f"[{key}] 未绑定提示词模板（prompt=None）")
            continue
        try:
            prompt = load_prompt(spec.prompt or "")
        except Exception as exc:  # noqa: BLE001 - 自检要把所有问题都收集出来
            problems.append(f"[{key}] 提示词模板加载失败：{exc}")
            continue
        if prompt.meta.version != spec.prompt_version:
            problems.append(
                f"[{key}] 模板版本漂移：spec={spec.prompt_version} 模板={prompt.meta.version}"
            )
        if spec.name in seen:
            problems.append(f"[{key}] Agent 名称与 [{seen[spec.name]}] 重复：{spec.name}")
        seen[spec.name] = key

    if not SPECS:
        problems.append("注册表为空")
    return problems
