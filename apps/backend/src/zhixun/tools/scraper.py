"""网页抓取工具 —— 把项目主页 / 文档站抓成干净 Markdown。

为什么用 Jina Reader 而不是自己写 HTML 解析？
因为它把"网页 → 正文 Markdown"这件事变成了一个 GET 请求：

    https://r.jina.ai/https://github.com/agno-agi/agno

免费、无需 API key、直接返回 Markdown，而且**去掉了导航栏与广告**。
自己用 BeautifulSoup 写一遍，效果大概率不如它，还多了三个依赖。

## 这个文件是 Harness「机械强制」的最佳示例

抓取类工具是**最危险的只读工具** —— 因为 URL 是模型给的。

模型可能给你：

- `http://169.254.169.254/latest/meta-data/` —— 云主机元数据，**拿到就等于拿到云凭证**
- `http://localhost:8000/api/v1/drafts` —— 你自己的内网服务，绕过了所有鉴权
- `file:///etc/passwd` —— 本地文件

这不是模型"坏"，是它**不知道这些地址在你环境里意味着什么**。
所以这件事不能写给模型看，只能写在代码里：

```python
assert_url_allowed(url, tool="fetch_webpage_markdown")   # 一行，拦住上面全部三种
```

**这就是"机械强制"与"提示词劝说"的区别** —— 它的效果不取决于模型今天的心情。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from agno.tools import tool

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings
from zhixun.tools.errors import FatalToolError, ToolError
from zhixun.tools.guards import audit_tool_call, assert_url_allowed, clamp_int, clamp_text
from zhixun.tools.http import request_text

logger = get_logger(__name__)

SCRAPER_HARD_LIMIT = 60_000


@tool(
    name="fetch_webpage_markdown",
    description=(
        "抓取指定网页并转换为 Markdown 正文，自动去掉导航与广告。"
        "适合读项目文档、博客与发布说明。只支持 http/https 公网地址。"
    ),
    pre_hook=audit_tool_call,
    cache_results=True,
    cache_ttl=3600,
)
def fetch_webpage_markdown(url: str, max_chars: int | None = None) -> dict[str, Any]:
    """抓取网页正文（Markdown）。

    Returns:
        {"ok": bool, "url": str, "content": str, "error": str | None}

    Raises:
        FatalToolError: URL 协议非法 / 指向内网或云元数据地址（不可重试）
    """
    # ---- 护栏①：URL 安全校验。命中即抛，不给"重试一下说不定能过"的机会 ----
    safe_url = assert_url_allowed(url, tool="fetch_webpage_markdown")

    limit = clamp_int(
        max_chars if max_chars is not None else settings.tool_result_max_chars,
        lo=500,
        hi=SCRAPER_HARD_LIMIT,
        name="max_chars",
    )

    # Jina Reader 的调用形态就是"把目标 URL 拼在自己后面"
    target = f"{settings.jina_reader_base_url.rstrip('/')}/{safe_url}"
    headers: dict[str, str] = {"Accept": "text/plain"}
    if settings.jina_api_key:
        headers["Authorization"] = f"Bearer {settings.jina_api_key}"

    try:
        text = request_text(target, tool="fetch_webpage_markdown", headers=headers)
    except ToolError as exc:
        logger.warning("scraper.failed", url=safe_url, error=exc.detail)
        return {"ok": False, "url": safe_url, "content": "", "error": exc.detail}

    if not text.strip():
        return {"ok": False, "url": safe_url, "content": "", "error": "抓取结果为空（页面可能是纯 JS 渲染）"}

    logger.info("scraper.ok", url=safe_url, chars=len(text))
    return {
        "ok": True,
        "url": safe_url,
        "content": clamp_text(text, max_chars=limit, name="webpage"),
        "error": None,
    }


SCRAPER_TOOLS = [fetch_webpage_markdown]
