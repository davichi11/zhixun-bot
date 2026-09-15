"""选题 / 筛选相关接口（前端「选题面板」对接）。"""

from __future__ import annotations

from fastapi import APIRouter

from zhixun.api.deps import Retriever
from zhixun.api.schemas import ProjectOut

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut], summary="获取本期候选项目")
async def list_projects(retriever: Retriever) -> list[ProjectOut]:
    """列出候选项目（按评分倒序）。

    TODO(第 4 篇): 从数据库读取最近一次运行的 scored_items。
    """
    _ = retriever
    return []


@router.post("/collect", summary="手动触发一次采集")
async def trigger_collect() -> dict[str, str]:
    """手动触发采集（调试用，正常走定时调度）。

    TODO(第 3 篇): 触发采集并返回任务 id。
    """
    return {"status": "accepted", "message": "采集任务已提交（第 3 篇实现）"}
