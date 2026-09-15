"""命令行入口。

用法：
    uv run zhixun run --dry-run     # 干跑一次周报流水线
    uv run zhixun serve             # 启动 API 服务
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

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
