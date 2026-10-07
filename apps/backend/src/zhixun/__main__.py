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
"""

from __future__ import annotations

import argparse
import asyncio

from zhixun.config.logging import configure_logging, get_logger
from zhixun.config.settings import settings

logger = get_logger("zhixun.cli")


def _cmd_run(args: argparse.Namespace) -> int:
    from zhixun.workflows import run_weekly_report

    state = asyncio.run(run_weekly_report(dry_run=args.dry_run))
    logger.info("cli.run_done", run_id=state.run_id, dry_run=args.dry_run)
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


def main() -> int:
    configure_logging()

    parser = argparse.ArgumentParser(prog="zhixun", description=f"{settings.app_name} CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="跑一次周报流水线")
    p_run.add_argument("--dry-run", action="store_true", help="干跑，不真正发布")
    p_run.set_defaults(func=_cmd_run)

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

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
