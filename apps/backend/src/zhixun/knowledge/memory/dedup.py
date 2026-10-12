"""历史去重策略 —— 两段式：URL 精确匹配 + 标题语义相似度。

## 为什么去重不能只比 URL

因为同一个项目会以各种形态再次出现：

| 形态 | 上周写的 | 这周又出现了 |
|---|---|---|
| 改名/转移 | `github.com/old/repo` | `github.com/new/repo` |
| 追踪参数 | `github.com/a/b` | `github.com/a/b?utm_source=x` |
| 镜像 | `github.com/a/b` | `gitlab.com/a/b` |
| **同题异构** | `LangMem` | `另一个记忆框架 Memary` |

前三行用 URL 规范化就能解决，**第四行只有语义比对能解决**。
而对周报这种内容来说，第四行才是读者真正会抱怨的（"这个我上周看过了"）。

## 为什么顺序不能反

```
第 1 段：URL 规范化后精确匹配   →  纯字符串比较，成本≈0
第 2 段：标题 Embedding 相似度  →  一次 Embedding 调用 + N 次余弦
```

**先便宜的后贵的，而且命中即短路。**
500 条历史项目做标题比对是一次真实的 Embedding 调用，
如果 80% 的重复其实是"同一个 URL 带了 utm 参数"，那这 80% 的 Embedding 全是浪费。

## URL 规范化才是第一段的重点

比 URL 难的不是"比较"，是"归一"。下面这些必须折叠成同一个键：

- 协议差异：`http://` vs `https://`
- `www.` 前缀
- 结尾斜杠：`/a/b` vs `/a/b/`
- `.git` 后缀
- 查询参数与锚点：`?utm_source=...` / `#readme`
- GitHub 的 `tree/main` 路径 → 仓库根

**规范化漏一条，去重就漏一批。** 这是那种"上线三个月后才发现"的 bug。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence
from urllib.parse import urlparse, urlunparse

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings
from zhixun.knowledge.rag.embedders import cosine_similarity

logger = get_logger(__name__)


@dataclass(slots=True)
class DedupVerdict:
    """去重判定结果。"""

    is_duplicate: bool
    reason: str
    matched: str | None = None
    similarity: float = 0.0
    stage: str = ""  # "url" / "title" / ""（未命中）


# ------------------------------------------------------------------ URL 规范化

# GitHub / GitLab 的代码路径前缀：它们指向同一个仓库，不是不同页面
_CODE_PATH_PREFIXES = ("tree", "blob", "commit", "commits", "releases", "issues", "pull")


def normalize_url(url: str) -> str:
    """把 URL 折叠成用于比较的规范形式。

    Example:
        >>> normalize_url("https://WWW.Github.com/Agno-AGI/Agno/?utm_source=x#readme")
        'github.com/agno-agi/agno'
        >>> normalize_url("http://github.com/agno-agi/agno.git")
        'github.com/agno-agi/agno'
    """
    raw = (url or "").strip()
    if not raw:
        return ""

    # 补全协议：URL 解析器不接受没有 scheme 的字符串
    if not raw.startswith(("http://", "https://", "git@")):
        raw = "https://" + raw

    parsed = urlparse(raw)

    # SSH 形式 git@github.com:owner/repo
    if parsed.scheme == "git@" or "@" in raw.split("://")[0]:
        _, _, path = raw.partition("@")
        host, _, repo = path.partition(":")
        return f"{host.lower().removeprefix('www.')}/{repo.removesuffix('.git').strip('/').lower()}"

    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]

    # 折叠代码路径：/a/b/tree/main/src → /a/b
    segments = path.strip("/").split("/")
    if len(segments) > 2 and segments[2].lower() in _CODE_PATH_PREFIXES:
        segments = segments[:2]
        path = "/" + "/".join(segments)

    return f"{host}{path}".rstrip("/").lower()


# ------------------------------------------------------------------ 去重策略


def _semantic_text(item: Any) -> str:
    """取候选的"语义比对文本"。

    优先 `title`（人类可读标题），退回 `name` / `full_name`。

    为什么不用仓库名做主键？因为第二段专门抓**同题异构** ——
    `agno` 和 `agno-v2` 的仓库名不同，但标题都是"Agno 智能体框架"，
    这正是读者会抱怨的"这个我上周看过了"。拿仓库名去比，语义段就完全失效了。
    """
    for attr in ("title", "name", "full_name"):
        value = getattr(item, attr, "") or ""
        if value.strip():
            return value.strip()
    return ""


class DedupStrategy:
    """两段式去重。"""

    def __init__(self, threshold: float | None = None) -> None:
        self.threshold = threshold if threshold is not None else settings.dedup_similarity_threshold

    # ---------- 第 1 段：URL ----------

    def build_url_index(self, published: Sequence[Any]) -> set[str]:
        """把历史项目压成一个规范化 URL 集合。"""
        index: set[str] = set()
        for p in published:
            raw = getattr(p, "url", None) or ""
            norm = normalize_url(raw)
            if norm:
                index.add(norm)
        return index

    def check_url(self, url: str, published_urls: set[str]) -> DedupVerdict:
        """第一段：URL 规范化后精确匹配。"""
        norm = normalize_url(url)
        if norm and norm in published_urls:
            return DedupVerdict(
                True, "URL 规范化后精确命中历史已发布项目", matched=norm, similarity=1.0, stage="url"
            )
        return DedupVerdict(False, "URL 未命中", stage="url")

    # ---------- 第 2 段：标题语义 ----------

    async def check_title(
        self,
        title: str,
        candidates: Sequence[Any],
        embedder: Any,
    ) -> DedupVerdict:
        """第二段：标题 Embedding 相似度。

        关键优化：**一次 embedder 调用批量编码全部候选**，
        而不是逐条调用。逐条调用 500 次 API 的成本和耗时都不可接受。
        """
        title = (title or "").strip()
        if not title or not candidates:
            return DedupVerdict(False, "标题为空或无候选，跳过语义比对", stage="title")

        candidate_texts = [
            (getattr(c, "title", "") or getattr(c, "full_name", "") or "") for c in candidates
        ]
        candidate_texts = [t for t in candidate_texts if t.strip()]
        if not candidate_texts:
            return DedupVerdict(False, "候选标题全为空", stage="title")

        vectors = await embedder.embed([title, *candidate_texts])
        target, rest = vectors[0], vectors[1:]

        best_score, best_idx = 0.0, -1
        for i, vec in enumerate(rest):
            score = cosine_similarity(target, vec)
            if score > best_score:
                best_score, best_idx = score, i

        if best_idx >= 0 and best_score >= self.threshold:
            matched = candidates[best_idx]
            return DedupVerdict(
                True,
                f"标题相似度 {best_score:.3f} ≥ 阈值 {self.threshold}",
                matched=getattr(matched, "title", "") or getattr(matched, "full_name", ""),
                similarity=round(best_score, 4),
                stage="title",
            )

        return DedupVerdict(
            False,
            f"最高标题相似度 {best_score:.3f} < 阈值 {self.threshold}",
            similarity=round(best_score, 4),
            stage="title",
        )

    # ---------- 组合 ----------

    async def check(
        self,
        *,
        url: str,
        title: str,
        published: Sequence[Any],
        embedder: Any | None = None,
        url_index: set[str] | None = None,
    ) -> DedupVerdict:
        """两段式判定：URL 命中即短路返回，否则走语义比对。

        Args:
            url: 本次候选的 URL
            title: 本次候选的标题 / 项目名
            published: 历史已发布项目列表
            embedder: Embedding 实现；为 None 时跳过第二段
            url_index: 预先算好的规范化 URL 索引（批量去重时复用，避免重复计算）
        """
        index = url_index if url_index is not None else self.build_url_index(published)

        verdict = self.check_url(url, index)
        if verdict.is_duplicate:
            return verdict

        if embedder is None:
            return DedupVerdict(
                False, "仅执行 URL 段（未提供 embedder）", similarity=0.0, stage="url"
            )

        return await self.check_title(title, published, embedder)

    async def filter_duplicates(
        self,
        candidates: Sequence[Any],
        *,
        embedder: Any,
        published: Sequence[Any],
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        """批量过滤：一次算好 URL 索引，逐个判定。

        Returns:
            `(保留项, 被剔除项详情)` —— 被剔除项带上原因，方便运营复盘
            "为什么这条被过滤了"。
        """
        url_index = self.build_url_index(published)
        keep: list[Any] = []
        dropped: list[dict[str, Any]] = []

        for item in candidates:
            verdict = await self.check(
                url=getattr(item, "url", "") or "",
                # ⚠️ 顺序很重要：**优先用 title，而不是 name**。
                # 第二段要抓的正是"同题异构"—— 仓库名不同（agno vs agno-v2）
                # 恰恰是重复的证据之一，拿仓库名去比会 100% 漏判。
                title=_semantic_text(item),
                published=published,
                embedder=embedder,
                url_index=url_index,
            )
            if verdict.is_duplicate:
                dropped.append(
                    {
                        "item": getattr(item, "full_name", "") or getattr(item, "name", ""),
                        "stage": verdict.stage,
                        "reason": verdict.reason,
                        "matched": verdict.matched,
                        "similarity": verdict.similarity,
                    }
                )
            else:
                keep.append(item)

        logger.info(
            "dedup.filter_done",
            total=len(candidates),
            kept=len(keep),
            dropped=len(dropped),
            by_url=sum(1 for d in dropped if d["stage"] == "url"),
            by_title=sum(1 for d in dropped if d["stage"] == "title"),
        )
        return keep, dropped