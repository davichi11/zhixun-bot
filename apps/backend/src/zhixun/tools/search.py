"""网页搜索工具 —— 用于补充信源与事实核查。

第 3 篇会在这里接入 DuckDuckGo / Exa；第 1 篇先定义工具契约。
"""

from __future__ import annotations

from typing import Any

from agno.tools import tool

from zhixun.config.logging import get_logger

logger = get_logger(__name__)


@tool(
    name="web_search",
    description="通用网页搜索，输入查询词，返回标题/链接/摘要列表。用于补充信源与事实核查。",
)
def web_search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """网页搜索。

    TODO(第 3 篇): 接入 DuckDuckGo（免费）或 Exa（质量更高，需 Key）。
    """
    logger.info("search.requested", query=query, max_results=max_results)
    raise NotImplementedError("第 3 篇实现：接入 DuckDuckGo / Exa 搜索")


SEARCH_TOOLS = [web_search]
