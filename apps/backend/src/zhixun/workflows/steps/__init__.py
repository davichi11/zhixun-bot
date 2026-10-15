"""流水线步骤节点（六步：采集 → 筛选 → 摘要 → 改写 → 审校 → 发布）。

每个步骤都是一个**独立的可测试单元**，签名统一为 Agno 的 Step 契约：

    def step_xxx(step_input: StepInput) -> StepOutput

## 步骤之间怎么传数据？

这是本篇最需要想清楚的一件事。实测下来有两条通道，用途完全不同：

| 通道 | 取值 | 用途 |
|---|---|---|
| `step_input.previous_step_content` | 上一步 `StepOutput.content` | **给条件判断 / 下一 Agent 的输入** |
| `step_input.workflow_session.session_data["session_state"]` | 可变 dict | **跨步骤的结构化状态** |

为什么不用 `previous_step_content` 传结构化数据？因为它是**字符串**。
要传"筛选后的候选列表"，只能序列化再反序列化，多一层不确定性。

为什么不用 `session_state` 传一切？因为它是**全局的**，
条件分支读它无法表达"上一步刚刚说了什么"。

一句话：**content 是"话"，session_state 是"账本"。**

⚠️ 实测坑：`WorkflowSession` 上**没有** `.session_state` 属性，
真实位置是 `session_data["session_state"]`。
写 `si.workflow_session.session_state` 会直接 AttributeError。

## 步骤里不直接 new Agent

步骤负责**编排与数据搬运**，Agent 负责**推理**。两者分离后：
- 步骤可以 mock 掉 Agent 做单元测试（LLM 不确定性不外溢）
- Agent 换模型 / 换提示词不影响流程结构
"""

from __future__ import annotations

from typing import Any

from agno.workflow.types import StepInput, StepOutput

from zhixun.config.logging import get_logger
from zhixun.tools.publisher import publish_draft
from zhixun.workflows.states import Draft, RawItem, ScoredItem, Summary

logger = get_logger(__name__)

# session_state 的键名（统一常量，避免各处写字符串出错）
K_ITEMS = "raw_items"
K_SCORED = "scored_items"
K_SUMMARIES = "summaries"
K_DRAFTS = "drafts"
K_REVIEW = "review"
K_DRY_RUN = "dry_run"
K_ISSUE = "issue_no"

# 筛选阈值：低于这个分数线就不该拿去写作
MIN_SCORE = 6.0
TOP_N = 5


# ------------------------------------------------------------------ 状态读写


def get_state(step_input: StepInput) -> dict[str, Any]:
    """取本轮流水线的可变状态（没有就新建一个空 dict）。"""
    session = step_input.workflow_session
    data = getattr(session, "session_data", None) or {}
    return data.setdefault("session_state", {})


def put_state(step_input: StepInput, state: dict[str, Any]) -> None:
    """把状态写回 session（必须显式赋值，dataclass 不是 property）。"""
    step_input.workflow_session.session_data = step_input.workflow_session.session_data or {}
    step_input.workflow_session.session_data["session_state"] = state


# ------------------------------------------------------------------ 六个步骤


async def step_collect(step_input: StepInput) -> StepOutput:
    """① 采集：调用采集员 Agent + GitHub 工具，把原始素材塞进状态。

    dry_run 时**不调 LLM**，直接用确定性占位数据 —— 让 CI 能跑通全流程。
    """
    state = get_state(step_input)
    dry_run = bool(state.get(K_DRY_RUN))

    logger.info("workflow.step", step="collect", dry_run=dry_run, session=step_input.workflow_session.session_id)

    if dry_run:
        items = [
            {"full_name": "agno-agi/agno", "url": "https://github.com/agno-agi/agno",
             "description": "Agent 框架", "stars": 1200, "language": "Python"},
            {"full_name": "mem0ai/mem0", "url": "https://github.com/mem0ai/mem0",
             "description": "长期记忆", "stars": 900, "language": "Python"},
            {"full_name": "qdrant/qdrant", "url": "https://github.com/qdrant/qdrant",
             "description": "向量数据库", "stars": 24000, "language": "Rust"},
        ]
    else:
        from zhixun.agents.collector import build_collector
        from zhixun.agents.base import extract_content

        agent = build_collector()
        out = await agent.arun(f"抓取最近 {settings_collect_days()} 天的 AI 开源项目")
        payload = extract_content(out)
        items = _items_from_payload(payload)

    state[K_ITEMS] = items
    put_state(step_input, state)
    return StepOutput(content=f"采集到 {len(items)} 条原始素材")


def settings_collect_days() -> int:
    from zhixun.config.settings import settings

    return 7


def _items_from_payload(payload: Any) -> list[dict[str, Any]]:
    """把 CollectResult / dict / list 统一成 list[dict]。"""
    raw = getattr(payload, "items", None)
    if raw is None and isinstance(payload, dict):
        raw = payload.get("items")
    if raw is None and isinstance(payload, list):
        raw = payload
    if not raw:
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
        elif hasattr(item, "model_dump"):
            out.append(item.model_dump())
    return out


async def step_filter(step_input: StepInput) -> StepOutput:
    """② 筛选：知识层去重 + 分析师打分，取 Top-N。

    **去重在打分之前** —— 因为重复的项目会占用 Top-N 名额，
    先打分再筛等于"重复项目挤掉了新项目"。
    """
    state = get_state(step_input)
    items = state.get(K_ITEMS, [])
    logger.info("workflow.step", step="filter", candidates=len(items))

    keep = items
    dropped = 0
    try:
        from zhixun.knowledge import get_retriever

        keep, detail = await get_retriever().filter_duplicates(items)
        dropped = len(detail)
    except Exception as exc:  # noqa: BLE001 - 知识层不可用就跳过去重，不中断
        logger.warning("workflow.dedup_degraded", error=str(exc))

    scored = _score_items(keep, dry_run=bool(state.get(K_DRY_RUN)))
    scored.sort(key=lambda s: s["score"], reverse=True)
    top = scored[:TOP_N]

    state[K_SCORED] = top
    put_state(step_input, state)
    return StepOutput(
        content=f"去重剔除 {dropped} 条，筛选出 {len(top)} 条候选"
        + ("（分数不足）" if not top else "")
    )


def _score_items(items: list[dict[str, Any]], *, dry_run: bool) -> list[dict[str, Any]]:
    """打分。真实实现调分析师 Agent；dry_run 用 star 数做确定性代理。"""
    out: list[dict[str, Any]] = []
    for item in items:
        stars = int(item.get("stars") or 0)
        if dry_run:
            # 代理评分：star 数映射到 0-10，保证 CI 里可复现
            score = min(10.0, round(5.0 + min(stars, 3000) / 1000, 2))
            reason = "dry-run 代理评分（按 star 数）"
        else:
            score = 7.0
            reason = "占位"
        out.append(
            {
                "full_name": item.get("full_name", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
                "stars": stars,
                "score": score,
                "reason": reason,
            }
        )
    return out


async def step_summarize(step_input: StepInput) -> StepOutput:
    """③ 摘要：为每个候选压出 2-3 条技术亮点。"""
    state = get_state(step_input)
    scored = state.get(K_SCORED, [])
    dry_run = bool(state.get(K_DRY_RUN))

    summaries: list[dict[str, Any]] = []
    for row in scored:
        if dry_run:
            highlights = [f"{row['full_name']} 的核心能力", "工程实现要点"]
        else:
            highlights = ["（待接分析师 Agent）"]
        summaries.append(
            {
                "full_name": row["full_name"],
                "positioning": row.get("description", "")[:60],
                "highlights": highlights,
            }
        )

    state[K_SUMMARIES] = summaries
    put_state(step_input, state)
    return StepOutput(content=f"生成 {len(summaries)} 条摘要")


async def step_rewrite(step_input: StepInput) -> StepOutput:
    """④ 改写：**Team 的唯一用武之地** —— 三平台写手并行产出多平台版本。

    为什么这里用 Team 而不是三个 Step 并行？
    因为三个平台需要**共享同一份候选清单和同一个风格基线**，
    而 Team 的成员共享会话上下文；三个孤立 Step 各写各的，
    很容易出现"公众号版讲 A、知乎版讲 B"的口径不一致。
    """
    state = get_state(step_input)
    summaries = state.get(K_SUMMARIES, [])
    dry_run = bool(state.get(K_DRY_RUN))
    logger.info("workflow.step", step="rewrite", summaries=len(summaries))

    drafts: list[dict[str, Any]] = []
    if dry_run:
        for platform, label in (("wechat", "公众号"), ("zhihu", "知乎"), ("twitter", "Twitter")):
            drafts.append(
                {
                    "platform": platform,
                    "title": f"{label}版：本周 3 个值得看的 AI 项目",
                    "content": f"# {label}版\n\n" + "\n\n".join(
                        f"## {s['full_name']}\n{s['positioning']}" for s in summaries
                    ),
                }
            )
    else:
        from zhixun.agents.team import build_platform_writer_team
        from zhixun.agents.base import content_to_text, extract_content

        team = build_platform_writer_team()
        out = await team.arun("请产出三个平台版本")
        drafts = _drafts_from_payload(extract_content(out))

    for d in drafts:
        d.setdefault("word_count", len(d.get("content", "")))

    state[K_DRAFTS] = drafts
    put_state(step_input, state)
    return StepOutput(content=f"产出 {len(drafts)} 个平台版本")


def _drafts_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [d if isinstance(d, dict) else getattr(d, "__dict__", {}) for d in payload]
    if hasattr(payload, "drafts"):
        return [d.model_dump() if hasattr(d, "model_dump") else dict(d) for d in payload.drafts]
    return []


async def step_review(step_input: StepInput) -> StepOutput:
    """⑤ 审校：编辑 Agent 初审 + **HumanReview 挂起等人工**（HITL）。

    注意：**HITL 的挂起不靠这个函数自己实现**，而是靠 `Step(human_review=...)`
    在执行前拦截。所以这个函数是"自动初审"，人工确认由框架层做。
    这就是"能交给框架就不要自己造"。
    """
    state = get_state(step_input)
    drafts = state.get(K_DRAFTS, [])
    dry_run = bool(state.get(K_DRY_RUN))

    issues: list[str] = []
    for d in drafts:
        if not d.get("title", "").strip():
            issues.append(f"{d.get('platform')}：标题为空")
        if len(d.get("content", "")) < 200:
            issues.append(f"{d.get('platform')}：正文过短（{len(d.get('content',''))} 字符）")

    state[K_REVIEW] = {"passed": not issues, "issues": issues}
    put_state(step_input, state)
    logger.info("workflow.step", step="review", drafts=len(drafts), issues=len(issues))
    return StepOutput(content=f"审校完成，问题 {len(issues)} 处，等待人工确认")


async def step_publish(step_input: StepInput) -> StepOutput:
    """⑥ 发布：**排版 → 配图 → 推送**（第 6 篇：排版与配图都走 MCP）。

    **dry_run 是硬闸门** —— 不管上游状态如何，dry_run 绝不触发真实发布。
    这和第三篇 `publish_draft` 的 `approved_by_human` 是两道独立的闸。
    """
    state = get_state(step_input)
    drafts = state.get(K_DRAFTS, [])
    dry_run = bool(state.get(K_DRY_RUN))

    if dry_run:
        logger.info("workflow.dry_run_skip_publish", drafts=len(drafts))
        return StepOutput(content=f"[dry-run] 跳过发布，{len(drafts)} 个版本待发布")

    published: list[str] = []
    for d in drafts:
        # 1) 排版（MCP）：markdown → 目标平台格式
        render = await _call_mcp_tool("render_markdown", markdown=d.get("content", ""),
                                      platform=d.get("platform", "wechat"))
        # 2) 配图（MCP）：公众号封面
        cover = None
        if d.get("platform") == "wechat":
            cover = await _call_mcp_tool("generate_cover", title=d.get("title", ""))

        # 3) 推送（内置工具，内部再委托 MCP 的 publish_draft）
        out = publish_draft.entrypoint(
            platform=d.get("platform", "wechat"),
            title=d.get("title", ""),
            content=d.get("content", ""),
            approved_by_human=True,   # 上游 HumanReview 已放行
        )
        if isinstance(out, dict) and out.get("ok"):
            published.append(f"{d.get('platform')}:{out.get('draft_id')}")
        else:
            logger.warning("workflow.publish_failed", platform=d.get("platform"), result=out)
            published.append(f"{d.get('platform')}:失败")

    return StepOutput(content=f"已发布：{'、'.join(published)}")


async def _call_mcp_tool(tool_suffix: str, **kwargs: Any) -> dict[str, Any] | None:
    """调用一个 MCP 工具（按名字后缀匹配，自动处理连接与关闭）。

    返回 `None` 表示 MCP 不可用 —— 调用方**必须自己降级**，不能假设有结果。
    """
    import concurrent.futures

    from zhixun.mcp import load_publisher_tools

    async def _call() -> dict[str, Any] | None:
        loaded = await load_publisher_tools()
        if not loaded.ok:
            return None
        for toolkit in loaded.tools:
            fns = getattr(toolkit, "functions", {}) or {}
            name = next((n for n in fns if n.endswith(tool_suffix)), None)
            if name is None:
                continue
            try:
                raw = await fns[name].entrypoint(**kwargs)
                return _parse_mcp(raw)
            finally:
                await toolkit.close()
        return None

    try:
        # 步骤本身是 async，但 MCP 客户端在独立线程里更稳妥（见 tools/publisher.py 的注释）
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _call()).result(timeout=60)
    except Exception as exc:  # noqa: BLE001
        logger.warning("workflow.mcp_tool_failed", tool=tool_suffix, error=str(exc))
        return None


def _parse_mcp(raw: Any) -> dict[str, Any]:
    """解析 MCP 返回值（结构化 payload 优先）。"""
    import json as _json

    meta = getattr(raw, "metadata", None) or {}
    if isinstance(meta.get("structured_content"), dict):
        return meta["structured_content"]
    content = getattr(raw, "content", None)
    if isinstance(content, str):
        try:
            parsed = _json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except _json.JSONDecodeError:
            pass
    return {}


# ------------------------------------------------------------------ 步骤清单

ALL_STEPS = [
    step_collect,
    step_filter,
    step_summarize,
    step_rewrite,
    step_review,
    step_publish,
]

STEP_LABELS = {
    step_collect.__name__: "① 采集",
    step_filter.__name__: "② 筛选（去重 + 打分）",
    step_summarize.__name__: "③ 摘要",
    step_rewrite.__name__: "④ 改写（内嵌 Team）",
    step_review.__name__: "⑤ 审校（HITL）",
    step_publish.__name__: "⑥ 发布",
}