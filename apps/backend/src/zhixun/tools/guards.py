"""机械强制（Mechanical Enforcement）—— 把约束从"请求"降级为"不许"。

## 一句话说清这个模块的存在意义

> **提示词是"请"，护栏是"不许"。**

你可以在一份提示词里写十遍"请不要传入超过 100 条的上限"，
但只要模型某一次心情好，传了 `limit=99999`，你的 API 就会被它一次性打爆。
—— 这不是模型的错，是你把**本该由代码保证的事情，交给了概率**。

本模块做的事情只有一个：**不依赖任何人的自觉，把边界写死在代码里。**

## 三层护栏

| 层 | 机制 | 拦什么 |
|---|---|---|
| ① 入口钳制 | `clamp_int` / `clamp_text` | 模型传了越界参数 —— **直接夹回合法区间**，不报错、不中断 |
| ② 硬拦截 | `assert_url_allowed` | 危险请求（内网地址、非 http 协议）—— **直接抛异常** |
| ③ 配额 | `pre_hook` + 调用预算 | 工具被反复调用（死循环）—— **超预算即熔断** |

注意 ① 和 ② 的区别：**能自动修正的就修正，不能修正的才拦截。**
`limit=99999` 钳到 100 是完全安全的（用户意图明确），所以不该报错；
而访问 `http://169.254.169.254/`（云元数据地址）没有任何合法意图，必须拦。

## 为什么钳制比报错好

如果模型传 `limit=99999` 时你返回一个错误，模型大概率会"再试一次"，
形成一个失败的循环 —— 每一次都要烧 token。**钳制是静默的、一次性的、必然成功的。**

这正是 Harness 那条原则的落地：**能失败的环节应该显式失败，但能自动纠正的环节不要失败。**
"""

from __future__ import annotations

import ipaddress
import re
from contextvars import ContextVar
from typing import Any, Callable, Final
from urllib.parse import urlparse

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings
from zhixun.tools.errors import FatalToolError, ToolBudgetExceeded

logger = get_logger(__name__)

__all__ = [
    "TOOL_CALL_BUDGET",
    "assert_url_allowed",
    "audit_tool_call",
    "budget_remaining",
    "budget_snapshot",
    "clamp_int",
    "clamp_text",
    "redact_args",
    "reset_budget",
]

# ------------------------------------------------------------------ ① 入口钳制


def clamp_int(value: Any, *, lo: int, hi: int, name: str = "value") -> int:
    """把整数参数夹到 [lo, hi] 闭区间。

    模型传字符串、浮点、None 都能处理 —— **入口不做格式审判，只做边界保证**。

    Example:
        >>> clamp_int(99999, lo=1, hi=100, name="limit")
        100
        >>> clamp_int("10", lo=1, hi=100, name="limit")
        10
    """
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        logger.warning("guard.clamp_bad_type", name=name, value=repr(value), fallback=hi)
        return hi

    clamped = max(lo, min(ivalue, hi))
    if clamped != ivalue:
        logger.warning("guard.clamped", name=name, requested=ivalue, actual=clamped, lo=lo, hi=hi)
    return clamped


def clamp_text(text: str, *, max_chars: int, name: str = "text") -> str:
    """截断超长文本，并在末尾留下可识别的标记。

    为什么留标记？因为**被截断的上下文如果看起来"完整"，模型会误以为资料就这么多**。
    加一行显式说明，模型才知道"后面还有内容，我可能需要用别的方式拿"。
    """
    if len(text) <= max_chars:
        return text
    logger.info("guard.text_truncated", name=name, original=len(text), kept=max_chars)
    return text[:max_chars] + f"\n\n…（内容过长已截断，原长度 {len(text)} 字符）"


# ------------------------------------------------------------------ ② 硬拦截

# 云元数据地址：SSRF 攻击的首要目标（拿到它等于拿到云主机凭证）
_BLOCKED_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "169.254.169.254",  # AWS / 阿里云 / 腾讯云 元数据服务
        "metadata.google.internal",
        "metadata.azure.com",
    }
)
_ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})
# 私有网段：抓自己的内网服务不是这个产品的需求，一律拒绝
_PRIVATE_NETWORKS: Final[tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]] = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
)


def assert_url_allowed(url: str, *, tool: str = "", allow_private: bool = False) -> str:
    """校验 URL 是否允许访问，返回规范化后的 URL。

    拦三类东西：协议不是 http(s)、域名在黑名单、指向内网/本机地址。

    Raises:
        FatalToolError: 命中任意一条规则（不可重试 —— 重试一百次也一样危险）
    """
    raw = (url or "").strip()
    if not raw:
        raise FatalToolError("URL 为空", tool=tool, detail="调用方传入空 URL")

    parsed = urlparse(raw)

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise FatalToolError(
            f"不支持的协议：{parsed.scheme or '(空)'}",
            tool=tool,
            detail=f"只允许 {sorted(_ALLOWED_SCHEMES)}，收到 {raw!r}",
        )

    host = (parsed.hostname or "").lower()

    if host in _BLOCKED_HOSTS:
        logger.error("guard.blocked_metadata", tool=tool, host=host)
        raise FatalToolError("目标地址被安全策略禁止", tool=tool, detail=f"命中元数据地址黑名单：{host}")

    if not allow_private:
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None and any(ip in net for net in _PRIVATE_NETWORKS):
            logger.error("guard.blocked_private", tool=tool, host=host)
            raise FatalToolError("目标地址被安全策略禁止", tool=tool, detail=f"内网地址不允许抓取：{host}")

    return raw


# ------------------------------------------------------------------ ③ 调用配额

# 用 ContextVar 而不是全局计数器：并发跑多个 run 时，各自的预算互不干扰。
# 这是"每轮对话的资源上限"，不是"整个进程的限额"。
TOOL_CALL_BUDGET: ContextVar[int] = ContextVar("tool_call_budget", default=0)


def reset_budget(limit: int | None = None) -> None:
    """开启一轮新的工具调用预算（每次 Agent 运行前调用）。"""
    TOOL_CALL_BUDGET.set(limit if limit is not None else settings.tool_call_budget)


def budget_remaining() -> int:
    """当前剩余调用额度。"""
    return TOOL_CALL_BUDGET.get()


def budget_snapshot() -> dict[str, int]:
    """给 CLI / 监控面板看的额度快照。"""
    return {"remaining": TOOL_CALL_BUDGET.get(), "limit": settings.tool_call_budget}


# ------------------------------------------------------------------ 审计与 pre_hook

# 这两类参数不能进日志：一个是密钥，一个是用户原文
_SECRET_KEYS: Final[frozenset[str]] = frozenset(
    {"api_key", "token", "password", "secret", "authorization", "access_token"}
)


def redact_args(args: dict[str, Any] | None, *, keep: int = 120) -> dict[str, Any]:
    """脱敏参数，用于日志。

    - 密钥类字段 → `***`
    - 超长文本 → 只留前 `keep` 个字符
    """
    out: dict[str, Any] = {}
    for key, value in (args or {}).items():
        if key.lower() in _SECRET_KEYS:
            out[key] = "***"
        elif isinstance(value, str) and len(value) > keep:
            out[key] = value[:keep] + f"…(+{len(value) - keep})"
        else:
            out[key] = value
    return out


def audit_tool_call(fc: Any = None, agent: Any = None) -> None:
    """工具的 `pre_hook`：审计 + 额度熔断。

    挂到工具上之后，**每一次工具调用都会留下一条结构化日志，且消耗一次额度**。
    业务代码一行不用改 —— 这就是"横切关注点"该有的样子。

    Args:
        fc: Agno 注入的 `FunctionCall`（含 `function` 与 `arguments`）
        agent: Agno 注入的 Agent 实例（可选）

    Raises:
        AgentRunException: 额度耗尽时熔断本次工具调用
    """
    tool_name = getattr(getattr(fc, "function", None), "name", "?")
    args = redact_args(getattr(fc, "arguments", None))
    agent_name = getattr(agent, "name", "")

    remaining = TOOL_CALL_BUDGET.get()
    if remaining > 0:
        TOOL_CALL_BUDGET.set(remaining - 1)

    logger.info(
        "tool.call",
        tool=tool_name,
        agent=agent_name,
        args=args,
        budget_left=max(remaining - 1, 0),
    )

    if remaining <= 0:
        from agno.exceptions import AgentRunException

        logger.error("tool.budget_exceeded", tool=tool_name, agent=agent_name)
        # 抛出去 = 物理阻断本次调用，模型拿不到结果，只能换策略
        raise AgentRunException(
            f"工具调用额度已用尽（上限 {settings.tool_call_budget} 次），"
            f"不允许再调用 {tool_name}。请基于已有信息直接给出结论。"
        )


def attach_audit_hook(func: Any) -> Any:
    """给一个 Agno Function 挂上审计钩子（幂等）。

    第 7 篇会把这里升级成"按工具类型分发不同护栏"，
    现在先保持单一入口，避免过早抽象。
    """
    if getattr(func, "pre_hook", None) is not None:
        return func
    func.pre_hook = audit_tool_call
    return func


def make_counting_hook(counter: dict[str, int]) -> Callable[..., None]:
    """生成一个按工具名计数的钩子 —— 给测试与统计用。

    Example:
        >>> counts: dict[str, int] = {}
        >>> hook = make_counting_hook(counts)
    """

    def _hook(fc: Any = None) -> None:
        name = getattr(getattr(fc, "function", None), "name", "?")
        counter[name] = counter.get(name, 0) + 1

    return _hook


# 保留一个简单的 URL 规范化正则，供后续按域名做白名单时使用
_DOMAIN_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$", re.IGNORECASE)


def is_public_domain(host: str) -> bool:
    """粗略判断是不是一个正常的公网域名（用于抓取前的快速体检）。"""
    return bool(_DOMAIN_RE.match(host or ""))
