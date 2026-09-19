"""命令行入口。

用法：
    uv run zhixun run --dry-run            # 干跑一次周报流水线
    uv run zhixun serve                    # 启动 API 服务

    # ---- 第二篇新增：Agent 调试三件套 ----
    uv run zhixun agents --list            # 列出全部 Agent、模型档位与提示词版本
    uv run zhixun agents --audit           # 提示词治理自检（建议挂进 CI）
    uv run zhixun agents --show-prompt analyst   # 打印渲染后的完整提示词（无需 API key）
    uv run zhixun agents --role collector --message "抓一下本周 AI 开源项目"
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

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
