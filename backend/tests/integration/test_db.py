"""集成测试：需要真实数据库（开发态用 SQLite 即可）。

运行：
    uv run pytest -m integration
"""

from __future__ import annotations

import pytest

from zhixun.db.session import dispose_db, get_session, init_db

pytestmark = pytest.mark.integration


async def test_init_db_creates_tables() -> None:
    await init_db()
    async with get_session() as session:
        # 能拿到会话即说明连接正常；第 4 篇会补真实读写断言
        assert session is not None
    await dispose_db()
