"""草稿 / 审校相关接口（前端「草稿面板」与「审校面板」对接）。"""

from __future__ import annotations

from fastapi import APIRouter

from zhixun.api.deps import DbSession
from zhixun.api.schemas import DraftOut, ReviewRequest

router = APIRouter(prefix="/drafts", tags=["drafts"])


@router.get("", response_model=list[DraftOut], summary="稿件列表")
async def list_drafts(session: DbSession, run_id: str | None = None) -> list[DraftOut]:
    """列出稿件，可按 run_id 过滤。

    TODO(第 5 篇): 查询 drafts 表。
    """
    _ = (session, run_id)
    return []


@router.post("/review", summary="提交人工审校结果（HITL 放行）")
async def submit_review(payload: ReviewRequest, session: DbSession) -> dict[str, object]:
    """人工审校回执 —— 决定稿件是否放行进入发布。

    这是 Workflow 中「等待人工」节点的唤醒入口（第 5 篇展开）。

    TODO(第 5 篇): 写审批状态 + 唤醒挂起的 Workflow。
    """
    _ = session
    return {"ok": True, "approved": payload.approve, "count": len(payload.draft_ids)}
