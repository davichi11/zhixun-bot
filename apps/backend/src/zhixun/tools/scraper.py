"""网页抓取工具 —— 把项目主页 / 文档站抓成干净 Markdown。

第 3 篇实现（推荐 Jina Reader：https://r.jina.ai/<url>，免费且直接返回 Markdown）。
"""

from __future__ import annotations

from agno.tools import tool

from zhixun.config.logging import get_logger

logger = get_logger(__name__)


@tool(
    name="fetch_webpage_markdown",
    description="抓取指定网页并转换为 Markdown 正文，自动去掉导航与广告。适合读项目文档与博客。",
)
def fetch_webpage_markdown(url: str, max_chars: int = 12_000) -> str:
    """抓取网页正文（Markdown）。

    TODO(第 3 篇): 接入 Jina Reader，并加缓存避免重复抓取。
    """
    logger.info("scraper.requested", url=url)
    raise NotImplementedError("第 3 篇实现：接入 Jina Reader 抓取网页正文")


SCRAPER_TOOLS = [fetch_webpage_markdown]
