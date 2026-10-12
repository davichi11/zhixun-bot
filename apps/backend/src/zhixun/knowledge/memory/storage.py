"""业务记忆存储子层 —— 已发布项目、草稿、读者关注方向。

存储选型：开发态 SQLite（零运维）/ 生产态 Postgres（只改 `DATABASE_URL`）。

## 一个刻意的设计：去重查询返回"够用就好"的数据

`list_published()` 默认只取最近 `dedup_max_candidates`（500）条，而不是全表。
理由是**成本**：

- 去重要做标题 Embedding，500 条就是一次 500 × 1536 的向量计算
- 而你真正关心的是"最近半年写过什么"，更早的内容重复概率极低
- 全表扫描在项目跑了一年之后会变成性能黑洞

**不是所有"查全部"都是安全的默认。** 除非你能证明需要全量，
否则先给一个上限，并把上限做成配置。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings
from zhixun.db.session import session_scope
from zhixun.knowledge.unified_retriever import PublishedProject

logger = get_logger(__name__)


class MemoryStore:
    """业务记忆读写（已发布项目 / 关注方向 / 草稿索引）。"""

    def __init__(self, session_factory: Any | None = None) -> None:
        # session_factory 允许注入 —— 测试里塞一个内存 SQLite，生产走全局工厂
        self._session_factory = session_factory

    def _scope(self) -> Any:
        """带提交/回滚的会话作用域。

        ⚠️ 永远不要写 `async with self._factory() as session:` ——
        那样**不会提交**，会话关闭即回滚，数据静默丢失且不报错。
        """
        return session_scope(self._session_factory)

    async def list_published(self, limit: int | None = None) -> list[PublishedProject]:
        """列出历史已发布项目（供去重使用），按发布时间倒序。"""
        from zhixun.db.models import PublishedProject as PublishedProjectRow

        limit = limit or settings.dedup_max_candidates

        async with self._scope() as session:
            stmt = (
                select(PublishedProjectRow)
                .order_by(PublishedProjectRow.published_at.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()

        out = [
            PublishedProject(
                full_name=r.full_name,
                url=r.url,
                title=r.title,
                published_at=r.published_at.isoformat() if r.published_at else "",
                issue_no=r.issue_no,
            )
            for r in rows
        ]
        logger.debug("memory.list_published", count=len(out), limit=limit)
        return out

    async def list_focus_topics(self) -> list[str]:
        """读者/作者关注方向。

        它来自**配置**而不是数据库 —— 因为这是"当前这个账号想写什么"，
        属于运营策略而不是业务数据。放数据库里意味着每次改关注方向都要写工单。
        """
        return [t.strip() for t in settings.focus_topics if t.strip()]

    async def mark_published(
        self,
        *,
        full_name: str,
        url: str,
        title: str = "",
        issue_no: int | None = None,
        published_at: datetime | None = None,
    ) -> bool:
        """标记某项目已发布（去重表 upsert）。

        用"先查后插"而不是数据库的 upsert 语法，理由是**可移植**：
        SQLite 的 `ON CONFLICT` 和 Postgres 的写法有细微差别，
        而这一层的写入频率是"每周几十条"，完全不值得为它引入方言分支。

        Returns:
            True=新写入；False=已存在（重复写入被跳过）。
        """
        from zhixun.db.models import PublishedProject as PublishedProjectRow

        async with self._scope() as session:
            existing = (
                await session.execute(
                    select(PublishedProjectRow).where(PublishedProjectRow.url == url)
                )
            ).scalar_one_or_none()

            if existing is not None:
                logger.info("memory.mark_published_exists", full_name=full_name)
                return False

            session.add(
                PublishedProjectRow(
                    full_name=full_name,
                    url=url,
                    title=title,
                    issue_no=issue_no,
                    published_at=published_at or datetime.now(),
                )
            )
        logger.info("memory.mark_published", full_name=full_name, issue_no=issue_no)
        return True

    async def count_published(self) -> int:
        """已发布项目总数（给 CLI / 监控用）。"""
        from sqlalchemy import func

        from zhixun.db.models import PublishedProject as PublishedProjectRow

        async with self._scope() as session:
            total = (
                await session.execute(select(func.count()).select_from(PublishedProjectRow))
            ).scalar()
        return int(total or 0)

    async def health(self) -> bool:
        """存储健康检查：能不能真的查到一行。"""
        try:
            await self.list_published(limit=1)
            return True
        except Exception as exc:  # noqa: BLE001 - 健康检查不应该把异常抛给调用方
            logger.warning("memory.health_failed", error=str(exc))
            return False


def get_memory_store() -> MemoryStore:
    """工厂函数（第 4 篇装配真实 session_factory）。"""
    return MemoryStore()