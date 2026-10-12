"""异步数据库会话（SQLAlchemy 2.0 async）。

用法：
    from zhixun.db.session import get_session, init_db

    async with get_session() as session:
        ...
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings
from zhixun.db.models import Base

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """获取全局异步引擎（惰性创建）。"""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            future=True,
            pool_pre_ping=True,
        )
        logger.info("db.engine_created", url=settings.database_url.split("@")[-1])
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncIterator[AsyncSession]:
    """带提交/回滚的会话作用域，可注入自定义 factory。

    这是**唯一正确获取会话的入口**。直接 `async with factory() as session:`
    不会提交任何东西 —— 会话关闭即回滚，数据静默丢失，
    而且不报任何错（这是最坑的一类 bug）。

    Args:
        factory: 可选的 session factory；为 None 时用全局工厂
    """
    active = factory or get_session_factory()
    async with active() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """获取一个自动提交/回滚的会话（全局工厂）。"""
    async with session_scope() as session:
        yield session


async def init_db() -> None:
    """建表（开发期使用；生产期请用 Alembic 迁移）。"""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("db.initialized")


async def dispose_db() -> None:
    """释放连接（应用关闭时调用）。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


__all__ = [
    "dispose_db",
    "get_engine",
    "get_session",
    "get_session_factory",
    "init_db",
    "session_scope",
]
