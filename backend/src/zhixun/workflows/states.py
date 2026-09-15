"""流水线状态定义 —— 步骤之间传递的数据契约。

原则：**步骤之间只传数据，不传状态对象**。
每个 Step 的输入输出都是这里的 Pydantic 模型，
这样每一步都可以单独测试、单独重放，也为 Harness 的 checkpoint 打好基础（第 7 篇）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Platform = Literal["wechat", "zhihu", "twitter"]


class RawItem(BaseModel):
    """采集步骤的输出：一条原始素材。"""

    full_name: str
    url: str
    description: str = ""
    stars: int = 0
    language: str | None = None
    readme_excerpt: str = ""


class ScoredItem(BaseModel):
    """筛选步骤的输出：带评分与判定的一条候选。"""

    item: RawItem
    score: float = Field(ge=0, le=10)
    novelty: float = Field(default=0, ge=0, le=10)
    relevance: float = Field(default=0, ge=0, le=10)
    momentum: float = Field(default=0, ge=0, le=10)
    reason: str = ""
    is_duplicate: bool = False


class Summary(BaseModel):
    """摘要步骤的输出。"""

    full_name: str
    highlights: list[str] = Field(default_factory=list, description="2-3 条技术亮点")
    positioning: str = Field(default="", description="一句话定位")


class Draft(BaseModel):
    """改写步骤的输出：某个平台的稿件。"""

    platform: Platform
    title: str
    content: str
    word_count: int = 0


class ReviewOutcome(BaseModel):
    """审校步骤的输出。"""

    passed: bool
    need_human: bool = False
    issues: list[str] = Field(default_factory=list)
    final_drafts: list[Draft] = Field(default_factory=list)


class WorkflowState(BaseModel):
    """整条流水线的聚合状态（用于持久化与断点恢复）。"""

    run_id: str
    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: datetime | None = None
    issue_no: int | None = Field(default=None, description="第几期周报")
    dry_run: bool = False

    raw_items: list[RawItem] = Field(default_factory=list)
    scored_items: list[ScoredItem] = Field(default_factory=list)
    summaries: list[Summary] = Field(default_factory=list)
    drafts: list[Draft] = Field(default_factory=list)
    review: ReviewOutcome | None = None
