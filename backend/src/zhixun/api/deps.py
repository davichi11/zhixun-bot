"""FastAPI 依赖注入。

约定：需要数据库/知识层的路由，一律通过这里的 Depends 获取，
不要在路由函数里直接 import 全局单例（方便测试覆盖）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from zhixun.db.session import get_session
from zhixun.knowledge import UnifiedRetriever, get_retriever


async def db_session() -> AsyncIterator[AsyncSession]:
    """数据库会话依赖。"""
    async with get_session() as session:
        yield session


def retriever() -> UnifiedRetriever:
    """知识层依赖。"""
    return get_retriever()


DbSession = Annotated[AsyncSession, Depends(db_session)]
Retriever = Annotated[UnifiedRetriever, Depends(retriever)]
