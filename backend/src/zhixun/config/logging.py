"""结构化日志（见第一篇 5.3 节）。

规范：
- 统一输出 JSON，方便 ELK / Loki 收集
- 每次 Agent 调用必须带 `agent_name` / `session_id` / `request_id`
- **禁止打印完整 prompt 与模型输出**（成本 + 隐私双重风险）
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from zhixun.config.settings import settings

_configured = False


def configure_logging() -> None:
    """初始化日志（幂等，可在 FastAPI lifespan 里安全重复调用）。"""
    global _configured
    if _configured:
        return

    level = getattr(logging, settings.log_level)

    # 开发态用彩色 console，生产态用纯 JSON
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if settings.is_dev:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    else:
        processors.append(structlog.processors.JSONRenderer(ensure_ascii=False))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    _configured = True


def get_logger(name: str = "zhixun") -> structlog.stdlib.BoundLogger:
    """获取一个绑定名称的 logger。"""
    configure_logging()
    return structlog.get_logger(name)  # type: ignore[no-any-return]


__all__ = ["configure_logging", "get_logger"]
