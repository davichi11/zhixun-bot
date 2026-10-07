"""发布工具 —— 把定稿推送到公众号 / 知乎等平台。

## 全项目唯一的写操作工具

前面三个工具（采集 / 搜索 / 抓取）最坏的结果是"白跑一趟"。
这个工具最坏的结果是**把没审过的稿子发到了你的公众号上**。

所以它值得被区别对待。这里叠加了**四道独立的闸门**：

| 闸门 | 机制 | 拦什么 |
|---|---|---|
| ① 框架级确认 | `requires_confirmation=True` | Agno 3.x 原生：调用前挂起，等人工确认 |
| ② 业务级审批 | `approved_by_human` 参数 | 即使有人绕过了框架，函数入口还有一道 |
| ③ 平台白名单 | `SUPPORTED_PLATFORMS` | 模型传 `platform="twitter_x"` 直接拒绝 |
| ④ 内容体检 | 长度 + 标题校验 | 空稿 / 超长稿不允许流出 |

**为什么要四道，而不是一道做扎实？**

因为它们的失效模式不同。① 可能被绕过（比如某个 SDK 版本不触发确认流程）；
② 可能被调用方强行传 `True`；③ 可能被"加个平台"的需求稀释；④ 可能被疏忽。

四道闸门**同时失效的概率**远低于任何单独一道 —— 这就是"纵深防御"。
Harness 的思路从来不是"造一道谁也翻不过的墙"，而是**让错误在抵达终点前被拦住多次**。

## 一个容易忽略的细节：返回值不泄露内容

注意看成功分支返回的是 `{"ok": True, "platform": ..., "chars": ...}`。
**它不回显 content** —— 因为写操作的返回值会被 Agent 带进上下文，
把整篇稿子再塞回去一遍纯属浪费 token，而且会让模型产生"我是不是该再发一次"的错觉。
"""

from __future__ import annotations

from typing import Any, Final

from agno.tools import tool

from zhixun.config.logging import get_logger
from zhixun.tools.errors import FatalToolError
from zhixun.tools.guards import audit_tool_call, clamp_int

logger = get_logger(__name__)

SUPPORTED_PLATFORMS: Final[tuple[str, ...]] = ("wechat", "zhihu", "twitter")
MIN_CONTENT_CHARS: Final[int] = 50
MAX_CONTENT_CHARS: Final[int] = 60_000


@tool(
    name="publish_draft",
    description=(
        "把审核通过的稿件发布到指定平台。"
        "出于安全考虑，approved_by_human 必须为 True 才会真正执行发布。"
    ),
    pre_hook=audit_tool_call,
    requires_confirmation=True,  # ① 框架级：调用前挂起，等人工确认
)
def publish_draft(
    platform: str,
    title: str,
    content: str,
    approved_by_human: bool = False,
) -> dict[str, Any]:
    """发布稿件到目标平台。

    Returns:
        {"ok": bool, "platform": str, "reason": str}

    Raises:
        FatalToolError: 平台不在白名单内（不可重试）
    """
    # ---- 闸门③：平台白名单 ----
    if platform not in SUPPORTED_PLATFORMS:
        raise FatalToolError(
            f"不支持的平台：{platform}",
            tool="publish_draft",
            detail=f"可选平台 {list(SUPPORTED_PLATFORMS)}",
        )

    # ---- 闸门②：人工审批标记（机械强制，不靠提示词劝说）----
    if not approved_by_human:
        logger.warning("publish.blocked_no_approval", platform=platform, title=title)
        return {
            "ok": False,
            "platform": platform,
            "reason": "缺少人工审批标记，已拦截。请先在工作台完成审校。",
        }

    # ---- 闸门④：内容体检 ----
    chars = clamp_int(len(content or ""), lo=0, hi=MAX_CONTENT_CHARS, name="content_chars")
    if chars < MIN_CONTENT_CHARS:
        logger.warning("publish.blocked_too_short", platform=platform, chars=chars)
        return {"ok": False, "platform": platform, "reason": f"内容过短（{chars} 字符），疑似空稿"}

    if not (title or "").strip():
        return {"ok": False, "platform": platform, "reason": "标题为空"}

    logger.info("publish.start", platform=platform, title=title, chars=chars)
    # TODO(第 6 篇): 通过 MCP 调用各平台 OpenAPI
    raise NotImplementedError("第 6 篇实现：接入各平台发布 API（或 MCP 工具）")


# `@tool` 装饰器在 Agno 3.0.9 上不接受 `has_side_effects` 参数（见装饰器的 VALID_KWARGS），
# 但这个标记对上层很有价值 —— 它让"哪些工具会改变外部世界"变成可查询的元数据。
# 所以建完之后补一句。第 7 篇的护栏中间件会读这个标记来决定要不要加确认流程。
publish_draft.has_side_effects = True


PUBLISHER_TOOLS = [publish_draft]
