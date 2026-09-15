"""GitHub 采集工具 —— 项目的主要信源。

第 1 篇：只放工具签名与实现骨架，保证可被 Agent 注册。
第 3 篇：补齐分页、限流、重试与错误处理，并接入采集员 Agent。
第 7 篇：为写操作类工具叠加 Harness 的输入校验护栏。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

import httpx
from agno.tools import tool

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings

logger = get_logger(__name__)

GITHUB_SEARCH_API = "https://api.github.com/search/repositories"


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


@tool(
    name="fetch_trending_repos",
    description=(
        "抓取最近 N 天内创建、按 star 数排序的 GitHub 仓库，用于追踪新出现的 AI 项目。"
        "参数 days 默认 7，limit 默认使用配置中的 collector_max_items。"
    ),
)
def fetch_trending_repos(days: int = 7, limit: int | None = None) -> list[dict[str, Any]]:
    """抓取 GitHub 近期热门仓库。"""
    limit = limit or settings.collector_max_items
    since = (date.today() - timedelta(days=days)).isoformat()
    query = f"created:>{since} stars:>50 topic:ai OR topic:llm OR topic:agent"

    params = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": min(limit, 100),
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(GITHUB_SEARCH_API, params=params, headers=_headers())
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPError as exc:  # TODO(第 3 篇): 换成带退避的重试策略
        logger.warning("github.fetch_failed", error=str(exc), days=days)
        return []

    items = [
        RepoItem(
            full_name=item["full_name"],
            html_url=item["html_url"],
            description=item.get("description") or "",
            stars=item.get("stargazers_count", 0),
            language=item.get("language"),
            topics=item.get("topics", []),
            pushed_at=item.get("pushed_at", ""),
            created_at=item.get("created_at", ""),
        ).to_dict()
        for item in payload.get("items", [])
    ]

    logger.info("github.fetched", count=len(items), days=days)
    return items


@tool(name="get_repo_readme", description="获取指定 GitHub 仓库的 README 原文（Markdown）。")
def get_repo_readme(full_name: str, max_chars: int = 8000) -> str:
    """获取仓库 README（截断到 max_chars，控制上下文体积）。"""
    url = f"https://api.github.com/repos/{full_name}/readme"
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, headers=_headers())
            resp.raise_for_status()
            content = resp.json().get("content", "")
    except httpx.HTTPError as exc:
        logger.warning("github.readme_failed", repo=full_name, error=str(exc))
        return ""

    import base64

    text = base64.b64decode(content).decode("utf-8", errors="ignore")
    return text[:max_chars]


GITHUB_TOOLS = [fetch_trending_repos, get_repo_readme]
