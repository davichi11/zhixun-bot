"""RAG 检索器 —— 混合检索（语义相似 + 关键词召回）。

为什么混合检索？
- 纯向量：容易漏掉专有名词（项目名、库名）
- 纯关键词（BM25）：抓不住同义表达

所以用 RRF（Reciprocal Rank Fusion）把两路结果融合，再重排取 Top-K。

第 1 篇：定义接口与融合策略签名。
第 4 篇：落地实现，配合 `unified_retriever` 做风格迁移检索。
"""

from __future__ import annotations

from typing import Any

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings
from zhixun.knowledge.rag.vector_store import VectorStore
from zhixun.knowledge.unified_retriever import StyleSample

logger = get_logger(__name__)


def rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion：融合多路召回结果。"""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


class HybridRetriever:
    """混合检索器。"""

    def __init__(self, store: VectorStore | None = None) -> None:
        self._store = store or VectorStore()

    async def search_style(self, query: str, top_k: int | None = None) -> list[StyleSample]:
        """检索风格范文（供 Few-shot 注入）。"""
        top_k = top_k or settings.rag_top_k
        # TODO(第 4 篇): 向量召回 + BM25 召回 → RRF 融合 → 组装 StyleSample
        logger.debug("rag.search_style", query=query[:40], top_k=top_k)
        return []

    async def search_projects(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """检索与查询相关的历史项目（与去重互补）。"""
        # TODO(第 4 篇)
        return []
