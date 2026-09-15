"""业务记忆存储子层 —— 已发布项目、草稿、读者关注方向。

存储选型：
- 开发态：SQLite（零运维）
- 生产态：Postgres（并发与运维能力）

第 1 篇：定义接口。
第 4 篇：接 SQLAlchemy + Alembic 落地。
"""

from __future__ import annotations

from typing import Any

from zhixun.config.logging import get_logger

logger = get_logger(__name__)


class MemoryStore:
    """业务记忆读写（已发布项目 / 关注方向 / 草稿索引）。"""

    def __init__(self, session_factory: Any | None = None) -> None:
        self._session_factory = session_factory

    async def list_published(self, limit: int = 500) -> list[Any]:
        """列出历史已发布项目（供去重使用）。"""
        # TODO(第 4 篇): 查询 published_projects 表
        logger.debug("memory.list_published", limit=limit)
        return []

    async def list_focus_topics(self) -> list[str]:
        """列出读者/作者关注方向，用于相关度打分。"""
        # TODO(第 4 篇): 从配置表或知识库读取
        return []

    async def mark_published(self, project: Any) -> None:
        """标记某项目已发布（去重表写入）。"""
        # TODO(第 4 篇): upsert published_projects
        logger.info("memory.mark_published", project=str(project))

    async def health(self) -> bool:
        """存储健康检查。"""
        return self._session_factory is not None
