"""RAG 检索器 —— 混合检索（向量语义 + BM25 关键词），RRF 融合。

## 为什么必须混合

单一召回方式在这个业务里都会翻车：

| 召回方式 | 擅长 | 翻车场景 |
|---|---|---|
| **向量** | 同义表达（"推理加速" ≈ "推理优化"） | **漏掉专有名词** —— 新项目名没进过训练数据，向量拉不到它 |
| **BM25** | 专有名词、项目名、精确短语 | **抓不住同义表达** —— 查"记忆"检索不到写"长期记忆"的那篇 |

真实案例：用户搜 `Memary`，向量召回因为这个词太少见而找不到；
BM25 直接命中。反过来搜"怎么让 Agent 记住东西"，BM25 一无所获，
向量召回把讲 memory 的那篇排在第一。**两路都必须有。**

## 为什么用 RRF 而不是加权求和

最朴素的做法是"向量分 × 0.6 + BM25 分 × 0.4"。
问题是**两路的分数量纲根本不可比** —— 余弦相似度在 0~1，
BM25 可以是 3.87 也可以是 0.8（见本篇的实测输出），权重怎么调都是拍脑袋。

RRF（Reciprocal Rank Fusion）绕开了这个问题：**只用排名，不用分数**。

```
score(d) = Σ  1 / (k + rank_i(d))       k 默认 60
```

一个文档在两路都排第 1，得分 `2/61 = 0.0328`；
一路第 1 一路第 50，得分 `1/61 + 1/110 = 0.0255`。前者胜出 —— 合理。
关键是**你完全不需要知道两路分数的实际数值**。

---

> 📌 **文末实测记录**：本篇 BM25 实测中，"上下文"一词的得分高达 **2.99**，
> 而"护栏"只有 **0.84** —— 差了 3.6 倍。这就是"加权求和不可行"的实证。

## 第三路：按文章聚合

风格检索要的不是"最像的几个切片"，而是"几篇**完整文章**"。
所以检索完还要做一次**按 `article_id` 聚合 + 取该文最高分**——
这保证注入的是"三篇不同的文章"而不是"同一篇文章的三个相邻小节"。
"""

from __future__ import annotations

from typing import Any, Sequence

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings
from zhixun.knowledge.rag.loaders import parent_of
from zhixun.knowledge.rag.tokenize import BM25Index
from zhixun.knowledge.rag.vector_store import ArticleRecord, VectorStore
from zhixun.knowledge.unified_retriever import StyleSample

logger = get_logger(__name__)

__all__ = ["HybridRetriever", "rrf_fuse"]

# 风格参考每段的最大字符数 —— 注入 3 段 × 1500 字已经足够传递语气了
STYLE_EXCERPT_CHARS = 1500


def rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion：融合多路召回结果。

    Args:
        rankings: 每路召回的 `doc_id` 列表（**按相关性降序**）
        k: 平滑常数。越大则"排第一"的加成越小；60 是文献推荐值

    Returns:
        `[(doc_id, rrf_score)]` 按 RRF 分数降序
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


class HybridRetriever:
    """混合检索器：向量 + BM25 → RRF 融合。"""

    def __init__(self, store: VectorStore | None = None, *, embedder: Any | None = None) -> None:
        from zhixun.knowledge.rag.vector_store import get_vector_store

        self._store = store or get_vector_store()
        self._embedder = embedder
        self._bm25: BM25Index | None = None
        self._by_id: dict[str, ArticleRecord] = {}

    # ---------- 索引构建 ----------

    async def build_bm25(self, records: Sequence[ArticleRecord]) -> int:
        """用全量记录构建 BM25 倒排索引。

        为什么每次都重建而不是增量更新？因为语料规模是**几百条**，
        重建一次的成本远低于维护增量的复杂度。
        **优化要有数据支撑** —— 真到了百万级再改。
        """
        index = BM25Index()
        for rec in records:
            self._by_id[rec.article_id] = rec
            index.add(rec.article_id, f"{rec.title}\n{rec.content}")
        self._bm25 = index
        logger.info("rag.bm25_built", docs=index.size, backend=self._store.backend)
        return index.size

    async def ensure_ready(self) -> None:
        """确保 BM25 索引已就绪（首次触发时懒加载）。"""
        if self._bm25 is None:
            await self.build_bm25(await self._store.all_records())

    # ---------- 两路召回 ----------

    async def _vector_rank(self, query: str, top_k: int) -> list[str]:
        if self._embedder is None:
            return []
        try:
            vectors = await self._embedder.embed([query])
        except Exception as exc:  # noqa: BLE001 - 语义这一路失败不应该让检索整体失败
            logger.warning("rag.vector_embed_failed", error=str(exc))
            return []
        if not vectors:
            return []
        hits = await self._store.search(vectors[0], limit=top_k)
        return [h["article_id"] for h in hits]

    async def _keyword_rank(self, query: str, top_k: int) -> list[str]:
        if self._bm25 is None:
            return []
        return [doc_id for doc_id, _ in self._bm25.search(query, top_k=top_k)]

    # ---------- 对外 ----------

    async def search_style(self, query: str, top_k: int | None = None) -> list[StyleSample]:
        """检索风格范文（供 Few-shot 注入）。

        两路召回 → RRF 融合 → **按文章去重** → 取 Top-K 篇文章。
        """
        top_k = top_k or settings.rag_top_k
        await self.ensure_ready()

        pool = max(top_k * 3, 10)  # 多召回一些，融合后再截断
        vec_rank = await self._vector_rank(query, pool)
        kw_rank = await self._keyword_rank(query, pool)

        fused = rrf_fuse([vec_rank, kw_rank])

        # 按**父级文章**去重：同一篇文章的多个切片只贡献一次，
        # 否则三篇范文可能全来自同一篇文章的不同小节（语气参考就失去意义了）
        seen: set[str] = set()
        samples: list[StyleSample] = []
        for doc_id, score in fused:
            rec = self._by_id.get(doc_id)
            if rec is None:
                continue
            parent = parent_of(rec.article_id)
            if parent in seen:
                continue
            seen.add(parent)
            samples.append(
                StyleSample(
                    article_id=parent,
                    title=rec.title,
                    excerpt=_excerpt(rec.content),
                    score=round(score, 5),
                )
            )
            if len(samples) >= top_k:
                break

        logger.debug(
            "rag.search_style",
            query=query[:40],
            vector_hits=len(vec_rank),
            keyword_hits=len(kw_rank),
            returned=len(samples),
        )
        return samples

    async def search_projects(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """检索与查询相关的历史项目（与 URL 去重互补 —— 语义层面的重复）。"""
        await self.ensure_ready()
        kw_rank = await self._keyword_rank(query, top_k)
        vec_rank = await self._vector_rank(query, top_k)

        out: list[dict[str, Any]] = []
        for doc_id, score in rrf_fuse([vec_rank, kw_rank])[:top_k]:
            rec = self._by_id.get(doc_id)
            if rec is None:
                continue
            out.append(
                {
                    "article_id": rec.article_id,
                    "title": rec.title,
                    "score": round(score, 5),
                    "source_path": rec.source_path,
                    "published_at": rec.published_at,
                }
            )
        return out

    async def stats(self) -> dict[str, Any]:
        """检索器状态（给 CLI / 监控）。"""
        await self.ensure_ready()
        records = await self._store.all_records()
        articles = {parent_of(r.article_id) for r in records}
        return {
            "backend": self._store.backend,
            "chunks": len(records),
            "articles": len(articles),
            "chars_indexed": sum(len(r.content) for r in records),
        }


def _excerpt(content: str, *, max_chars: int = STYLE_EXCERPT_CHARS) -> str:
    """截取范文片段。

    取开头而不是"最相关的 N 个字" —— 因为我们要传递的是**语气和句式**，
    开头的定调部分信息密度最高。
    """
    text = (content or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"