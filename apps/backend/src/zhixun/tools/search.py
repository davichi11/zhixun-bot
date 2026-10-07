"""网页搜索工具 —— 补充信源与事实核查。

## 这个文件的主题：**可选依赖的优雅降级**

Agno 3.x 内置了 20+ 个工具包，但它们**大多依赖第三方 SDK**：

```python
from agno.tools.duckduckgo import DuckDuckGoTools
# ImportError: `ddgs` not installed. Please install using `pip install ddgs`
```

一个中型项目会用到 5~10 个工具包，每个都带一坨依赖。如果全部写进 `pyproject.toml`：

- 镜像体积翻倍，CI 安装时间从 40 秒变成 4 分钟
- 某个包和你的 Python 版本不兼容，**整个服务起不来**
- 而其中 80% 的能力你根本没用上

所以本项目的策略是：**把内置工具包当"可选能力"，用的时候才 import，缺了就降级。**

```
① 优先 DuckDuckGo（装了 ddgs 就用，质量最好、返回结构化结果）
      ↓ 没装 / 调用失败
② 降级 Jina Search（只要 httpx，永远可用，返回纯文本）
      ↓ 也失败
③ 返回 ok=False 并说明原因（让模型知道"这条路走不通"，而不是编造结果）
```

**降级不是失败，静默降级才是。** 每一次降级都会打日志、并在返回值里说明，
这样你在第 8 篇做评估时能一眼看出"这周的搜索质量下降是因为降级了"。
"""

from __future__ import annotations

import importlib.util
from typing import Any, Final

from agno.tools import tool

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings
from zhixun.tools.errors import ToolError
from zhixun.tools.guards import audit_tool_call, clamp_int, clamp_text
from zhixun.tools.http import request_text

logger = get_logger(__name__)

MAX_RESULTS_HARD_LIMIT: Final[int] = 20
_JINA_SNIPPET_CHARS: Final[int] = 3_000


def _has_ddgs() -> bool:
    """检查可选依赖是否可用（只查模块文件，不 import，避免 ImportError 打断启动）。"""
    return importlib.util.find_spec("ddgs") is not None


def _search_duckduckgo(query: str, max_results: int) -> list[dict[str, Any]]:
    """首选路径：DuckDuckGo（需要 `pip install ddgs`）。"""
    from ddgs import DDGS  # 延迟 import：只有真的走到这条路才会加载

    rows = DDGS().text(query, max_results=max_results)
    return [
        {
            "title": row.get("title", ""),
            "url": row.get("href") or row.get("url", ""),
            "snippet": row.get("body", ""),
        }
        for row in (rows or [])
    ]


def _search_jina(query: str, max_results: int) -> list[dict[str, Any]]:
    """降级路径：Jina Search（只要 httpx，返回一段 Markdown 文本）。

    Jina 返回的是"已经整理好的长文本"，不是结构化结果列表 ——
    所以我们把它包成一条结果，并**在 title 里明确标注这是降级结果**。
    """
    target = f"{settings.jina_search_base_url.rstrip('/')}/{query}"
    headers: dict[str, str] = {"Accept": "text/plain"}
    if settings.jina_api_key:
        headers["Authorization"] = f"Bearer {settings.jina_api_key}"

    text = request_text(target, tool="web_search", headers=headers)
    return [
        {
            "title": "(降级：Jina Search 文本结果)",
            "url": "",
            "snippet": clamp_text(text, max_chars=_JINA_SNIPPET_CHARS, name="jina_search"),
        }
    ]


@tool(
    name="web_search",
    description=(
        "通用网页搜索，输入查询词，返回标题 / 链接 / 摘要列表。"
        "用于补充信源与事实核查。max_results 默认 5，上限 20。"
    ),
    pre_hook=audit_tool_call,
    cache_results=True,
    cache_ttl=1800,
)
def web_search(query: str, max_results: int | None = None) -> dict[str, Any]:
    """网页搜索（自动选择可用后端）。

    Returns:
        {"ok": bool, "backend": str, "results": [...], "error": str | None}
    """
    q = (query or "").strip()
    if not q:
        return {"ok": False, "backend": "none", "results": [], "error": "查询词为空"}

    n = clamp_int(
        max_results if max_results is not None else 5,
        lo=1,
        hi=MAX_RESULTS_HARD_LIMIT,
        name="max_results",
    )

    # ---- 首选：DuckDuckGo ----
    if _has_ddgs():
        try:
            results = _search_duckduckgo(q, n)
            logger.info("search.ok", backend="duckduckgo", query=q, count=len(results))
            return {"ok": True, "backend": "duckduckgo", "results": results, "error": None}
        except Exception as exc:  # noqa: BLE001 - 第三方库异常类型不稳定，统一兜住后降级
            logger.warning("search.ddg_failed_fallback_jina", query=q, error=str(exc))
    else:
        logger.info("search.ddg_unavailable", hint="pip install ddgs 可启用首选后端")

    # ---- 降级：Jina Search ----
    try:
        results = _search_jina(q, n)
        logger.info("search.degraded", backend="jina", query=q)
        return {"ok": True, "backend": "jina(降级)", "results": results, "error": None}
    except ToolError as exc:
        logger.error("search.all_backends_failed", query=q, error=exc.detail)
        return {"ok": False, "backend": "none", "results": [], "error": exc.detail}


SEARCH_TOOLS = [web_search]
