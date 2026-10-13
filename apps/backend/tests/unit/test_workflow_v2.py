"""流水线层单元测试（第 5 篇）。

原则：绝不调用真实 LLM —— 全部走 `dry_run=True` 分支。
HITL 的挂起/恢复需要真实的 Agno db，因此用 `tmp_path` 隔离。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agno.workflow import Condition, HumanReview, Step

from zhixun.workflows import (
    MIN_CANDIDATES,
    approve,
    build_weekly_report_workflow,
    describe_pending,
    dump_steps,
    has_enough_candidates,
    pending_approvals,
    reject,
    run_weekly_report,
)
from zhixun.workflows.steps import (
    STEP_LABELS,
    get_state,
    step_collect,
    step_filter,
    step_publish,
    step_review,
    step_rewrite,
    step_summarize,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """把工作流 db 指向 tmp_path，绝不碰仓库里的真实库。"""
    import zhixun.workflows.weekly_report as wr

    def _fake_db():
        from agno.db.sqlite import SqliteDb

        return SqliteDb(db_file=str(tmp_path / "wf.db"))

    monkeypatch.setattr(wr, "get_workflow_db", _fake_db)
    yield


# ---------------------------------------------------------------- 结构


def test_workflow_has_six_named_steps() -> None:
    """六个步骤都要有中文标签（它们会直接显示在前端进度条上）。"""
    labels = set(STEP_LABELS.values())
    assert len(labels) == 6
    assert "④ 改写（内嵌 Team）" in labels
    assert "⑤ 审校（HITL）" in labels


def test_workflow_structure_puts_review_at_top_level() -> None:
    """回归防护：HumanReview 写在 Condition 内部**不生效**（实测 paused→completed）。

    这条测试守着第五篇最贵的一个发现 —— 结构一旦改回去，
    流水线会静默地"永远自动发布"，且不报任何错。
    """
    wf = build_weekly_report_workflow()
    top_level_review = [
        s for s in wf.steps if getattr(getattr(s, "human_review", None), "requires_confirmation", False)
    ]
    assert len(top_level_review) == 1, "人工审校必须是顶层 Step"

    # 且 Condition 内部不应再有 HumanReview
    for container in wf.steps:
        if isinstance(container, Condition):
            for s in container.steps:
                hr = getattr(s, "human_review", None)
                assert not getattr(hr, "requires_confirmation", False), (
                    "Condition 内的 HumanReview 不会生效"
                )


def test_review_uses_cancel_not_skip() -> None:
    """回归防护：`on_reject="skip"` 会让发布步骤照样执行（实测）。

    对一个紧挨发布工具的审校节点，那是致命的默认值。
    """
    wf = build_weekly_report_workflow()
    review = next(
        s for s in wf.steps if getattr(getattr(s, "human_review", None), "requires_confirmation", False)
    )
    assert review.human_review.on_reject == "cancel"


def test_workflow_enables_session_state_context() -> None:
    wf = build_weekly_report_workflow()
    assert wf.add_session_state_to_context is True
    assert wf.store_executor_outputs is True


# ---------------------------------------------------------------- 条件分支


class _FakeSession:
    def __init__(self) -> None:
        self.session_data: dict = {}


class _FakeStepInput:
    def __init__(self, content: str = "", session_data: dict | None = None) -> None:
        self.previous_step_content = content
        self.workflow_session = _FakeSession()
        if session_data is not None:
            self.workflow_session.session_data = session_data


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("去重剔除 2 条，筛选出 5 条候选", True),
        ("去重剔除 8 条，筛选出 1 条候选", False),
        ("筛选出 3 条候选", True),          # 恰好等于阈值
        ("筛选出 2 条候选", False),
        ("", False),                        # 解析不出数字 → 不进入
    ],
)
def test_branch_parses_count_from_content(content: str, expected: bool) -> None:
    assert has_enough_candidates(_FakeStepInput(content)) is expected


def test_branch_tolerates_missing_session() -> None:
    """evaluator 拿不到 workflow_session 时不能崩 —— 实测它就是 None。"""
    si = _FakeStepInput("筛选出 9 条候选")
    si.workflow_session = None  # type: ignore[assignment]
    assert has_enough_candidates(si) is True


def test_min_candidates_is_sane() -> None:
    assert MIN_CANDIDATES >= 1


def test_step_default_max_retries_is_three() -> None:
    """认知固化：Agno 的 Step **默认重试 3 次**（不是 0 次）。

    这条不是测我们的代码，是测"框架默认值"——
    因为它直接决定了 LLM 步骤失败时会不会静默烧三次钱。
    如果哪天升级框架改了默认值，这条测试会提醒我们重新评估成本策略。
    """
    probe = Step(name="probe", executor=lambda si: None)
    assert probe.max_retries == 3
    assert probe.skip_on_failure is False


# ---------------------------------------------------------------- 状态字符串的坑


def test_is_paused_handles_both_enum_shapes() -> None:
    """`status` 从内存和从 db 出来形状不同：小写 vs 大写枚举。

    这条踩过真实的坑 —— `find_latest_pending_run()` 用 `endswith("paused")`
    判断内存里的枚举没问题，但从 db 反序列化出来的是 `PAUSED`，导致
    `approve --latest` 永远找不到待审批的 run。
    """
    from enum import Enum

    from zhixun.workflows.weekly_report import _is_paused

    class _RunStatusLower(Enum):
        paused = "paused"

    class _RunStatusUpper(Enum):
        PAUSED = "PAUSED"

    class _Fake:
        def __init__(self, status):
            self.status = status

    assert _is_paused(_Fake(_RunStatusLower.paused)) is True
    assert _is_paused(_Fake(_RunStatusUpper.PAUSED)) is True
    assert _is_paused(_Fake("RunStatus.paused")) is True
    assert _is_paused(_Fake("completed")) is False
    assert _is_paused(None) is False


async def test_find_latest_pending_run_locates_paused_run() -> None:
    """端到端：跑一次 → 挂起 → 能被 find_latest_pending_run 找到。"""
    from zhixun.workflows import find_latest_pending_run

    out = await run_weekly_report(dry_run=True, issue_no=8)
    assert str(out.status).lower().endswith("paused")

    session_id, run_id = await find_latest_pending_run()
    assert session_id == out.session_id
    assert run_id == out.run_id


# ---------------------------------------------------------------- dry-run 全链路


async def test_dry_run_completes_without_human() -> None:
    """--skip-review 时应一口气跑完（CI 依赖这个）。"""
    out = await run_weekly_report(dry_run=True, issue_no=1, skip_review=True)
    assert str(out.status).endswith("completed")
    assert pending_approvals(out) == []


async def test_dry_run_never_publishes() -> None:
    """dry_run 是发布硬闸门：即使全部通过也必须跳过发布。"""
    out = await run_weekly_report(dry_run=True, issue_no=1, skip_review=True)
    assert "dry-run" in str(out.content) or "跳过发布" in str(out.content)


async def test_run_pauses_at_review() -> None:
    """正式跑必须挂在人工审校处。"""
    out = await run_weekly_report(dry_run=True, issue_no=2)
    assert str(out.status).endswith("paused")
    reqs = pending_approvals(out)
    assert len(reqs) == 1
    assert "审校" in str(reqs[0].step_name)
    assert "等待人工确认" in describe_pending(out)


async def test_approve_resumes_and_publishes() -> None:
    out = await run_weekly_report(dry_run=True, issue_no=3)
    out2 = await approve(out)
    assert str(out2.status).endswith("completed")
    names = [str(s.step_name) for s in (out2.step_results or [])]
    assert any("发布" in n for n in names), "通过后发布步骤必须执行"


async def test_reject_cancels_and_skips_publish() -> None:
    """驳回是**正常业务结果**，不是故障：流程以 cancelled 结束，且不发布。"""
    out = await run_weekly_report(dry_run=True, issue_no=4)
    out2 = await reject(out, feedback="数据不准")
    assert str(out2.status).endswith("cancelled")
    names = [str(s.step_name) for s in (out2.step_results or [])]
    assert not any("发布" in n for n in names), "驳回后绝不能发布"


async def test_approve_on_non_paused_run_is_noop() -> None:
    """没有待办时 approve 不应报错（幂等）。"""
    out = await run_weekly_report(dry_run=True, issue_no=5, skip_review=True)
    out2 = await approve(out)
    assert str(out2.status).endswith("completed")


async def test_describe_pending_when_none() -> None:
    out = await run_weekly_report(dry_run=True, issue_no=6, skip_review=True)
    assert "没有待人工确认" in describe_pending(out)


async def test_dump_steps_is_readable() -> None:
    out = await run_weekly_report(dry_run=True, issue_no=7, skip_review=True)
    text = dump_steps(out)
    assert "① 采集" in text
    assert len(text.splitlines()) >= 3


# ---------------------------------------------------------------- 步骤级契约


async def test_steps_are_callable_with_step_input() -> None:
    """六个步骤的签名统一，Agno 才能统一调度。"""
    for fn in (step_collect, step_filter, step_summarize, step_rewrite, step_review, step_publish):
        assert callable(fn)
        assert fn.__name__ in STEP_LABELS, f"{fn.__name__} 缺少中文标签"


async def test_session_state_roundtrip() -> None:
    from agno.workflow import StepInput, StepOutput

    si = _FakeStepInput()  # type: ignore[arg-type]
    state = get_state(si)
    state["k"] = "v"
    from zhixun.workflows.steps import put_state

    put_state(si, state)
    assert get_state(si)["k"] == "v"


async def test_review_flags_empty_title_and_short_content() -> None:
    from agno.workflow import StepOutput

    from zhixun.workflows.steps import K_DRAFTS, put_state

    si = _FakeStepInput()  # type: ignore[arg-type]
    state = get_state(si)
    state[K_DRAFTS] = [
        {"platform": "wechat", "title": "  ", "content": "太短"},
        {"platform": "zhihu", "title": "正常标题", "content": "正文" * 200},
    ]
    put_state(si, state)

    out = await step_review(si)  # type: ignore[arg-type]
    assert isinstance(out, StepOutput)
    assert "问题 2 处" in str(out.content)
    assert state["review"]["passed"] is False


async def test_publish_step_blocks_on_dry_run() -> None:
    """发布步骤自身也要认 dry_run —— 不能只靠外层把关。"""
    from agno.workflow import StepOutput

    from zhixun.workflows.steps import K_DRAFTS, K_DRY_RUN, put_state

    si = _FakeStepInput()  # type: ignore[arg-type]
    state = get_state(si)
    state[K_DRY_RUN] = True
    state[K_DRAFTS] = [{"platform": "wechat", "title": "t", "content": "正文" * 200}]
    put_state(si, state)

    out = await step_publish(si)  # type: ignore[arg-type]
    assert isinstance(out, StepOutput)
    assert "dry-run" in str(out.content)


def test_step_labels_human_readable() -> None:
    """步骤标签会直接进前端进度条 —— 必须是人话。"""
    for label in STEP_LABELS.values():
        assert "①" in label or "②" in label or "③" in label or "④" in label or "⑤" in label or "⑥" in label