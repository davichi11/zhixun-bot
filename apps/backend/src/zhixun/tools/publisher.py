"""发布工具 —— 把定稿推送到公众号 / 知乎等平台。

⚠️ 这是全项目**唯一的写操作工具**，也是 Harness「机械强制」的重点看护对象（第 7 篇）：
- 必须有 `approved_by_human=True` 才允许真正调用（人环结合）
- 必须记录审计日志：谁、什么时候、把什么内容发到了哪里

第 1 篇：定义契约并强制校验人工审批标记。
第 6 篇：改为通过 MCP 接入（把发布能力做成标准 MCP 工具）。
第 7 篇：叠加护栏中间件。
"""

from __future__ import annotations

from agno.tools import tool

from zhixun.config.logging import get_logger

logger = get_logger(__name__)

SUPPORTED_PLATFORMS = ("wechat", "zhihu", "twitter")


@tool(
    name="publish_draft",
    description=(
        "把审核通过的稿件发布到指定平台。"
        "出于安全考虑，approved_by_human 必须为 True 才会真正执行发布。"
    ),
)
def publish_draft(
    platform: str,
    title: str,
    content: str,
    approved_by_human: bool = False,
) -> dict[str, object]:
    """发布稿件到目标平台。

    Returns:
        {"ok": bool, "platform": str, "reason": str}
    """
    if platform not in SUPPORTED_PLATFORMS:
        return {"ok": False, "platform": platform, "reason": f"不支持的平台：{platform}"}

    # ---- Harness 机械强制：未获人工批准，物理拦截（不是靠提示词劝说）----
    if not approved_by_human:
        logger.warning("publish.blocked", platform=platform, title=title)
        return {
            "ok": False,
            "platform": platform,
            "reason": "缺少人工审批标记，已拦截。请先在工作台完成审校。",
        }

    logger.info("publish.start", platform=platform, title=title, chars=len(content))
    # TODO(第 6 篇): 通过 MCP 调用各平台 OpenAPI
    raise NotImplementedError("第 6 篇实现：接入各平台发布 API（或 MCP 工具）")


PUBLISHER_TOOLS = [publish_draft]
