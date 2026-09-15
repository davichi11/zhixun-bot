"""历史去重策略。

去重为什么需要 LLM（而不是简单的 URL 比对）：
- 同一个项目可能换域名/改仓库名重新出现
- 同一件事可能被不同项目重复实现（"又一个 RAG 框架"）
- 读者真正在意的是"我是不是已经看过类似的东西"

所以采用两段式：
1. **URL 精确匹配**（便宜，命中即拦截）
2. **标题 Embedding 相似度**（阈值可配，默认 0.85）

第 1 篇：定义策略接口。
第 4 篇：落地与调参（阈值、Embedding 模型选择）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings

logger = get_logger(__name__)


@dataclass(slots=True)
class DedupVerdict:
    """去重判定结果。"""

    is_duplicate: bool
    reason: str
    matched: str | None = None
    similarity: float = 0.0


class DedupStrategy:
    """两段式去重。"""

    def __init__(self, threshold: float | None = None) -> None:
        self.threshold = threshold or settings.dedup_similarity_threshold

    def check_url(self, url: str, published_urls: set[str]) -> DedupVerdict:
        """第一段：URL 精确匹配。"""
        if url in published_urls:
            return DedupVerdict(True, "URL 精确命中历史已发布项目", matched=url, similarity=1.0)
        return DedupVerdict(False, "URL 未命中")

    def check_title(self, title: str, published_titles: dict[str, Any]) -> DedupVerdict:
        """第二段：标题语义相似度。

        TODO(第 4 篇): 用 Embedding + 余弦相似度实现；第 1 篇先占位。
        """
        logger.debug("dedup.check_title", title=title, candidates=len(published_titles))
        return DedupVerdict(False, "标题相似度未超阈值")

    def check(self, *, url: str, title: str, published: Any) -> DedupVerdict:
        """组合两段式判定：URL 命中即返回，否则走语义比对。"""
        verdict = self.check_url(url, set(getattr(published, "urls", set())))
        if verdict.is_duplicate:
            return verdict
        return self.check_title(title, getattr(published, "titles", {}))
