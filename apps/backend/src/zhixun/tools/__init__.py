"""工具系统总入口 —— 注册表 + **按角色最小权限授权**。

## 这一层的核心主张：工具不是"全局可用"的

新手项目最常见的设计是"所有工具给所有 Agent"：

```python
# ❌ 反面教材
all_tools = get_tools("github", "search", "scraper", "publisher")
agent = Agent(tools=all_tools, ...)
```

这在 Demo 阶段看起来很省事，但会带来三个真问题：

**① 工具表越长，模型越容易选错。**
给采集员 12 个工具，它有相当概率在一轮里同时调"搜索""抓网页""读 README"，
把上下文塞满，而它本来只需要调一次 `fetch_trending_repos`。
**工具数量本身就是一种上下文污染。**

**② 权限不可能比工具表更粗。**
如果写手手里有 `publish_draft`，那么"写手不会发布"这件事只能靠提示词保证 ——
回到我们一直在反对的那件事。

**③ 出问题时无法归因。**
采集员这一步多出了 3000 token 的工具结果，你没法判断是"抓取"花的还是"搜索"花的。
`tools_for("collector")` 让每一步的工具集是**有限的、可枚举的、可审计的**。

## 授权表

| 角色 | 授予的工具组 | 理由 |
|---|---|---|
| `collector` | github + search + 内置 hackernews | 它的职责就是"抓" |
| `analyst` | （无） | 只对已抓到的素材打分，不需要任何外部输入 |
| `writer` | （无） | 写作的输入来自上游，不给它"自己去找素材"的能力 |
| `editor` | search + scraper | 事实核查要能查证 |
| `publisher` | publisher | 全项目唯一写操作，只在这一步出现 |

注意 `analyst` 和 `writer` 是**空工具集**。这不是遗漏，是刻意的 ——
**"不给"也是一种设计决策，而且是最容易被忽略的那一种。**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from zhixun.config.logging import get_logger
from zhixun.tools.builtin import BuiltinLoadResult, load_builtin_tools
from zhixun.tools.github import GITHUB_TOOLS
from zhixun.tools.publisher import PUBLISHER_TOOLS
from zhixun.tools.scraper import SCRAPER_TOOLS
from zhixun.tools.search import SEARCH_TOOLS

logger = get_logger(__name__)

# ---------------------------------------------------------------- 工具组注册表
# 每个模块导出自己的 XXX_TOOLS，这里只做"分组名 → 工具列表"的映射。
# 新增一组工具 = 加一行；改一个工具 = 只改它自己的模块。
TOOL_GROUPS: dict[str, list[Any]] = {
    "github": GITHUB_TOOLS,
    "search": SEARCH_TOOLS,
    "scraper": SCRAPER_TOOLS,
    "publisher": PUBLISHER_TOOLS,
}


@dataclass(slots=True)
class Toolset:
    """一个角色的工具授权声明。"""

    role: str
    groups: tuple[str, ...] = ()
    builtin: tuple[str, ...] = ()
    reason: str = ""

    def describe(self) -> str:
        parts = list(self.groups) + [f"内置:{b}" for b in self.builtin]
        return " + ".join(parts) if parts else "(无工具)"


# ---------------------------------------------------------------- 授权表
# 这张表就是"最小权限"的落地：一眼能看出谁能调用什么。
TOOLSETS: dict[str, Toolset] = {
    "collector": Toolset(
        role="collector",
        groups=("github", "search"),
        builtin=("hackernews",),
        reason="职责是采集，需要多信源抓取能力",
    ),
    "analyst": Toolset(
        role="analyst",
        reason="只对已采集素材打分，任何外部输入都会污染评分口径",
    ),
    "writer": Toolset(
        role="writer",
        reason="写作输入来自上游；给它搜索能力会导致它绕过分析师自己找素材",
    ),
    "editor": Toolset(
        role="editor",
        groups=("search", "scraper"),
        reason="事实核查必须能查证原始来源",
    ),
    "publisher": Toolset(
        role="publisher",
        groups=("publisher",),
        reason="全项目唯一写操作，只在这一步授权",
    ),
}


@dataclass(slots=True)
class ResolvedToolset:
    """解析后的工具集（含降级信息）。"""

    role: str
    tools: list[Any] = field(default_factory=list)
    missing: dict[str, str] = field(default_factory=dict)

    @property
    def names(self) -> list[str]:
        return [getattr(t, "name", repr(t)) for t in self.tools]


def resolve_toolset(role: str) -> ResolvedToolset:
    """按角色解析出工具列表（含可选依赖降级）。

    Raises:
        KeyError: 未授权的角色 —— 报错而不是静默返回空列表，
            因为"忘记授权"和"故意不授权"是两件完全不同的事。
    """
    if role not in TOOLSETS:
        available = ", ".join(sorted(TOOLSETS))
        raise KeyError(f"未授权的工具角色: {role!r}。可用：{available}")

    spec = TOOLSETS[role]
    resolved = ResolvedToolset(role=role)

    for group in spec.groups:
        resolved.tools.extend(TOOL_GROUPS.get(group, []))

    if spec.builtin:
        loaded: BuiltinLoadResult = load_builtin_tools(list(spec.builtin))
        resolved.tools.extend(loaded.tools)
        resolved.missing.update(loaded.missing)

    logger.debug(
        "toolset.resolved",
        role=role,
        count=len(resolved.tools),
        tools=resolved.names,
        degraded=bool(resolved.missing),
    )
    return resolved


def tools_for(role: str) -> list[Any]:
    """`resolve_toolset` 的便捷版 —— 只要工具列表。"""
    return resolve_toolset(role).tools


def get_tools(*groups: str, builtin: list[str] | None = None) -> list[Any]:
    """按分组名取工具（**仅用于调试与测试**）。

    业务代码请用 `tools_for(role)` —— 按角色授权才是正确姿势。
    """
    tools: list[Any] = []
    for group in groups:
        tools.extend(TOOL_GROUPS.get(group, []))
    if builtin:
        tools.extend(load_builtin_tools(builtin).tools)
    return tools


def describe_toolsets() -> list[dict[str, Any]]:
    """给 CLI / 文档站用的授权表摘要。"""
    rows: list[dict[str, Any]] = []
    for role, spec in TOOLSETS.items():
        resolved = resolve_toolset(role)
        rows.append(
            {
                "role": role,
                "declared": spec.describe(),
                "count": len(resolved.tools),
                "tools": ", ".join(resolved.names) or "-",
                "degraded": ", ".join(f"{k}({v})" for k, v in resolved.missing.items()) or "-",
                "reason": spec.reason,
            }
        )
    return rows


__all__ = [
    "TOOLSETS",
    "TOOL_GROUPS",
    "ResolvedToolset",
    "Toolset",
    "describe_toolsets",
    "get_tools",
    "load_builtin_tools",
    "resolve_toolset",
    "tools_for",
]
