"""流水线触发、状态查询与人工审批接口（第 5 篇）。

第 1 篇时这里返回的是一个自造的 `WorkflowState`；
第 5 篇起改为**透传 Agno 的 `WorkflowRunOutput`**，
因为 HITL 挂起状态存在 Agno 的 db 里，自造状态会和真实进度脱节。
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from zhixun.api.schemas import RunRequest, RunResponse, RunStatusResponse, StepProgress
from zhixun.config.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/workflow", tags=["workflow"])


def _status_str(output: object) -> str:
    """把 RunStatus 枚举转成小写字符串。"""
    return str(getattr(output, "status", "unknown")).split(".")[-1].lower()


async def _execute(dry_run: bool, issue_no: int | None) -> None:
    """后台执行流水线（失败只记日志，不阻塞 HTTP 响应）。"""
    from zhixun.workflows import run_weekly_report

    try:
        output = await run_weekly_report(dry_run=dry_run, issue_no=issue_no)
        logger.info(
            "workflow.background_done",
            run_id=getattr(output, "run_id", "?"),
            status=_status_str(output),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("workflow.background_failed", error=str(exc))


@router.post("/run", response_model=RunResponse, summary="触发一次周报流水线")
async def trigger_run(payload: RunRequest, background: BackgroundTasks) -> RunResponse:
    """触发流水线（后台异步执行，立即返回）。

    ⚠️ 注意：**返回的 `run_id` 是入口层的占位值**，真正的 run_id 由
    Agno 在后台创建。查询进度请用 `GET /workflow/status`（列出待审批的 run），
    而不是拿着这个 id 去查 —— 这是第 5 篇 API 层遗留的接口债，第 9 篇统一收拾。
    """
    run_id = f"pending-{id(payload):x}"
    background.add_task(_execute, payload.dry_run, payload.issue_no)
    logger.info("workflow.triggered", dry_run=payload.dry_run, issue_no=payload.issue_no)
    return RunResponse(
        run_id=run_id,
        status="accepted",
        dry_run=payload.dry_run,
        issue_no=payload.issue_no,
    )


@router.get("/status", response_model=RunStatusResponse, summary="查看待审批的流水线")
async def list_pending() -> RunStatusResponse:
    """列出当前等待人工确认的流水线（前端审校面板的数据源）。

    有了这个接口，前端就不需要自己记 run_id —— 后端去 Agno db 里查。
    """
    from zhixun.workflows import find_latest_pending_session, pending_approvals
    from zhixun.workflows.weekly_report import build_weekly_report_workflow, get_workflow_db

    db = get_workflow_db()
    if db is None:
        return RunStatusResponse(runs=[], message="工作流数据库不可用")

    workflow = build_weekly_report_workflow(db=db)
    session_id = await find_latest_pending_session()
    if session_id is None:
        return RunStatusResponse(runs=[], message="当前没有待审批的流水线")

    steps: list[StepProgress] = []
    try:
        output = await workflow.aget_session_run_outputs(session_id=session_id)
        for out in output or []:
            for s in getattr(out, "step_results", None) or []:
                steps.append(
                    StepProgress(
                        name=str(s.step_name),
                        success=bool(s.success),
                        paused=bool(s.is_paused),
                        content=str(s.content or "")[:200],
                    )
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("workflow.load_steps_failed", error=str(exc))

    return RunStatusResponse(
        runs=[{"session_id": session_id}],
        steps=steps,
        message=f"会话 {session_id} 等待人工确认",
    )


@router.post("/{run_id}/approve", summary="人工通过，恢复流水线")
async def approve_run(run_id: str, feedback: str = "") -> dict[str, str]:
    """人工点"通过"。

    ⚠️ `run_id` 形如 `<session_id>::<run_id>` 或直接传 session_id ——
    因为 Agno 的 `aget_run_output` **必须同时给 run_id 和 session_id**。
    第 9 篇会把这段参数解析收敛到统一的 `parse_run_ref()`。
    """
    from zhixun.workflows import approve
    from zhixun.workflows.weekly_report import build_weekly_report_workflow, get_workflow_db

    session_id, rid = _parse_run_ref(run_id)
    db = get_workflow_db()
    if db is None:
        raise HTTPException(status_code=503, detail="工作流数据库不可用")

    workflow = build_weekly_report_workflow(db=db)
    output = await workflow.aget_run_output(rid, session_id=session_id)
    if output is None:
        raise HTTPException(status_code=404, detail=f"找不到 run：{run_id}")

    output = await approve(output, workflow=workflow)
    return {"run_id": run_id, "status": _status_str(output)}


@router.post("/{run_id}/reject", summary="人工驳回，取消发布")
async def reject_run(run_id: str, feedback: str = "") -> dict[str, str]:
    """人工点"驳回"。默认 `on_reject="cancel"`，发布步骤不会执行。"""
    from zhixun.workflows import reject
    from zhixun.workflows.weekly_report import build_weekly_report_workflow, get_workflow_db

    session_id, rid = _parse_run_ref(run_id)
    db = get_workflow_db()
    if db is None:
        raise HTTPException(status_code=503, detail="工作流数据库不可用")

    workflow = build_weekly_report_workflow(db=db)
    output = await workflow.aget_run_output(rid, session_id=session_id)
    if output is None:
        raise HTTPException(status_code=404, detail=f"找不到 run：{run_id}")

    output = await reject(output, feedback=feedback or "内容需要修改", workflow=workflow)
    return {"run_id": run_id, "status": _status_str(output)}


def _parse_run_ref(run_ref: str) -> tuple[str, str]:
    """把 `session_id::run_id` 或单个 session_id 解析成 (session_id, run_id)。

    run_id 留空时返回空串 —— 调用方应改用 `list_pending` 拿准确的 run_id。
    """
    if "::" in run_ref:
        session_id, _, rid = run_ref.partition("::")
        return session_id, rid
    return run_ref, ""