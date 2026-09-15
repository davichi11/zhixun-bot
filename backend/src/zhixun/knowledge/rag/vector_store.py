"""LanceDB 客户端封装。

选型理由：嵌入式、零运维、Python 原生，适合单机部署的本项目；
未来要上云可平滑切到 PgVector（接口不变）。

第 1 篇：定义接口。
第 4 篇：落地建表、写入、检索。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings

logger = get_logger(__name__)


@dataclass(slots=True)
class ArticleRecord:
    """历史文章向量记录。"""

    article_id: str
    title: str
    content: str
    vector: list[float]


class VectorStore:
    """LanceDB 薄封装。"""

    def __init__(self, uri: str | None = None, table: str | None = None) -> None:
        self.uri = uri or settings.vector_db_uri
        self.table_name = table or settings.vector_table_articles
        self._db: Any | None = None

    @property
    def db(self) -> Any:
        """惰性连接（避免 import 时就建库）。"""
        if self._db is None:
            import lancedb

            self._db = lancedb.connect(self.uri)
            logger.info("vector_store.connected", uri=self.uri, table=self.table_name)
        return self._db

    async def upsert(self, records: list[ArticleRecord]) -> int:
        """写入/更新文章向量。"""
        # TODO(第 4 篇): create_table / merge_insert
        logger.info("vector_store.upsert", count=len(records))
        return len(records)

    async def search(self, vector: list[float], limit: int = 5) -> list[dict[str, Any]]:
        """向量近邻检索。"""
        # TODO(第 4 篇): self.db.open_table(...).search(vector).limit(limit)
        logger.debug("vector_store.search", limit=limit)
        return []
