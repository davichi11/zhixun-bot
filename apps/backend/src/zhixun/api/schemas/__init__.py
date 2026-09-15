"""API 请求/响应模型。

约定：**API 出参只暴露这里定义的 Schema，不要把 ORM 模型直接返回**。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """健康检查响应。"""

    status: str = "ok"
    app: str
    env: str
    version: str = "0.1.0"
    harness_enabled: bool = True


class RunRequest(BaseModel):
    """触发一次流水线。"""

    dry_run: bool = Field(default=True, description="干跑模式：走完全部步骤但不真正发布")
    issue_no: int | None = Field(default=None, description="期号，不填则自动递增")


class RunResponse(BaseModel):
    """流水线触发响应。"""

    run_id: str
    status: str
    dry_run: bool


class ProjectOut(BaseModel):
    """候选项目（选题面板用）。"""

    full_name: str
    url: str
    description: str = ""
    stars: int = 0
    score: float = 0.0
    reason: str = ""


class DraftOut(BaseModel):
    """稿件（草稿面板用）。"""

    id: int
    run_id: str
    platform: str
    title: str
    approved: bool
    created_at: datetime


class ReviewRequest(BaseModel):
    """人工审校提交。"""

    draft_ids: list[int]
    approve: bool
    comment: str = ""


class JobOut(BaseModel):
    """定时任务信息。"""

    id: str
    name: str
    cron: str
    enabled: bool
    next_run: datetime | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
