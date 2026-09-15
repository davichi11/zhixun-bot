"""Agno 内置工具包的统一封装与再导出。

保持这一层存在的意义：当 Agno 升级导致内置工具改名/改签名时，
业务代码只改这里，不用全仓库搜替换。
"""

from __future__ import annotations

from typing import Any

from zhixun.config.logging import get_logger

logger = get_logger(__name__)


def load_builtin_tools(names: list[str] | None = None) -> list[Any]:
    """按名称加载 Agno 内置工具包（延迟 import）。

    目前预留 DuckDuckGoTools / FileTools 等常用工具，
    TODO(第 3 篇): 按需补齐，并在 Harness 层做权限裁剪。
    """
    names = names or []
    tools: list[Any] = []

    for name in names:
        if name == "duckduckgo":
            from agno.tools.duckduckgo import DuckDuckGoTools

            tools.append(DuckDuckGoTools())
        elif name == "file":
            from agno.tools.file import FileTools

            tools.append(FileTools())
        else:
            logger.warning("builtin_tools.unknown", name=name)

    return tools
