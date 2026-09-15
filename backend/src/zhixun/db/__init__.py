"""数据访问层 —— 只被 knowledge（memory 子层）与 api 依赖（见第一篇 4.2 节 ⑨）。

业务模块**不要直接碰数据库**，一律通过 knowledge 层暴露的接口。
这样将来换库（SQLite → Postgres → 分布式）时，改动被限制在本层。
"""

from __future__ import annotations

from zhixun.db.models import Base, DraftRecord, PublishedProject, WorkflowRun
from zhixun.db.session import dispose_db, get_engine, get_session, get_session_factory, init_db

__all__ = [
    "Base",
    "DraftRecord",
    "PublishedProject",
    "WorkflowRun",
    "dispose_db",
    "get_engine",
    "get_session",
    "get_session_factory",
    "init_db",
]
