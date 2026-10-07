"""GitHub 采集工具 —— 项目的第一信源。

## 这个工具解决了什么

第二篇结束时，采集员"看起来"能列出一批项目 —— 但那全是模型**编的**。
LLM 见过 2024 年之前的 GitHub，它对"本周新出现的 AI 项目"一无所知。
你问它，它会给你一批**听起来非常合理、但根本不存在或早已过时**的仓库名。

工具的作用就是把这件事从"回忆"变成"查询"。

## 生产级工具的四个必备件

这是本篇的核心内容，四个都能在这里找到对应实现：

| 必备件 | 这个文件里的体现 |
|---|---|
| **① 统一的 HTTP 出口** | 所有请求走 `zhixun.tools.http.request_json`，重试策略集中一处 |
| **② 参数钳制** | `limit` 被 `clamp_int` 夹在 [1, 100]，模型传 99999 也打不爆 API |
| **③ 限流可观测** | 读 `X-RateLimit-Remaining`，剩余不足就打日志预警 |
| **④ 失败可归因** | 返回体里带 `error` / `failed_sources`，而不是静默返回空列表 |

## 一个刻意的设计：工具返回 dict 而不是抛异常

对**可预期的失败**（限流、超时、仓库不存在），工具**返回**一个带 `ok: False` 的结果，
而不是抛异常。原因：异常会中断 Agent 的推理循环，而返回结果会让模型**看到失败并自己决策**
（换关键词、少抓几条、或者如实汇报"这个源没抓到"）。

只有**不可接受的输入**（内网 URL、越权平台）才抛异常 —— 那是 Harness 该拦的。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Final

from agno.tools import tool

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings
from zhixun.tools.errors import FatalToolError, ToolError
from zhixun.tools.guards import audit_tool_call, clamp_int, clamp_text
from zhixun.tools.http import request_json

logger = get_logger(__name__)

GITHUB_API: Final[str] = "https://api.github.com"
GITHUB_SEARCH_API: Final[str] = f"{GITHUB_API}/search/repositories"

# 单次请求最多取多少条 —— 这是**写死的上限**，不来自配置，也不能被模型覆盖。
# GitHub 搜索接口本身的上限就是 100，超过会被 422 拒绝；写死是因为它属于"外部契约"，
# 不是一个可以调优的业务参数。
HARD_LIMIT: Final[int] = 100
README_HARD_LIMIT: Final[int] = 40_000

# 默认追踪的 topic。把它们放在代码里而不是提示词里 ——
# 因为"要跟踪哪几个技术方向"是产品策略，而"一次最多查几个"是资源约束。
DEFAULT_TOPICS: Final[tuple[str, ...]] = ("ai", "llm", "agent")
MAX_TOPICS: Final[int] = 5
GITHUB_MAX_PER_PAGE: Final[int] = 100


@dataclass(slots=True)
class RepoItem:
    """一条 GitHub 项目记录（工具层的统一数据契约）。"""

    full_name: str
    html_url: str
    description: str
    stars: int
    language: str | None
    topics: list[str]
    pushed_at: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "zhixun-bot/0.1",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


def _parse_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """把 GitHub 原始返回体映射成本项目的统一契约。

    注意 `.get(...)` 的兜底：GitHub 的字段会变（比如 `topics` 在旧仓库上没有），
    **映射层要能容忍缺字段，而不是让 KeyError 把整轮采集炸掉**。
    """
    return [
        RepoItem(
            full_name=item.get("full_name", ""),
            html_url=item.get("html_url", ""),
            description=item.get("description") or "",
            stars=item.get("stargazers_count", 0),
            language=item.get("language"),
            topics=item.get("topics", []),
            pushed_at=item.get("pushed_at", ""),
            created_at=item.get("created_at", ""),
        ).to_dict()
        for item in payload.get("items", [])
    ]


@tool(
    name="fetch_trending_repos",
    description=(
        "抓取最近 N 天内创建、按 star 数排序的 GitHub 仓库，用于追踪新出现的 AI 项目。"
        "参数 days 默认 7，limit 默认 30（上限 100，超出会被自动收敛）。"
    ),
    pre_hook=audit_tool_call,
    cache_results=True,
    cache_ttl=1800,
)
def fetch_trending_repos(
    days: int = 7,
    limit: int | None = None,
    topics: list[str] | None = None,
    min_stars: int = 50,
) -> dict[str, Any]:
    """抓取 GitHub 近期热门仓库。

    实现上是**按 topic 分路查询再合并去重**，而不是拼一个带 `OR` 的大查询。
    原因是踩过坑：GitHub 搜索 API 对 `topic:ai OR topic:llm OR topic:agent` 这种
    不带括号的写法直接返回 422，而加了括号之后 `stars:>` 过滤会失效（返回 0 条）。
    分路查询虽然多花几次请求，但**每一路的语义都是明确的**，而且天然支持"部分成功"。

    Returns:
        {"ok": bool, "items": [...], "count": int, "failed_sources": [...], "error": str | None}

    Notes:
        `days` / `limit` / `min_stars` / `topics` 全部经过钳制。
        模型如果说"帮我抓最近 3650 天的"（它真的会这么说），这里会静默收敛到 90 天。
    """
    days = clamp_int(days, lo=1, hi=90, name="days")
    limit = clamp_int(
        limit if limit is not None else settings.collector_max_items,
        lo=1,
        hi=HARD_LIMIT,
        name="limit",
    )
    min_stars = clamp_int(min_stars, lo=0, hi=1_000_000, name="min_stars")

    # topic 列表也要限长：模型给你 30 个 topic 的话，这一轮就要发 30 次请求
    topic_list = [str(t).strip() for t in (topics or DEFAULT_TOPICS) if str(t).strip()]
    if len(topic_list) > MAX_TOPICS:
        logger.warning("github.too_many_topics", requested=len(topic_list), kept=MAX_TOPICS)
        topic_list = topic_list[:MAX_TOPICS]
    if not topic_list:
        topic_list = list(DEFAULT_TOPICS)

    since = (date.today() - timedelta(days=days)).isoformat()
    per_topic = max(1, min(limit, GITHUB_MAX_PER_PAGE))

    merged: dict[str, dict[str, Any]] = {}
    failed: list[str] = []

    for topic in topic_list:
        query = f"created:>{since} stars:>{min_stars} topic:{topic}"
        try:
            payload = request_json(
                GITHUB_SEARCH_API,
                tool="fetch_trending_repos",
                params={
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": per_topic,
                },
                headers=_headers(),
            )
        except ToolError as exc:
            # 单个 topic 失败不影响其他 topic —— 部分成功好过整体失败
            failed.append(f"github:{topic}（{exc.detail}）")
            logger.warning("github.topic_failed", topic=topic, error=exc.detail)
            continue

        for item in _parse_items(payload):
            # 同一仓库可能同时带 ai 和 llm 两个 topic，按 full_name 去重
            merged.setdefault(item["full_name"], item)

    items = sorted(merged.values(), key=lambda row: row["stars"], reverse=True)[:limit]
    logger.info(
        "github.fetched",
        count=len(items),
        topics=topic_list,
        failed=len(failed),
        days=days,
    )
    return {
        "ok": bool(items),
        "items": items,
        "count": len(items),
        "failed_sources": failed,
        "error": None if items else "所有 topic 查询均未返回结果",
    }


@tool(
    name="get_repo_readme",
    description="获取指定 GitHub 仓库的 README 原文（Markdown）。输入格式为 owner/name。",
    pre_hook=audit_tool_call,
    cache_results=True,
    cache_ttl=3600,
)
def get_repo_readme(full_name: str, max_chars: int | None = None) -> dict[str, Any]:
    """获取仓库 README。

    Returns:
        {"ok": bool, "full_name": str, "content": str, "error": str | None}

    Notes:
        `max_chars` 默认取 `settings.tool_result_max_chars`。
        README 动辄两三万字，直接塞进上下文会挤掉其他所有素材 ——
        **截断不是省 token，是保护推理质量**。
    """
    repo = (full_name or "").strip()
    # 白名单式校验：只接受 owner/name 形态，挡掉路径穿越与 URL 注入
    if repo.count("/") != 1 or any(c.isspace() for c in repo):
        raise FatalToolError(
            "仓库标识格式非法",
            tool="get_repo_readme",
            detail=f"需要 owner/name 形式，收到 {repo!r}",
        )

    limit = clamp_int(
        max_chars if max_chars is not None else settings.tool_result_max_chars,
        lo=500,
        hi=README_HARD_LIMIT,
        name="max_chars",
    )

    import base64

    try:
        payload = request_json(
            f"{GITHUB_API}/repos/{repo}/readme",
            tool="get_repo_readme",
            headers=_headers(),
        )
    except ToolError as exc:
        logger.warning("github.readme_failed", repo=repo, error=exc.detail)
        return {"ok": False, "full_name": repo, "content": "", "error": exc.detail}

    raw = payload.get("content", "")
    try:
        text = base64.b64decode(raw).decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001 - 兼容 GitHub 各种奇怪的编码返回
        logger.warning("github.readme_decode_failed", repo=repo, error=str(exc))
        return {"ok": False, "full_name": repo, "content": "", "error": f"README 解码失败：{exc}"}

    return {
        "ok": True,
        "full_name": repo,
        "content": clamp_text(text, max_chars=limit, name="readme"),
        "error": None,
    }


GITHUB_TOOLS = [fetch_trending_repos, get_repo_readme]
