"""命令行入口。

用法：
    uv run zhixun run --dry-run            # 干跑一次周报流水线
    uv run zhixun serve                    # 启动 API 服务

    # ---- 第二篇：Agent 调试三件套 ----
    uv run zhixun agents --list            # 列出全部 Agent、模型档位与提示词版本
    uv run zhixun agents --audit           # 提示词治理自检（建议挂进 CI）
    uv run zhixun agents --show-prompt analyst   # 打印渲染后的完整提示词（无需 API key）
    uv run zhixun agents --role collector --message "抓一下本周 AI 开源项目"

    # ---- 第三篇：工具调试三件套 ----
    uv run zhixun tools --list             # 列出工具授权表（谁被授予了什么）
    uv run zhixun tools --builtin          # 内置工具包可用性（缺哪些可选依赖）
    uv run zhixun tools --call fetch_trending_repos --arg days=7 --arg limit=3

    # ---- 第四篇：知识层调试四件套 ----
    uv run zhixun knowledge --stats        # 知识层状态（向量库/索引/已发布条目）
    uv run zhixun knowledge --ingest       # 把历史文章目录入库（切片→Embedding→索引）
    uv run zhixun knowledge --search "混合检索怎么实现"
    uv run zhixun knowledge --check-dup agno-agi/agno --url https://github.com/agno-agi/agno

    # ---- 第五篇：流水线 + 人工审批 ----
    uv run zhixun run --dry-run --skip-review     # 全链路直跑（CI 用，不需要人工点）
    uv run zhixun run --issue 42                  # 正式跑，会在"人工审校"处挂起
    uv run zhixun approve <run_id>                # 人工点"通过"，恢复并发布
    uv run zhixun approve <run_id> --reject --feedback "数据不准"   # 人工驳回

    # ---- 第六篇：能力扩展 ----
    uv run zhixun mcp --list            # MCP Server 注册表与可用性
    uv run zhixun mcp --call render_markdown --arg markdown="# 标题" --arg platform=wechat
    uv run zhixun skills --list         # 已沉淀的技能清单与按角色分配
"""

from __future__ import annotations

import argparse
import asyncio

from zhixun.config.logging import configure_logging, get_logger
from zhixun.config.settings import settings

logger = get_logger("zhixun.cli")


def _cmd_run(args: argparse.Namespace) -> int:
    """跑一次周报流水线（第 5 篇：交给 Agno Workflow 编排）。"""
    from zhixun.workflows import describe_pending, dump_steps, run_weekly_report

    output = asyncio.run(
        run_weekly_report(
            dry_run=args.dry_run,
            issue_no=args.issue,
            skip_review=args.skip_review,
        )
    )
    status = str(getattr(output, "status", "?")).split(".")[-1]
    run_id = getattr(output, "run_id", None)
    session_id = getattr(output, "session_id", None)

    print(f"\n===== 流水线状态：{status} =====")
    print(f"run_id={run_id}  session_id={session_id}")
    print(dump_steps(output))

    pending = describe_pending(output)
    if "等待人工确认" in pending:
        print(f"\n{pending}")
        print(f"\n下一步：uv run zhixun approve {run_id} --session-id {session_id}   # 点通过")
        print(f"        uv run zhixun approve {run_id} --latest --reject           # 点驳回")
    return 0


def _cmd_approve(args: argparse.Namespace) -> int:
    """人工审批：恢复一个被挂起的 run。"""
    from zhixun.workflows import approve, dump_steps, reject
    from zhixun.workflows.weekly_report import (
        build_weekly_report_workflow,
        find_latest_pending_run,
        get_workflow_db,
    )

    db = get_workflow_db()
    if db is None:
        print("❌ 没有数据库连接，无法恢复被挂起的 run（HITL 状态存在 db 里）。")
        return 1

    workflow = build_weekly_report_workflow(db=db)

    run_id, session_id = args.run_id, args.session_id

    # --latest（或没给 run_id）：自动定位最近一个待审批的会话
    if args.latest or not run_id:
        session_id, found_run = asyncio.run(find_latest_pending_run())
        if session_id is None or found_run is None:
            print("❌ 没有找到待审批的 run。用 `zhixun run --dry-run` 先跑一次。")
            return 1
        run_id = run_id or found_run
        print(f"定位到待审批：run_id={run_id}  session_id={session_id}")
    elif session_id is None:
        print("❌ 需要 --session-id（或改用 --latest 自动定位）。")
        return 1

    output = asyncio.run(workflow.aget_run_output(run_id, session_id=session_id))
    if output is None:
        print(f"❌ 找不到 run：{run_id}（session={session_id}）")
        return 1

    if args.reject:
        feedback = args.feedback or "内容需要修改"
        print(f"\n===== 驳回（{feedback}）=====")
        output = asyncio.run(reject(output, feedback=feedback, workflow=workflow))
    else:
        print("\n===== 人工确认通过 =====")
        output = asyncio.run(approve(output, workflow=workflow))

    print(f"status = {str(getattr(output, 'status', '?')).split('.')[-1]}")
    print(dump_steps(output))
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "zhixun.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


# ---------------------------------------------------------------- agents


def _cmd_agents(args: argparse.Namespace) -> int:
    """Agent 调试三件套：list / audit / show-prompt，以及真实运行。"""
    from zhixun.agents import AGENT_BUILDERS, SPECS, audit_specs, spec_summary
    from zhixun.config.llm import describe
    from zhixun.prompts import list_prompts, render_prompt

    # 1) 列清单
    if args.list or not any((args.audit, args.show_prompt, args.role)):
        models = describe()
        print(f"\n模型矩阵：primary={models['primary']}  light={models['light']}\n")
        header = f"{'role':<10} {'名称':<8} {'档位':<8} {'提示词':<22} {'输出契约':<16} 指令"
        print(header)
        print("-" * len(header))
        for key, spec in SPECS.items():
            s = spec_summary(spec)
            prompt = f"{s['prompt']}@v{s['prompt_version']}" if s["prompt"] else "(内联)"
            print(
                f"{key:<10} {s['name']:<8} {s['tier']:<8} {prompt:<22} "
                f"{s['schema'] or '-':<16} {s['instructions']}"
            )
        print(f"\n提示词模板：{', '.join(list_prompts())}")
        if not args.audit and not args.show_prompt and not args.role:
            return 0

    # 2) 治理自检
    if args.audit:
        problems = audit_specs()
        if problems:
            print("\n❌ 提示词治理自检未通过：")
            for p in problems:
                print(f"   - {p}")
            return 1
        print("\n✅ 提示词治理自检通过：所有 Agent 均已绑定提示词模板。")

    # 3) 打印最终提示词（这一步完全不碰 LLM，可离线 review）
    if args.show_prompt:
        name = args.show_prompt
        extra = _parse_vars(args.var)
        print(f"\n{'=' * 72}\n提示词模板：{name}\n{'=' * 72}\n")
        print(render_prompt(name, **extra))
        return 0

    # 4) 真实运行
    if args.role:
        if not args.message:
            print("请用 --message 指定要交给 Agent 的任务。")
            return 2
        if args.role not in AGENT_BUILDERS:
            print(f"未知 role：{args.role}。可用：{', '.join(sorted(AGENT_BUILDERS))}")
            return 2

        from zhixun.agents import run_text

        agent = AGENT_BUILDERS[args.role]()
        print(f"\n[运行] role={args.role}  model={getattr(agent.model, 'id', '?')}\n")
        print(run_text(agent, args.message))
        return 0

    return 0


def _parse_vars(pairs: list[str] | None) -> dict[str, str]:
    """把 `--var k=v` 解析成 dict。"""
    out: dict[str, str] = {}
    for item in pairs or []:
        if "=" not in item:
            raise SystemExit(f"--var 需要 key=value 形式，收到：{item!r}")
        key, _, value = item.partition("=")
        out[key.strip()] = value.strip()
    return out


# ---------------------------------------------------------------- tools


def _coerce(value: str) -> object:
    """把命令行字符串尽力转成标量类型（int / float / bool / str）。"""
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            continue
    return value


def _cmd_tools(args: argparse.Namespace) -> int:
    """工具调试三件套：授权表 / 内置可用性 / 直接调用。"""
    from zhixun.tools import TOOL_GROUPS, get_tools
    from zhixun.tools.guards import budget_snapshot, reset_budget

    # 1) 内置工具包可用性（缺哪些可选依赖）
    if args.builtin or not any((args.call, args.list)):
        from zhixun.tools.builtin import available_builtins, unavailable_builtins

        print(f"\n本机可用的 Agno 内置工具包：{', '.join(available_builtins()) or '(无)'}")
        for name, hint in unavailable_builtins().items():
            print(f"  ⚠️ {name:<12} 缺少依赖 → {hint}")
        if not args.call and not args.list:
            return 0

    # 2) 授权表：谁能调用什么
    if args.list or not args.call:
        from zhixun.tools import TOOL_GROUPS, describe_toolsets

        print("\n===== 工具授权表（最小权限）=====")
        header = f"{'角色':<12} {'数量':<6} {'工具':<64} 声明"
        print(header)
        print("-" * len(header))
        for row in describe_toolsets():
            print(f"{row['role']:<12} {row['count']:<6} {row['tools']:<64} {row['declared']}")
            if row["degraded"] != "-":
                print(f"{'':<12} {'':<6} ⚠️ 依赖降级：{row['degraded']}")
        print(f"\n工具组：{', '.join(sorted(TOOL_GROUPS))}")
        if not args.call:
            return 0

    # 3) 直接调用一个工具（真联网，注意会消耗真实配额）
    name = args.call
    all_tools = {t.name: t for t in get_tools(*TOOL_GROUPS)}
    if name not in all_tools:
        print(f"未知工具：{name}。可用：{', '.join(sorted(all_tools))}")
        return 2

    kwargs = {k: _coerce(v) for k, v in _parse_vars(args.arg).items()}
    reset_budget()
    print(f"\n[调用] {name}  参数={kwargs or '(无)'}")
    print(f"工具预算：{budget_snapshot()}")
    try:
        # 走 entrypoint 直接调用底层函数，绕过 Agent —— 便于单点调试
        result = all_tools[name].entrypoint(**kwargs)
    except Exception as exc:  # noqa: BLE001 - CLI 要把异常打给人看，而不是抛栈
        print(f"\n❌ {type(exc).__name__}: {exc}")
        return 1

    import json

    print("\n" + json.dumps(result, ensure_ascii=False, indent=2)[:4000])
    return 0


# ---------------------------------------------------------------- knowledge


def _cmd_knowledge(args: argparse.Namespace) -> int:
    """知识层调试四件套：状态 / 入库 / 检索 / 去重自检。"""
    import asyncio

    from zhixun.knowledge.ingest import describe_pipeline, ingest_history

    wants_ingest = bool(args.ingest)

    # 1) 管道配置（不执行，纯展示）
    if args.stats or not any((wants_ingest, args.search, args.check_dup)):
        print("\n===== 知识层管道 =====")
        for key, value in describe_pipeline().items():
            print(f"  {key:14s}: {value}")

    if not any((wants_ingest, args.search, args.check_dup)):
        return _print_knowledge_stats()

    # 2) 入库
    if wants_ingest:
        result = asyncio.run(ingest_history(args.dir))
        print(f"\n===== 入库完成（{result.elapsed_ms}ms）=====")
        print(f"  {result.summary()}")
        if not result.chunks:
            print("  ⚠️ 没有读到任何文章。用 --dir 指定历史文章目录。")
        return 0

    # 3) 检索
    if args.search:
        from zhixun.knowledge import get_retriever
        from zhixun.knowledge.rag.vector_store import get_vector_store

        # 内存后端是**进程内**的：上一个进程入库的数据这里读不到。
        # 所以先探一下，空库就顺手入库一次 —— 让 CLI 开箱可用。
        probe = asyncio.run(get_vector_store().all_records())
        if not probe:
            print("（索引为空，先执行一次自动入库 —— 内存后端不跨进程持久化）")
            asyncio.run(ingest_history(args.dir))

        ctx = asyncio.run(get_retriever().retrieve(args.search, need_dedup=True, need_style=True))

        print(f'\n===== 检索："{args.search}" =====')
        if not ctx.style_samples:
            print("  （无命中）")
        for i, s in enumerate(ctx.style_samples, start=1):
            print(f"\n  [{i}] RRF={s.score:.5f}  {s.article_id}")
            print(f"      {s.title}")
            head = s.excerpt[:120].replace("\n", " ")
            print(f"      {head}…")

        print(
            f"\n===== 渐进式披露：三档对比"
            f"（项目 {len(ctx.published_projects)} 条 / 范文 {len(ctx.style_samples)} 篇）====="
        )
        from zhixun.knowledge.memory.compressor import estimate_tokens

        for level in ("summary", "standard", "full"):
            rendered = ctx.render(detail_level=level)
            print(f"  {level:9s} {estimate_tokens(rendered):>6d} tokens")
        return 0

    # 4) 去重自检
    if args.check_dup:
        from zhixun.knowledge import get_retriever

        retriever = get_retriever()
        ctx = asyncio.run(retriever.retrieve("dedup", need_dedup=True))
        published = ctx.published_projects

        print("\n===== 去重判定 =====")
        print(f"  候选标题: {args.check_dup}")
        print(f"  候选 URL : {args.url or '(无)'}")

        if not published:
            verdict = None
        else:
            verdict = asyncio.run(
                retriever._dedup.check(
                    url=args.url or "",
                    title=args.check_dup,
                    published=published,
                    embedder=retriever._embedder,
                )
            )
            print(f"  命中阶段 : {verdict.stage or '(未命中)'}")
            print(f"  判定     : {'重复' if verdict.is_duplicate else '不重复'}")
            print(f"  相似度   : {verdict.similarity}")
            print(f"  原因     : {verdict.reason}")
        print(f"  历史库规模: {len(published)} 条" + ("（空库，恒判定不重复）" if not published else ""))
        return 0

    return 0


def _print_knowledge_stats() -> int:
    """打印知识层状态（向量库 + 索引 + 已发布条目）。"""
    import asyncio

    from zhixun.db.session import dispose_db, init_db
    from zhixun.knowledge import get_retriever
    from zhixun.knowledge.memory.storage import MemoryStore

    async def _run() -> None:
        await init_db()
        retriever = get_retriever()
        stats = await retriever._retriever.stats()
        store = MemoryStore()
        print("\n===== 知识层状态 =====")
        print(f"  向量库后端 : {stats['backend']}")
        print(f"  已入库切片 : {stats['chunks']}")
        print(f"  覆盖文章数 : {stats['articles']}")
        print(f"  索引字符数 : {stats['chars_indexed']}")
        print(f"  已发布项目 : {await store.count_published()}")
        print(f"  关注方向   : {'、'.join(await store.list_focus_topics())}")
        await dispose_db()

    asyncio.run(_run())
    return 0


def _cmd_mcp(args: argparse.Namespace) -> int:
    """MCP 调试：Server 注册表 / 真实调用。"""
    from zhixun.mcp import describe_mcp_servers, load_mcp_tools

    if not args.call:
        print("\n===== MCP Server 注册表 =====")
        for row in describe_mcp_servers():
            mark = "✅" if row["ready"] else "⚠️"
            print(f"  {mark} {row['name']:18s} {row['description']}")
            print(f"      命令: {row['command']}")
            if not row["enabled"]:
                print("      状态: 已通过配置禁用")
            if row["hint"]:
                print(f"      安装: {row['hint']}")
        return 0

    async def _run() -> int:
        loaded = await load_mcp_tools()
        print(f"\n连接成功: {loaded.connected or '(无)'}")
        if loaded.failed:
            print(f"连接失败: {loaded.failed}")
        if loaded.unavailable_reason:
            print(f"不可用: {loaded.unavailable_reason}")
            return 1

        kwargs = {k: _coerce(v) for k, v in _parse_vars(args.arg).items()}
        for toolkit in loaded.tools:
            fns = getattr(toolkit, "functions", {}) or {}
            name = next((n for n in fns if n.endswith(args.call) or n == args.call), None)
            if name is None:
                continue
            print(f"[调用] {name}  参数={kwargs or '(无)'}")
            raw = await fns[name].entrypoint(**kwargs)
            import json as _json

            payload = (getattr(raw, "metadata", None) or {}).get("structured_content")
            if payload is None:
                payload = getattr(raw, "content", "")
            print("\n" + _json.dumps(payload, ensure_ascii=False, indent=2)[:3000]
                  if not isinstance(payload, str) else payload[:3000])
            await toolkit.close()
            return 0

        print(f"没有找到匹配 {args.call} 的工具。可用："
              f"{[n for t in loaded.tools for n in getattr(t, 'functions', {})]}")
        return 1

    return asyncio.run(_run())


def _cmd_skills(args: argparse.Namespace) -> int:
    """技能调试：清单与按角色分配。"""
    from zhixun.skills import describe_skills

    info = describe_skills()
    print("\n===== 技能清单 =====")
    if not info.available:
        print(f"  ⚠️ {info.error}")
        return 1

    header = f"{'技能':<18}{'字数':>6}  允许使用的工具"
    print(f"  {header}")
    print("  " + "-" * 70)
    for row in info.detail:
        print(f"  {row['name']:<18}{row['chars']:>6}  {row['allowed_tools']}")
        print(f"  {'':<18}{'':>6}  {row['description']}")

    print("\n===== 按角色分配（最小权限思路的延续）=====")
    for role, names in info.by_agent.items():
        print(f"  {role:<12} → {'、'.join(names) if names else '(无)'}")
    return 0


def main() -> int:
    configure_logging()

    parser = argparse.ArgumentParser(prog="zhixun", description=f"{settings.app_name} CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="跑一次周报流水线")
    p_run.add_argument("--dry-run", action="store_true", help="干跑，不调 LLM、不发布")
    p_run.add_argument("--issue", type=int, help="第几期周报")
    p_run.add_argument("--skip-review", action="store_true",
                       help="跳过人工审校（仅与 --dry-run 搭配使用）")
    p_run.set_defaults(func=_cmd_run)

    p_approve = sub.add_parser("approve", help="人工审批一个被挂起的 run")
    p_approve.add_argument("run_id", nargs="?", help="待审批的 run_id")
    p_approve.add_argument("--session-id", help="所属 session_id（--latest 可省略）")
    p_approve.add_argument("--latest", action="store_true",
                           help="自动定位最近一个待审批的会话")
    p_approve.add_argument("--reject", action="store_true", help="驳回而不是通过")
    p_approve.add_argument("--feedback", help="驳回理由（会写入 rejection_feedback）")
    p_approve.set_defaults(func=_cmd_approve)

    p_serve = sub.add_parser("serve", help="启动 API 服务")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=_cmd_serve)

    p_agents = sub.add_parser("agents", help="Agent 调试：清单 / 自检 / 提示词预览 / 运行")
    p_agents.add_argument("--list", action="store_true", help="列出全部 Agent")
    p_agents.add_argument("--audit", action="store_true", help="提示词治理自检")
    p_agents.add_argument("--show-prompt", metavar="NAME", help="打印渲染后的提示词（离线）")
    p_agents.add_argument("--var", action="append", metavar="k=v", help="show-prompt 的模板变量")
    p_agents.add_argument("--role", help="要运行的 Agent role")
    p_agents.add_argument("--message", help="交给 Agent 的任务描述")
    p_agents.set_defaults(func=_cmd_agents)

    p_tools = sub.add_parser("tools", help="工具调试：授权表 / 内置可用性 / 直接调用")
    p_tools.add_argument("--list", action="store_true", help="列出工具授权表")
    p_tools.add_argument("--builtin", action="store_true", help="列出内置工具包可用性")
    p_tools.add_argument("--call", metavar="NAME", help="直接调用某个工具（真联网）")
    p_tools.add_argument("--arg", action="append", metavar="k=v", help="调用参数")
    p_tools.set_defaults(func=_cmd_tools)

    p_know = sub.add_parser("knowledge", help="知识层调试：状态 / 入库 / 检索 / 去重自检")
    p_know.add_argument("--stats", action="store_true", help="知识层状态与管道配置")
    p_know.add_argument("--ingest", action="store_true", help="把历史文章目录入库")
    p_know.add_argument("--dir", help="历史文章目录（默认取配置）")
    p_know.add_argument("--search", metavar="QUERY", help="混合检索一篇范文")
    p_know.add_argument("--check-dup", metavar="TITLE", help="对给定标题做一次去重判定")
    p_know.add_argument("--url", help="配合 --check-dup 使用的 URL")
    p_know.set_defaults(func=_cmd_knowledge)

    p_mcp = sub.add_parser("mcp", help="MCP 调试：Server 清单 / 直接调用")
    p_mcp.add_argument("--list", action="store_true", help="列出 MCP Server 注册表")
    p_mcp.add_argument("--call", metavar="NAME", help="调用某个 MCP 工具（真连 Server）")
    p_mcp.add_argument("--arg", action="append", metavar="k=v", help="调用参数")
    p_mcp.set_defaults(func=_cmd_mcp)

    p_skills = sub.add_parser("skills", help="技能调试：已沉淀的技能清单")
    p_skills.add_argument("--list", action="store_true", help="列出全部技能与角色分配")
    p_skills.set_defaults(func=_cmd_skills)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
