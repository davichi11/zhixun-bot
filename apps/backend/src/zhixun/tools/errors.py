"""工具错误分类 —— 决定「要不要重试」的唯一依据。

## 为什么错误要分类？

工具跑在生产环境里，失败是常态。但**不同的失败，处理方式完全不同**：

| 失败类型 | 例子 | 正确做法 |
|---|---|---|
| 暂时性 | 超时、502、429（限流） | **退避重试**，过一会就好 |
| 永久性 | 401（key 错了）、404（仓库改名了）、422（参数不合法） | **立刻放弃**，重试 100 次也是白搭 |
| 用户错误 | 模型传了个不存在的信源名 | 把错误**回灌给模型**，让它自己改参数 |

一个不带分类的重试逻辑会犯两种错误：
- 对 401 重试 3 次 → 白等 7 秒，还让日志里塞满无意义的告警
- 对 429 不重试 → 直接丢数据，采集员莫名其妙少了一批素材

所以本模块先把"错误"变成**有类型的一等公民**，重试策略只认类型，不认错误字符串。

## 约定

- `RetryableToolError`：可以重试，调用方负责退避
- `FatalToolError`：不可重试，立即上抛或返回降级值
- `ToolBudgetExceeded`：超过本轮调用额度（Harness「机械强制」会用到）
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "FatalToolError",
    "RetryableToolError",
    "ToolBudgetExceeded",
    "ToolError",
    "classify_status",
    "is_retryable",
]

# 值得重试的 HTTP 状态码：
# - 408 请求超时
# - 425 Too Early
# - 429 限流（Retry-After 会告诉我们等多久）
# - 5xx 服务端抖动（500/502/503/504 最常见）
RETRYABLE_STATUS: Final[frozenset[int]] = frozenset({408, 425, 429, 500, 502, 503, 504})

# 明确不可重试的：认证、权限、资源不存在、参数错误
FATAL_STATUS: Final[frozenset[int]] = frozenset({400, 401, 403, 404, 410, 422})


class ToolError(Exception):
    """工具异常基类。

    Attributes:
        tool: 出错的工具名（日志与归因都要用）
        detail: 给人看的一句话说明
    """

    def __init__(self, message: str, *, tool: str = "", detail: str = "") -> None:
        super().__init__(message)
        self.tool = tool
        self.detail = detail or message

    def as_dict(self) -> dict[str, object]:
        """转成可以塞进 Agent 上下文的结构（让模型知道发生了什么）。"""
        return {
            "error": type(self).__name__,
            "tool": self.tool,
            "retryable": isinstance(self, RetryableToolError),
            "detail": self.detail,
        }


class RetryableToolError(ToolError):
    """可重试错误：网络抖动、限流、服务端 5xx。"""

    def __init__(
        self,
        message: str,
        *,
        tool: str = "",
        detail: str = "",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, tool=tool, detail=detail)
        # 服务端明确告知的等待时长（秒），有就优先用它而不是自己的退避曲线
        self.retry_after = retry_after


class FatalToolError(ToolError):
    """不可重试错误：认证失败、资源不存在、参数非法。"""


class ToolBudgetExceeded(ToolError):
    """超过本轮工具调用预算（由 Harness 层在 pre_hook 里抛出）。"""


def classify_status(status_code: int, *, tool: str = "", url: str = "") -> type[ToolError]:
    """把 HTTP 状态码映射成异常类型。

    Example:
        >>> classify_status(429) is RetryableToolError
        True
        >>> classify_status(404) is FatalToolError
        True
    """
    if status_code in RETRYABLE_STATUS:
        return RetryableToolError
    if status_code in FATAL_STATUS:
        return FatalToolError
    # 未知状态码：4xx 视为致命（大概率是我们请求写错了），5xx 视为可重试
    return RetryableToolError if status_code >= 500 else FatalToolError


def is_retryable(exc: BaseException) -> bool:
    """判断一个异常是否值得重试。

    注意：这里**只认类型，不认字符串**。用 `"timeout" in str(exc)` 这种写法
    迟早会踩坑 —— 某个错误信息里恰好包含 "timeout" 就会被误重试。
    """
    return isinstance(exc, RetryableToolError)
