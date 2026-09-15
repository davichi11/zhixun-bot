"""流水线触发与状态查询接口。"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks

from zhixun.api.schemas import RunRequest, RunResponse
from zhixun.config.logging import get_logger
from zhixun.workflows import new_state, run_weekly_report

logger = get_logger(__name__)

router = APIRouter(prefix="/workflow", tags=["workflow"])


async def _execute(run_id: str, dry_run: bool) -> None:
    """后台执行流水线（失败只记日志，不阻塞 HTTP 响应）。"""
    try:
        state = await run_weekly_report(dry_run=dry_run)
        logger.info("workflow.background_done", run_id=state.run_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("workflow.background_failed", run_id=run_id, error=str(exc))


@router.post("/run", response_model=RunResponse, summary="触发一次周报流水线")
async def trigger_run(payload: RunRequest, background: BackgroundTasks) -> RunResponse:
    """触发流水线（后台异步执行，立即返回 run_id）。"""
    state = new_state(dry_run=payload.dry_run, issue_no=payload.issue_no)
    background.add_task(_execute, state.run_id, payload.dry_run)
    logger.info("workflow.triggered", run_id=state.run_id, dry_run=payload.dry_run)
    return RunResponse(
        run_id=state.run_id,
        status="accepted",
        dry_run=payload.dry_run,
    )


@router.get("/{run_id}", summary="查询流水线状态")
async def get_run_status(run_id: str) -> dict[str, object]:
    """查询某次运行的状态。

    TODO(第 5 篇): 从 workflow_runs 表读取真实状态与步骤进度。
    """
    return {"run_id": run_id, "status": "unknown", "steps": []}
