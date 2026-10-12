"""向量库 —— 一个接口，两个实现（内存 / LanceDB）。

## 为什么要做这个降级？

第三篇我们立了一条规矩：**能自动降级的不要让服务起不来**。
这一篇是那条规矩的第一次实战 —— `lancedb` 是一个**可选的重量级依赖**
（几十 MB，含 Arrow / Rust 扩展），而本项目的开发态完全可以不用它。

所以这里有两个实现：

| 实现 | 何时使用 | 适用规模 |
|---|---|---|
| `InMemoryVectorStore` | 没装 `lancedb`（默认） | 几百篇 —— 线性扫描，毫秒级 |
| `LanceVectorStore` | 装了 `lancedb` | 万篇以上 |

关键在于：**两者的 `upsert` / `search` 签名完全一致**，
所以检索器（`rag/retriever.py`）完全不需要知道自己跑在哪个上面。

> 顺带一提：内存实现用**线性扫描**而不是建 HNSW 索引。
> 因为在几千条以内，线性扫描的常数小得足以吊打"建索引 + 维护索引"。
> 优化要有数据支撑，不能靠直觉 —— 我们会在第 8 篇用真实数据验证这个判断。

## 线性扫描为什么没想象中慢

1000 篇 × 1536 维 = 153 万次乘加，纯 Python 大约 0.1~0.3 秒。
而一次 RAG 检索本来就要调一次 LLM（几秒），这点开销完全被淹没了。

**真正的性能问题从来不是"算法不够聪明"，而是"你在优化不存在的问题"。**
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings
from zhixun.knowledge.rag.embedders import cosine_similarity

logger = get_logger(__name__)

__all__ = [
    "ArticleRecord",
    "InMemoryVectorStore",
    "LanceVectorStore",
    "VectorStore",
    "get_vector_store",
    "reset_vector_store",
]


@dataclass(slots=True)
class ArticleRecord:
    """历史文章向量记录。"""

    article_id: str
    title: str
    content: str
    vector: list[float]
    source_path: str = ""
    published_at: str = ""


@runtime_checkable
class VectorStore(Protocol):
    """向量库协议 —— 检索器只依赖这个，不依赖具体实现。"""

    backend: str

    async def upsert(self, records: list[ArticleRecord]) -> int: ...

    async def search(self, vector: list[float], limit: int = 5) -> list[dict[str, Any]]: ...

    async def get(self, article_id: str) -> ArticleRecord | None: ...

    async def all_records(self) -> list[ArticleRecord]: ...


# ------------------------------------------------------------------ 内存实现


class InMemoryVectorStore:
    """纯内存向量库 —— 零依赖、零运维，线性扫描。"""

    backend = "memory"

    def __init__(self) -> None:
        self._records: dict[str, ArticleRecord] = {}

    async def upsert(self, records: list[ArticleRecord]) -> int:
        for rec in records:
            self._records[rec.article_id] = rec
        logger.info("vector_store.upsert", backend=self.backend, count=len(records))
        return len(records)

    async def search(self, vector: list[float], limit: int = 5) -> list[dict[str, Any]]:
        scored = [
            {
                "article_id": rec.article_id,
                "title": rec.title,
                "content": rec.content,
                "distance": 1.0 - cosine_similarity(vector, rec.vector),  # 转成"距离"语义
            }
            for rec in self._records.values()
        ]
        scored.sort(key=lambda row: row["distance"])
        return scored[:limit]

    async def get(self, article_id: str) -> ArticleRecord | None:
        return self._records.get(article_id)

    async def all_records(self) -> list[ArticleRecord]:
        return list(self._records.values())

    async def clear(self) -> None:
        self._records.clear()


# ------------------------------------------------------------------ LanceDB 实现


class LanceVectorStore:
    """LanceDB 实现（延迟 import，缺依赖时不会让 import 失败）。"""

    backend = "lancedb"

    def __init__(self, uri: str | None = None, table: str | None = None) -> None:
        self.uri = uri or settings.vector_db_uri
        self.table_name = table or settings.vector_table_articles
        self._db: Any | None = None
        self._cache: dict[str, ArticleRecord] = {}  # BM25 那路要用全文

    @property
    def db(self) -> Any:
        if self._db is None:
            import lancedb

            self._db = lancedb.connect(self.uri)
            logger.info("vector_store.connected", backend=self.backend, uri=self.uri)
        return self._db

    def _table(self) -> Any | None:
        try:
            names = self.db.table_names()
        except Exception:  # noqa: BLE001 - 首次连接时表还不存在
            return None
        return self.db.open_table(self.table_name) if self.table_name in names else None

    async def upsert(self, records: list[ArticleRecord]) -> int:
        if not records:
            return 0

        rows = [
            {
                "article_id": r.article_id,
                "title": r.title,
                "content": r.content,
                "source_path": r.source_path,
                "published_at": r.published_at,
                "vector": r.vector,
            }
            for r in records
        ]
        table = self._table()
        if table is None:
            self.db.create_table(self.table_name, data=rows)
        else:
            ids = ", ".join(f"'{r.article_id}'" for r in records)
            table.delete(f"article_id IN ({ids})")
            table.add(rows)

        for r in records:
            self._cache[r.article_id] = r
        logger.info("vector_store.upsert", backend=self.backend, count=len(records))
        return len(records)

    async def search(self, vector: list[float], limit: int = 5) -> list[dict[str, Any]]:
        table = self._table()
        if table is None:
            return []
        rows = table.search(vector).limit(limit).to_list()
        return [
            {
                "article_id": row["article_id"],
                "title": row["title"],
                "content": row["content"],
                "distance": float(row.get("_distance", 1.0)),
            }
            for row in rows
        ]

    async def get(self, article_id: str) -> ArticleRecord | None:
        if article_id in self._cache:
            return self._cache[article_id]
        table = self._table()
        if table is None:
            return None
        rows = table.search().where(f"article_id = '{article_id}'").limit(1).to_list()
        if not rows:
            return None
        row = rows[0]
        return ArticleRecord(
            article_id=row["article_id"],
            title=row["title"],
            content=row["content"],
            vector=list(row.get("vector", [])),
            source_path=row.get("source_path", ""),
            published_at=row.get("published_at", ""),
        )

    async def all_records(self) -> list[ArticleRecord]:
        """全量导出（BM25 建索引需要全文）。"""
        if self._cache:
            return list(self._cache.values())
        table = self._table()
        if table is None:
            return []
        rows = table.search().limit(100_000).to_list()
        out = [
            ArticleRecord(
                article_id=row["article_id"],
                title=row["title"],
                content=row["content"],
                vector=list(row.get("vector", [])),
                source_path=row.get("source_path", ""),
                published_at=row.get("published_at", ""),
            )
            for row in rows
        ]
        for rec in out:
            self._cache[rec.article_id] = rec
        return out


# ------------------------------------------------------------------ 工厂

_store_singleton: VectorStore | None = None


def get_vector_store(backend: str | None = None) -> VectorStore:
    """按配置返回向量库实现，缺依赖自动降级到内存实现。

    ⚠️ 进程内单例。内存后端如果每次都 new 一个，
    就会出现"刚入库的数据检索不到"这种诡异 bug（两个实例不是同一份数据）。
    LanceDB 后端本身是文件持久化的，单例只是省掉重复连接。
    """
    global _store_singleton
    if _store_singleton is not None and (backend is None or _store_singleton.backend == backend):
        return _store_singleton

    backend = (backend or settings.vector_backend).lower()
    store: VectorStore

    if backend == "lancedb":
        try:
            import lancedb  # noqa: F401

            store = LanceVectorStore()
        except ImportError:
            logger.warning("vector_store.lancedb_missing_fallback_memory", hint="pip install lancedb")
            store = InMemoryVectorStore()
    else:
        store = InMemoryVectorStore()

    _store_singleton = store
    return store


def reset_vector_store() -> None:
    """清空单例（测试与配置热更新时用）。"""
    global _store_singleton
    _store_singleton = None


def describe_vector_store() -> dict[str, str]:
    """给 CLI 展示用（不连接、不建表）。"""
    from zhixun.config.settings import settings

    store = get_vector_store()
    return {
        "backend": settings.vector_backend,
        "effective": store.backend,
        "uri": settings.vector_db_uri if store.backend == "lancedb" else "(内存)",
        "table": settings.vector_table_articles if store.backend == "lancedb" else "-",
    }