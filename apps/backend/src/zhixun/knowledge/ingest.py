"""入库管道 —— 把历史文章目录变成可检索的知识。

    Markdown 目录 → 切片 → 批量 Embedding → 向量库 → BM25 索引

## 为什么要有一个独立的"入库"概念？

因为**入库和查询的节奏完全不同**：

| | 入库 | 查询 |
|---|---|---|
| 触发 | 手动 / 定时（文章发布后） | 每次流水线运行 |
| 成本 | 高（Embedding 调用要花钱） | 低（只读） |
| 失败影响 | 下次重跑即可 | 当期内容质量下降 |

把两者混在一起，就出现了"每次跑流水线都重新算一遍 Embedding"的反模式 ——
既慢又贵。所以本项目把入库做成**显式命令**：

```bash
uv run zhixun knowledge --ingest --dir ./data/history
```

## 一个关键的取舍：chunk 级 vs article 级

我们按 `##` 切片入库（检索粒度细），但风格参考需要"整篇"（语气完整）。
于是有了 ID 的两层结构：

```
article_id = "art-2026-09-01-agent-架构#3"
                └──────────── 父级（整篇） ────┘ └ 切片序号 ┘
```

- 向量库按**切片**存（检索精确）
- 风格检索按**父级**去重（保证给的是三篇不同的文章）

这个约定写在 `parent_of()` 里 —— 后续第 7 篇的按需展开也依赖它。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zhixun.config.logging import get_logger
from zhixun.knowledge.rag.embedders import get_embedder
from zhixun.knowledge.rag.loaders import Chunk, MarkdownDirLoader, get_loader, parent_of, record_id
from zhixun.knowledge.rag.retriever import HybridRetriever
from zhixun.knowledge.rag.vector_store import ArticleRecord, get_vector_store

logger = get_logger(__name__)

__all__ = ["IngestResult", "ingest_history", "ingest_sync", "parent_of", "record_id", "describe_pipeline"]


@dataclass(slots=True)
class IngestResult:
    """入库结果（给 CLI 展示，也便于断言）。"""

    files: int = 0
    chunks: int = 0
    written: int = 0
    bm25_docs: int = 0
    backend: str = ""
    embedder: str = ""
    elapsed_ms: int = 0
    skipped: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"文件 {self.files} · 切片 {self.chunks} · 入库 {self.written} · "
            f"BM25 文档 {self.bm25_docs} · 后端 {self.backend} · Embedding {self.embedder}"
        )


async def ingest_history(
    root: str | Path | None = None,
    *,
    loader: Any | None = None,
    store: Any | None = None,
    embedder: Any | None = None,
    rebuild_bm25: bool = True,
) -> IngestResult:
    """执行一次入库。

    Args:
        root: 历史文章目录（默认取配置 `history_articles_dir`）
        loader / store / embedder: 允许注入，便于测试
        rebuild_bm25: 是否重建 BM25 索引

    Returns:
        `IngestResult`

    Notes:
        **入库失败不抛异常** —— 知识层是增强能力，不是硬依赖。
        返回值里能看到每个环节的数量，CLI 会据此给出提示。
    """
    started = time.perf_counter()

    loader = loader or get_loader(root)
    store = store or get_vector_store()
    embedder = embedder or get_embedder()

    chunks: list[Chunk] = loader.load() if isinstance(loader, MarkdownDirLoader) else loader.load()
    result = IngestResult(
        files=len({c.source_path for c in chunks}),
        chunks=len(chunks),
        backend=getattr(store, "backend", "unknown"),
        embedder=getattr(embedder, "name", type(embedder).__name__),
    )

    if not chunks:
        logger.warning("ingest.no_chunks", root=str(root))
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    # ---- 批量 Embedding（一次调用，而不是逐条）----
    vectors = await embedder.embed([c.full_text for c in chunks])
    if len(vectors) != len(chunks):
        logger.error("ingest.embed_mismatch", chunks=len(chunks), vectors=len(vectors))
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    records = [
        ArticleRecord(
            article_id=record_id(c),
            title=c.title,
            # 存 full_text 而不是纯正文：标题参与检索能显著提升召回
            content=c.full_text,
            vector=vec,
            source_path=c.source_path,
            published_at=c.published_at,
        )
        for c, vec in zip(chunks, vectors, strict=True)
    ]

    result.written = await store.upsert(records)

    if rebuild_bm25:
        hybrid = HybridRetriever(store=store, embedder=embedder)
        result.bm25_docs = await hybrid.build_bm25(await store.all_records())

    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "ingest.done",
        chunks=result.chunks,
        written=result.written,
        bm25=result.bm25_docs,
        backend=result.backend,
        embedder=result.embedder,
        elapsed_ms=result.elapsed_ms,
    )
    return result


def ingest_sync(root: str | Path | None = None, **kwargs: Any) -> IngestResult:
    """同步包装（CLI 用）。"""
    return asyncio.run(ingest_history(root, **kwargs))


def describe_pipeline() -> dict[str, str]:
    """给 CLI 展示整条管道（不执行）。"""
    from zhixun.knowledge.rag.vector_store import describe_vector_store
    from zhixun.knowledge.rag.embedders import describe_embedder
    from zhixun.config.settings import BACKEND_ROOT, settings

    emb = describe_embedder()
    vec = describe_vector_store()
    return {
        "历史文章目录": str(BACKEND_ROOT / settings.history_articles_dir),
        "切片策略": "按二级标题（##）切，<80 字的小节丢弃",
        "Embedding": f"{emb['provider']} / {emb['model']} / dim={emb['dim']}",
        "向量库": f"{vec['backend']} → {vec['effective']}",
        "关键词召回": "BM25（中文 bigram 分词，k1=1.5 b=0.75）",
        "融合": "RRF（k=60）",
        "披露档位": "summary(20/0) · standard(80/3) · full(500/5)",
    }