"""端到端测试：需要真实 LLM Key，默认跳过。

运行：
    RUN_E2E=1 uv run pytest -m e2e
"""

from __future__ import annotations

import os

import pytest

from zhixun.workflows import run_weekly_report

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.getenv("RUN_E2E"),
        reason="需要真实 LLM，设置 RUN_E2E=1 后运行",
    ),
]


async def test_full_pipeline_dry_run() -> None:
    """完整跑一次周报流水线（不发布）。"""
    state = await run_weekly_report(dry_run=True)
    assert state.run_id
