"""流水线与 API 的结构测试（不依赖 LLM、不依赖外部服务）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from zhixun.main import create_app
from zhixun.workflows import new_state, run_weekly_report
from zhixun.workflows.steps import ALL_STEPS

pytestmark = pytest.mark.unit


def test_workflow_has_six_steps() -> None:
    assert len(ALL_STEPS) == 6
    names = [fn.__name__ for fn in ALL_STEPS]
    assert names == [
        "step_collect",
        "step_filter",
        "step_summarize",
        "step_rewrite",
        "step_review",
        "step_publish",
    ]


async def test_run_weekly_report_dry_run() -> None:
    """第 1 篇各步骤为空实现，干跑应能正常走完并返回状态。"""
    state = await run_weekly_report(dry_run=True)
    assert state.run_id
    assert state.dry_run is True


def test_new_state_unique_run_id() -> None:
    assert new_state().run_id != new_state().run_id


def test_health_endpoint() -> None:
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] == "智讯助手"


def test_scheduler_jobs_endpoint() -> None:
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/api/v1/scheduler/jobs")
    assert resp.status_code == 200
    jobs = resp.json()
    assert jobs[0]["id"] == "weekly-report"
