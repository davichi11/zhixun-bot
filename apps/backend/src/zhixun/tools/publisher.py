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

import asyncio
import json
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

    # ---- 第 6 篇：委托给 MCP Server 执行真实发布 ----
    # ⚠️ 关键设计：**四道闸门留在主进程，MCP Server 侧还有一套同构的闸门**。
    # 这样做的理由是纵深防御（第三篇的思路）：
    # 主进程可能被改代码绕过，但 Server 是独立进程、独立部署的边界；
    # 任何一侧单独失效，另一侧仍会拦截。
    result = _publish_via_mcp(platform=platform, title=title, content=content)
    if result is None:
        # MCP 不可用时的降级：明确告诉调用方"没发出去"，而不是假装成功
        logger.error("publish.mcp_unavailable", platform=platform)
        return {
            "ok": False,
            "platform": platform,
            "reason": "MCP 发布通道不可用（未安装依赖或 Server 启动失败），已阻止发布",
        }
    return result


def _publish_via_mcp(*, platform: str, title: str, content: str) -> dict[str, Any] | None:
    """通过 MCP 调用真正的发布能力。

    ⚠️ **这里必须用独立线程跑事件循环**，不能直接 `asyncio.run()`：
    这个工具是**同步函数**，但它通常在 Workflow 的异步步骤里被调用，
    此时事件循环已经在运行 —— `asyncio.run()` 会抛
    `RuntimeError: asyncio.run() cannot be called from a running event loop`。

    这是一个"同步签名 + 异步实现"函数必须处理的场景。

    Returns:
        Server 返回的结果；连接不可用时返回 `None`
    """
    import asyncio
    import concurrent.futures

    from zhixun.mcp import load_publisher_tools

    async def _call() -> dict[str, Any] | None:
        loaded = await load_publisher_tools()
        if not loaded.ok:
            logger.warning("publish.mcp_load_failed", failed=loaded.failed)
            return None

        for toolkit in loaded.tools:
            fns = getattr(toolkit, "functions", {}) or {}
            target = next((n for n in fns if n.endswith("publish_draft")), None)
            if target is None:
                continue
            try:
                raw = await fns[target].entrypoint(
                    platform=platform,
                    title=title,
                    content=content,
                    approved_by_human=True,  # 主进程已校验；Server 侧仍会再校验一次
                )
                return _extract_mcp_payload(raw)
            finally:
                await toolkit.close()
        return None

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _call()).result(timeout=60)
    except Exception as exc:  # noqa: BLE001 - 外部进程异常一律转为"没发出去"
        logger.warning("publish.mcp_call_failed", error=str(exc))
        return None


def _extract_mcp_payload(raw: Any) -> dict[str, Any]:
    """从 MCP 返回值里取出结构化 payload。

    MCP 工具返回的是 `content=<json 字符串>` + `metadata.structured_content`。
    优先用后者（框架已经解析过），退回前者手工解析。
    """
    metadata = getattr(raw, "metadata", None) or {}
    structured = metadata.get("structured_content")
    if isinstance(structured, dict):
        return structured

    content = getattr(raw, "content", None)
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {"ok": bool(getattr(raw, "success", False)), "reason": "无法解析 MCP 返回值"}


# `@tool` 装饰器在 Agno 3.0.9 上不接受 `has_side_effects` 参数（见装饰器的 VALID_KWARGS），
# 但这个标记对上层很有价值 —— 它让"哪些工具会改变外部世界"变成可查询的元数据。
# 所以建完之后补一句。第 7 篇的护栏中间件会读这个标记来决定要不要加确认流程。
publish_draft.has_side_effects = True


PUBLISHER_TOOLS = [publish_draft]
