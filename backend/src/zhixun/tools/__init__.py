"""工具系统总入口（见第一篇 4.2 节 ③）。

约定：
- 每个工具模块导出自己的 `XXX_TOOLS: list` 常量
- 这里统一聚合成注册表，Agent 通过 `get_tools("github")` 按需取用
- 工具只做"执行"，**权限与边界由 Harness 层负责**（第 7 篇）
"""

from __future__ import annotations

from typing import Any

from zhixun.tools.builtin import load_builtin_tools
from zhixun.tools.github import GITHUB_TOOLS
from zhixun.tools.publisher import PUBLISHER_TOOLS
from zhixun.tools.scraper import SCRAPER_TOOLS
from zhixun.tools.search import SEARCH_TOOLS

_REGISTRY: dict[str, list[Any]] = {
    "github": GITHUB_TOOLS,
    "search": SEARCH_TOOLS,
    "scraper": SCRAPER_TOOLS,
    "publisher": PUBLISHER_TOOLS,
}


def get_tools(*groups: str, builtin: list[str] | None = None) -> list[Any]:
    """按分组名取工具。

    Example:
        get_tools("github", "scraper", builtin=["file"])
    """
    tools: list[Any] = []
    for group in groups:
        tools.extend(_REGISTRY.get(group, []))
    if builtin:
        tools.extend(load_builtin_tools(builtin))
    return tools


__all__ = ["get_tools", "load_builtin_tools"]
