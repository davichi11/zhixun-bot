"""带退避重试的 HTTP 客户端 —— 所有联网工具的唯一出口。

## 为什么不让每个工具自己写 httpx 调用？

因为**重试策略应该是统一的**。如果让每个工具自己写：

- GitHub 工具重试 2 次、网页抓取重试 5 次、搜索不重试 —— 没人说得清为什么
- 有人用 `time.sleep(1)` 硬睡，有人用指数退避，有人忘了加抖动（→ 惊群）
- 想加一个"熔断"能力，得改 8 个地方

所以本项目规定：**工具里禁止直接 `httpx.get`，一律走 `request_json` / `request_text`。**

## 退避曲线

第 n 次重试等待：`base_delay * 2^(n-1)`，再叠加 **0-100% 的随机抖动**。

```
attempt 1 fail → 等 0.5~1.0s
attempt 2 fail → 等 1.0~2.0s
attempt 3 fail → 等 2.0~4.0s
```

抖动（jitter）不是可选项。没有抖动的话，一批并行任务会在同一毫秒一起重试，
把刚缓过来的服务再打挂一次 —— 这就是"惊群效应"。

服务端如果回了 `Retry-After`，**优先听它的**：人家明确说了等多久，你比它聪明是没道理的。
"""

from __future__ import annotations

import random
import time
from typing import Any, Final

import httpx

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings
from zhixun.tools.errors import FatalToolError, RetryableToolError, classify_status

logger = get_logger(__name__)

# httpx 自身抛出的、值得重试的网络异常
_NETWORK_ERRORS: Final[tuple[type[BaseException], ...]] = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)


def _sleep_for(attempt: int, base_delay: float) -> float:
    """第 attempt 次重试前的等待时长（attempt 从 1 开始）。"""
    backoff = base_delay * (2 ** (attempt - 1))
    return backoff * (1 + random.random())  # 0~100% 抖动


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """读取服务端的 Retry-After 头（可能是秒数，也可能是 HTTP 日期）。"""
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        # HTTP 日期格式，解析成本高、收益低，直接走自己的退避曲线
        return None


def request_json(
    url: str,
    *,
    tool: str = "",
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    attempts: int | None = None,
    timeout: float | None = None,
    base_delay: float | None = None,
) -> dict[str, Any]:
    """GET 一个 JSON 接口，按需重试。

    Raises:
        RetryableToolError: 重试次数耗尽后仍失败
        FatalToolError: 遇到不可重试的状态码（401 / 404 / 422 …）
    """
    attempts = attempts or settings.tool_max_attempts
    timeout = timeout or settings.tool_timeout_seconds
    base_delay = base_delay or settings.tool_retry_base_delay
    tool = tool or url

    last_error: RetryableToolError | None = None

    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, params=params, headers=headers)

            # 2xx 直接返回
            if resp.is_success:
                if attempt > 1:
                    logger.info("tool.retry_ok", tool=tool, attempt=attempt)
                return resp.json()

            exc_type = classify_status(resp.status_code, tool=tool, url=url)
            detail = f"HTTP {resp.status_code}"
            if exc_type is FatalToolError:
                # 不可重试：立刻抛，别浪费预算
                logger.warning("tool.fatal", tool=tool, status=resp.status_code, url=url)
                raise FatalToolError(
                    f"{tool} 请求失败（不可重试）",
                    tool=tool,
                    detail=detail,
                )

            last_error = RetryableToolError(
                f"{tool} 请求失败（将重试）",
                tool=tool,
                detail=detail,
                retry_after=_retry_after_seconds(resp),
            )

        except _NETWORK_ERRORS as exc:
            last_error = RetryableToolError(
                f"{tool} 网络异常（将重试）",
                tool=tool,
                detail=f"{type(exc).__name__}: {exc}",
            )

        # ---- 到这里说明本次失败且可重试 ----
        if attempt >= attempts:
            break
        wait = last_error.retry_after if last_error and last_error.retry_after else _sleep_for(attempt, base_delay)
        logger.warning(
            "tool.retry",
            tool=tool,
            attempt=attempt,
            max_attempts=attempts,
            wait=round(wait, 2),
            detail=last_error.detail if last_error else "",
        )
        time.sleep(wait)

    assert last_error is not None  # 逻辑上不可能为 None（循环里必然赋值）
    logger.error("tool.gave_up", tool=tool, attempts=attempts, detail=last_error.detail)
    raise last_error


def request_text(
    url: str,
    *,
    tool: str = "",
    headers: dict[str, str] | None = None,
    attempts: int | None = None,
    timeout: float | None = None,
) -> str:
    """GET 一个纯文本接口（如 Jina Reader），按需重试。"""
    attempts = attempts or settings.tool_max_attempts
    timeout = timeout or settings.tool_timeout_seconds
    tool = tool or url

    last_error: RetryableToolError | None = None

    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=headers)

            if resp.is_success:
                if attempt > 1:
                    logger.info("tool.retry_ok", tool=tool, attempt=attempt)
                return resp.text

            exc_type = classify_status(resp.status_code, tool=tool, url=url)
            if exc_type is FatalToolError:
                logger.warning("tool.fatal", tool=tool, status=resp.status_code)
                raise FatalToolError(
                    f"{tool} 请求失败（不可重试）",
                    tool=tool,
                    detail=f"HTTP {resp.status_code}",
                )
            last_error = RetryableToolError(
                f"{tool} 请求失败（将重试）",
                tool=tool,
                detail=f"HTTP {resp.status_code}",
                retry_after=_retry_after_seconds(resp),
            )

        except _NETWORK_ERRORS as exc:
            last_error = RetryableToolError(
                f"{tool} 网络异常（将重试）",
                tool=tool,
                detail=f"{type(exc).__name__}: {exc}",
            )

        if attempt >= attempts:
            break
        wait = last_error.retry_after if last_error and last_error.retry_after else _sleep_for(attempt, settings.tool_retry_base_delay)
        logger.warning("tool.retry", tool=tool, attempt=attempt, wait=round(wait, 2))
        time.sleep(wait)

    assert last_error is not None
    logger.error("tool.gave_up", tool=tool, attempts=attempts, detail=last_error.detail)
    raise last_error
