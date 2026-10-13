"""周报主流程 —— 全项目的业务主干。

架构决策（见第一篇 4.2 / ADR-002 / 第 5 篇）：
**Workflow 主导 + Team 局部嵌套**。

- 主干用 Workflow：确定性、可审计、可断点恢复
- 只有"改写"这一步内部嵌套 Team（三平台并行）

流程：

    ① 采集 → ② 筛选 → ┬→ ③ 摘要 → ④ 改写(内嵌 Team) → ⑤ 审校 ⏸ → ⑥ 发布
                      └────────────── 候选不足时走 else 分支（提前结束）

第 5 篇用 Agno 3.1.2 的 Workflow 替换了第 1 篇的手写 for 循环，
换来三件手写拿不到的东西：**条件分支、并行执行、HITL 挂起/恢复**。

---

## 为什么 Workflow 主导而不是 Team 主导

内容生产是**确定性流水线**：采集→筛选→摘要→改写→审校→发布，步骤与依赖关系固定。
生产环境要求可审计、可回放、可失败重试 —— 这些是 Workflow 的能力。
Team 的自主调度不可复现：同一份输入两次运行结果可能不同，无法做回归测试。

**Team 的唯一用武之地是第 ④ 步内部**：三个平台写手并行 + 共享同一份候选清单，
需要成员间共享会话上下文。这种场景用三个孤立 Step 并行反而会出现口径不一致。
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from agno.workflow import Condition, HumanReview, Step, StepInput, StepOutput, Workflow
from agno.workflow.types import StepRequirement

from zhixun.config.logging import get_logger
from zhixun.config.settings import BACKEND_ROOT, settings
from zhixun.workflows.steps import (
    K_DRY_RUN,
    K_ISSUE,
    STEP_LABELS,
    step_collect,
    step_filter,
    step_publish,
    step_review,
    step_rewrite,
    step_summarize,
)

logger = get_logger(__name__)

# 至少要这么多候选才值得写一期 —— 少于这个数，本期不发。
# 从配置读，方便运营随时调整"这周素材不够就不发"这条业务规则。
MIN_CANDIDATES = settings.min_candidates


# ------------------------------------------------------------------ 条件判断

# 筛选步骤在 StepOutput.content 里留下的机器可读标记
# 形如 "去重剔除 2 条，筛选出 5 条候选"
_COUNT_RE = re.compile(r"筛选出\s*(\d+)\s*条")


def has_enough_candidates(step_input: StepInput) -> bool:
    """条件：筛选后候选数是否达标。

    ⚠️ **实测坑（Agno 3.1.2）**：`Condition.evaluator` 收到的
    `StepInput.workflow_session` 是 **`None`**，不是 session 对象。
    所以条件判断里**读不到 session_state**。

    可用的通道有两个：
    - `previous_step_content`：上一步的输出字符串（本实现用它，格式固定）
    - `previous_step_outputs`：上一步的 `StepOutput` 字典（更稳，但需按名取值）

    本项目选择"content 里带可解析的数字"，因为它同时喂给人和喂给框架 ——
    出了错，你在日志里一眼就能看出上一步说了什么。
    """
    content = str(step_input.previous_step_content or "")
    m = _COUNT_RE.search(content)
    count = int(m.group(1)) if m else 0
    logger.info("workflow.branch", count=count, threshold=MIN_CANDIDATES, content=content[:60])
    return count >= MIN_CANDIDATES


async def step_abort_insufficient(step_input: StepInput) -> StepOutput:
    """候选不足时的收尾：不产出空稿，明确告诉下游"这期不发了"。

    ⚠️ 这里 `workflow_session` 是可用的（不在 `evaluator` 里），
    所以能正常清理状态 —— 上一版的清理逻辑就依赖这一点。
    """
    from zhixun.workflows.steps import K_SCORED, get_state, put_state

    state = get_state(step_input)
    state[K_SCORED] = []          # 清掉，避免下次误读
    put_state(step_input, state)

    logger.info("workflow.abort", reason=f"候选不足 {MIN_CANDIDATES} 条，本期不发")
    return StepOutput(content="候选不足，本期不产出稿件（这本身就是有价值的信号）")


# ------------------------------------------------------------------ 构建


def build_weekly_report_workflow(*, db: Any | None = None) -> Workflow:
    """构建周报 Workflow。

    ## 一个必须知道的 3.1.2 行为（实测）

    **`HumanReview` 写在 `Condition` 内部的 Step 上不会生效。**

    实测对照（同一份代码，只改嵌套位置）：

    ```
    Step(name="审校", human_review=...)                      → status=paused   pending=1
    Condition(steps=[Step(..., human_review=...)])           → status=completed pending=0
    ```

    所以本流程刻意把结构拆成"条件在前、HITL 在后"：

    ```
    ① 采集 → ② 筛选 → [Condition: 够不够写 → ③ 摘要 + ④ 改写 / else 收尾]
                        → ⑤ 审校（HumanReview，顶层）→ ⑥ 发布
    ```

    这样条件分支与人工审批**都真正生效**，而不是"看起来有、实际不挂起"。
    如果当初没做这个对照实验，这篇流水线会"永远自动发布"——
    而且不报任何错。

    Args:
        db: Agno 的数据库连接。**HITL 挂起与恢复依赖它** ——
            没有 db，暂停的 run 无处存放，恢复时读不回来。
    """
    review_step = Step(
        name=STEP_LABELS[step_review.__name__],
        executor=step_review,
        # ---- HITL：框架在这里挂起，等人工点"通过"（必须是顶层 Step）----
        human_review=HumanReview(
            requires_confirmation=True,
            confirmation_message="稿件已完成审校，是否发布？",
            # ⚠️ 必须用 `cancel`，不能用 `skip`。实测（Agno 3.1.2）：
            #   on_reject="skip"   → 驳回后 status=completed，**发布步骤照样执行**
            #   on_reject="cancel" → 驳回后 status=cancelled，发布不再执行
            # `skip` 的语义是"跳过这个步骤，继续往下走"，
            # 对一个紧挨着发布工具的审校节点来说，那是致命的默认值。
            on_reject="cancel",
        ),
    )

    steps: list[Any] = [
        Step(name=STEP_LABELS[step_collect.__name__], executor=step_collect),
        Step(name=STEP_LABELS[step_filter.__name__], executor=step_filter),
        # ---- 条件分支：候选够才进入写作 ----
        Condition(
            name="候选是否够写",
            description=f"筛选后至少 {MIN_CANDIDATES} 条候选才进入写作，否则本期不发",
            steps=[
                Step(name=STEP_LABELS[step_summarize.__name__], executor=step_summarize),
                Step(name=STEP_LABELS[step_rewrite.__name__], executor=step_rewrite),
            ],
            evaluator=has_enough_candidates,
            else_steps=[step_abort_insufficient],
        ),
        # ---- 人工审校与发布：必须在顶层，HumanReview 才生效 ----
        review_step,
        Step(name=STEP_LABELS[step_publish.__name__], executor=step_publish),
    ]

    workflow = Workflow(
        name="weekly-report",
        description="智讯助手周报流水线：采集 → 筛选 → 摘要 → 改写 → 审校 → 发布",
        db=db,
        steps=steps,
        # 让每个 Agent 都能看到本轮的状态（采集员要知道别重复、写手要知道候选清单）
        add_session_state_to_context=True,
        store_executor_outputs=True,
    )
    logger.info("workflow.built", steps=len(steps), has_db=db is not None)
    return workflow


def new_session_id() -> str:
    """生成会话 ID（一次流水线 = 一个 session）。"""
    return f"wr-{uuid.uuid4().hex[:12]}"


def get_workflow_db() -> Any | None:
    """取 Agno 的数据库连接（SQLite / Postgres）。

    **开发态也必须有 db** —— 因为 HITL 的暂停状态存在这里。
    没有它，`HumanReview` 挂起后流程就卡死无法恢复。
    """
    try:
        from agno.db.sqlite import SqliteDb

        return SqliteDb(db_file=str(BACKEND_ROOT / settings.workflow_db))
    except Exception as exc:  # noqa: BLE001 - 拿不到 db 时降级为无状态模式
        logger.warning("workflow.db_unavailable", error=str(exc))
        return None


# ------------------------------------------------------------------ 运行


async def run_weekly_report(
    *,
    dry_run: bool = False,
    issue_no: int | None = None,
    session_id: str | None = None,
    skip_review: bool = False,
) -> Any:
    """跑一次周报流水线。

    Args:
        dry_run: 干跑 —— 走完全部步骤但不调 LLM、不真正发布（CI 与本地调试用）
        issue_no: 第几期周报
        session_id: 指定会话（不传则新建）
        skip_review: 跳过人工审校环节（**只能配 dry_run 使用**，用于本地全链路验证）

    Returns:
        `WorkflowRunOutput`。若在审校处挂起，`status` 为 `paused`
        且 `step_requirements` 里有人工待办项。
    """
    sid = session_id or new_session_id()
    db = get_workflow_db()
    workflow = build_weekly_report_workflow(db=db)

    if skip_review:
        # 本地全链路验证：把审校步骤摘掉，免得每次都要手动点确认
        _strip_review(workflow)

    initial_state: dict[str, Any] = {K_DRY_RUN: dry_run}
    if issue_no is not None:
        initial_state[K_ISSUE] = issue_no

    logger.info(
        "workflow.start", session_id=sid, dry_run=dry_run, issue_no=issue_no, skip_review=skip_review
    )
    output = await workflow.arun(
        input=f"生成第 {issue_no or '本期'} 期 AI 周报",
        session_id=sid,
        session_state=initial_state,
    )
    logger.info(
        "workflow.done",
        session_id=sid,
        status=str(getattr(output, "status", "?")),
        pending=len(getattr(output, "step_requirements", None) or []),
    )
    return output


def _strip_review(workflow: Workflow) -> None:
    """移除带 HumanReview 的审校步骤（仅本地全链路验证用）。

    因为审校步骤被提到了顶层（见 `build_weekly_report_workflow` 的说明），
    这里直接在顶层过滤即可。
    """
    before = len(workflow.steps)
    workflow.steps = [
        s for s in workflow.steps
        if not (
            getattr(getattr(s, "human_review", None), "requires_confirmation", False)
        )
    ]
    logger.info("workflow.review_stripped", before=before, after=len(workflow.steps))


# ------------------------------------------------------------------ 人工审批


def pending_approvals(output: Any) -> list[StepRequirement]:
    """取出待人工确认的条目。"""
    return list(getattr(output, "step_requirements", None) or [])


def describe_pending(output: Any) -> str:
    """把待办渲染成人能读的文字（CLI 与前端共用）。"""
    reqs = pending_approvals(output)
    if not reqs:
        return "当前没有待人工确认的步骤"
    lines = [f"本轮有 {len(reqs)} 个步骤等待人工确认："]
    for r in reqs:
        lines.append(f"  - [{r.step_name}] {r.confirmation_message or '请确认'}")
    return "\n".join(lines)


async def approve(
    output: Any,
    *,
    workflow: Workflow | None = None,
    approve_all: bool = True,
) -> Any:
    """人工点"通过"，恢复被挂起的流程。

    ⚠️ **最容易写错的一步**：恢复不是传 `confirmed=True`，
    而是构造 `StepRequirement` 对象传给 `continue_run(step_requirements=[...])`。
    传错会报 `ValueError: Cannot continue run - unresolved step requirements`。
    """
    wf = workflow or build_weekly_report_workflow(db=get_workflow_db())
    reqs = pending_approvals(output)
    if not reqs:
        return output

    for req in reqs:
        req.confirmed = True
    logger.info("workflow.approve", steps=[r.step_name for r in reqs])

    return await wf.acontinue_run(
        run_response=output,
        run_id=getattr(output, "run_id", None),
        session_id=getattr(output, "session_id", None),
        step_requirements=reqs if approve_all else [reqs[0]],
    )


async def reject(
    output: Any,
    *,
    feedback: str = "内容需要修改",
    workflow: Workflow | None = None,
) -> Any:
    """人工点"驳回"。默认 `on_reject="skip"` —— 跳过发布，流程正常结束。

    这和"抛异常让流程崩掉"是两回事：驳回是一个**正常的业务结果**，
    不是故障。流水线该以"本期不发"结束，而不是报错。
    """
    wf = workflow or build_weekly_report_workflow(db=get_workflow_db())
    reqs = pending_approvals(output)
    if not reqs:
        return output

    for req in reqs:
        req.confirmed = False
        req.rejection_feedback = feedback
    logger.info("workflow.reject", steps=[r.step_name for r in reqs], feedback=feedback)

    return await wf.acontinue_run(
        run_response=output,
        run_id=getattr(output, "run_id", None),
        session_id=getattr(output, "session_id", None),
        step_requirements=reqs,
    )


async def load_pending_run(run_id: str, *, session_id: str | None = None) -> Any | None:
    """按 run_id 读回一个被挂起的 run。

    ⚠️ **实测坑**：`Workflow.aget_run_output(run_id)` 在没给 `session_id` 时
    会走到 `aget_session(None)` 并抛 `No session_id provided`。
    所以 `session_id` 是必需的，不是可选的。

    如果只有 run_id（CLI 场景），先用 `find_latest_pending_session()` 定位会话。

    Returns:
        `WorkflowRunOutput` 或 None（找不到）
    """
    db = get_workflow_db()
    if db is None:
        return None

    workflow = build_weekly_report_workflow(db=db)

    if session_id is None:
        return None
    return await workflow.aget_run_output(run_id, session_id=session_id)


async def find_latest_pending_session() -> str | None:
    """找出最近一个仍在等待人工确认的 session。

    ⚠️ 两个实测坑：
    1. Agno 的 `SqliteDb` 只提供**同步**的 `get_sessions()`。
       在 async 上下文里直接调是安全的 —— 它内部是本地 SQLite 查询，毫秒级。
    2. `session_type` 必须传 **`SessionType.WORKFLOW` 枚举**，
       传字符串 `"workflow"` 会报 `'str' object has no attribute 'value'`。

    Returns:
        session_id 或 None
    """
    sid, _ = await find_latest_pending_run()
    return sid


def _is_paused(output: Any) -> bool:
    """判断一个运行结果是否处于"等待人工确认"的暂停态。

    ⚠️ **实测坑**：`status` 在不同路径下返回的东西不一样 ——
    刚从 `run()` 返回时是 `RunStatus.paused`（枚举），
    从 db 反序列化出来的是 `PAUSED`（**大写**的枚举成员）。

    所以不能直接比字符串，要统一走 `str(...).lower()`。
    """
    return str(getattr(output, "status", "")).lower().endswith("paused")


async def find_latest_pending_run() -> tuple[str | None, str | None]:
    """找出最近一个待审批的 `(session_id, run_id)`。

    `run_id` 是必需的 —— `Workflow.aget_run_output(run_id)` 少了它
    会走到 `aget_session(None)` 并抛 `No session_id provided`。

    ⚠️ 两个实测坑：
    1. Agno 的 `SqliteDb` 只提供**同步**的 `get_sessions()`。
       在 async 上下文里直接调是安全的 —— 它内部是本地 SQLite 查询，毫秒级。
    2. `session_type` 必须传 **`SessionType.WORKFLOW` 枚举**，
       传字符串 `"workflow"` 会报 `'str' object has no attribute 'value'`。

    Returns:
        `(session_id, run_id)`；没有待审批项时返回 `(None, None)`
    """
    from agno.db.base import SessionType

    db = get_workflow_db()
    if db is None:
        return None, None

    try:
        sessions = db.get_sessions(session_type=SessionType.WORKFLOW)
    except Exception as exc:  # noqa: BLE001
        logger.warning("workflow.list_sessions_failed", error=str(exc))
        return None, None

    # 倒序遍历：Agno 按创建时间升序返回，最后一个最新
    for session in reversed(list(sessions or [])):
        sid = getattr(session, "session_id", None)
        if not sid:
            continue
        for run in reversed(getattr(session, "runs", None) or []):
            if _is_paused(run):
                return sid, getattr(run, "run_id", None)
    return None, None


# ------------------------------------------------------------------ 调试辅助


def dump_steps(output: Any) -> str:
    """把一次运行的每步结果打印出来（CLI 与单测共用）。"""
    lines: list[str] = []
    for s in getattr(output, "step_results", None) or []:
        status = "✅" if s.success else ("⏸" if s.is_paused else "❌")
        lines.append(f"  {status} {str(s.step_name):24s} {str(s.content or '')[:60]}")
    return "\n".join(lines) or "  （无步骤结果）"
