"""流水线与 API 的结构测试（不依赖 LLM、不依赖外部服务）。

第 5 篇：`run_weekly_report` 返回的已是 Agno 的 `WorkflowRunOutput`
而不是第 1 篇的自造 `WorkflowState`，所以这里的断言同步更新。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from zhixun.main import create_app
from zhixun.workflows import new_session_id, run_weekly_report
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
    """dry_run + skip_review 应一口气跑完并返回 Agno 的运行结果。"""
    output = await run_weekly_report(dry_run=True, skip_review=True)
    assert str(output.status).endswith("completed")
    assert output.run_id
    assert output.session_id


def test_new_session_id_unique() -> None:
    assert new_session_id() != new_session_id()
    assert new_session_id().startswith("wr-")


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


def test_workflow_run_endpoint_accepts_payload() -> None:
    """触发接口应接受 dry_run / issue_no 并立即返回 accepted。"""
    app = create_app()
    with TestClient(app) as client:
        resp = client.post("/api/v1/workflow/run", json={"dry_run": True, "issue_no": 7})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["dry_run"] is True
    assert body["issue_no"] == 7


def test_workflow_status_endpoint_never_crashes() -> None:
    """状态查询在没有待审批 run 时也要正常返回，而不是报错。"""
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/api/v1/workflow/status")
    assert resp.status_code == 200
    assert "runs" in resp.json()