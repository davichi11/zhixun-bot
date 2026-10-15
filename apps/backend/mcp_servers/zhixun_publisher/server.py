"""智讯助手 MCP Server —— 把"发布到各平台"做成标准 MCP 工具。

## 这个文件存在的意义

第三篇我们把发布能力写成了 `publish_draft` 工具，里面留了一个
`NotImplementedError("第 6 篇：通过 MCP 调用各平台 OpenAPI")`。

现在兑现这个承诺。但**关键不在于把那句异常换成真实调用**，
而在于把它做成一个**独立的 MCP Server** —— 进程边界。

这样做的好处：
- 平台的 token 与 SDK 只存在于 Server 进程里，主进程碰不到
- Server 可以单独部署（甚至放到内网另一台机器），主进程只负责连
- 平台 SDK 升级不会污染主应用的依赖树

> **MCP 的价值不只是"接工具"，而是"把能力挪到合适的进程边界里"。**

## 为什么用 stdio 传输

MCP 三种传输里，本项目选 stdio（本地子进程）：

| 传输 | 适用 | 本项目 |
|---|---|---|
| **stdio** | 同机子进程 | ✅ 默认（零运维、零端口） |
| streamable-http | 独立服务 | 生产环境（跨机） |
| SSE | 老式，已不推荐 | 不用 |

生产环境切 HTTP 只需改一行 `transport`，业务代码不动 —— 这正是协议标准化的红利。

## 三个工具的设计原则

平台类工具最容易犯的错是**给模型太多自由度**。所以这里的每个工具都有护栏：

1. `publish_draft`：**必须**传 `approved_by_human`，否则拒绝
2. `render_markdown` / `generate_cover`：纯本地计算，无副作用，随便调
3. 所有工具都**返回结构化 dict**，而不是裸字符串 —— 便于 Agent 解析

Run it:
    uv run python mcp_servers/zhixun_publisher/server.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

try:
    # ⚠️ mcp 2.x 把 FastMCP 改名为 MCPServer（1.x 是 fastmcp）
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError:  # mcp < 2
        from mcp.server.fastmcp import FastMCP as MCPServer
except ImportError as exc:  # pragma: no cover
    sys.exit(f"需要先安装 mcp：pip install 'mcp>=2.1.0,<3.0.0'（{exc}）")


# ------------------------------------------------------------------ 平台配置

SUPPORTED_PLATFORMS = ("wechat", "zhihu", "twitter")

# 各平台的字数上限（超出会被截断并告警）
PLATFORM_LIMITS = {
    "wechat": 20_000,
    "zhihu": 30_000,
    "twitter": 280,
}

# 发布记录落在这里，便于人工复核与回滚
LOG_DIR = Path(os.getenv("ZHIXUN_PUBLISH_LOG", Path(__file__).parent / "_logs"))

mcp = MCPServer("zhixun-publisher")


# ------------------------------------------------------------------ 工具一：排版


@mcp.tool()
def render_markdown(markdown: str, platform: str = "wechat") -> dict[str, Any]:
    """把 Markdown 转成目标平台的排版格式。

    这是纯本地计算，没有副作用，模型可以放心反复调用。

    Args:
        markdown: 文章正文（Markdown）
        platform: wechat / zhihu / twitter

    Returns:
        {"ok": bool, "html": str, "word_count": int, "truncated": bool, "warnings": [...]}
    """
    if platform not in SUPPORTED_PLATFORMS:
        return {"ok": False, "error": f"不支持的平台：{platform}", "warnings": []}

    warnings: list[str] = []
    limit = PLATFORM_LIMITS[platform]
    body = markdown or ""

    if len(body) > limit:
        warnings.append(f"正文 {len(body)} 字符超过{platform}上限 {limit}，已截断")
        body = body[:limit]

    if platform == "twitter":
        html = _md_to_plain(body)
    else:
        html = _md_to_html(body)

    return {
        "ok": True,
        "platform": platform,
        "html": html,
        "word_count": len(body),
        "truncated": len(markdown or "") > limit,
        "warnings": warnings,
    }


# ------------------------------------------------------------------ 工具二：封面


@mcp.tool()
def generate_cover(title: str, width: int = 900) -> dict[str, Any]:
    """生成文章封面图（占位实现：返回 SVG 文本）。

    真实项目里这里应该调 Pillow 或图床 API。
    这里刻意不引依赖 —— **演示 MCP 协议本身，不演示图形库**。

    Args:
        title: 文章标题
        width: 封面宽度（默认 900，公众号推荐尺寸）

    Returns:
        {"ok": bool, "svg": str, "path": str | None}
    """
    safe = re.sub(r"[<>&\"']", "", (title or "未命名"))[:40]
    height = int(width * 0.425)  # 公众号封面比例 2.35:1

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        f'<rect width="{width}" height="{height}" fill="#1a1a2e"/>'
        f'<text x="50%" y="52%" fill="#ffffff" font-size="{width // 18}" '
        f'font-family="sans-serif" text-anchor="middle">{safe}</text>'
        f"</svg>"
    )
    return {"ok": True, "svg": svg, "path": None, "width": width, "height": height}


# ------------------------------------------------------------------ 工具三：发布


@mcp.tool()
def publish_draft(
    platform: str,
    title: str,
    content: str,
    approved_by_human: bool = False,
) -> dict[str, Any]:
    """把审核通过的稿件发布到指定平台。

    安全约束（与第三篇 publish_draft 保持一致）：
    - approved_by_human 必须为 True，否则拒绝
    - platform 必须在白名单内
    - 正文不能过短（防空稿）

    Args:
        platform: wechat / zhihu / twitter
        title: 文章标题
        content: 正文（Markdown）
        approved_by_human: 人工审批标记

    Returns:
        {"ok": bool, "platform": str, "draft_id": str | None, "reason": str}
    """
    if platform not in SUPPORTED_PLATFORMS:
        return {"ok": False, "platform": platform, "reason": f"不支持的平台：{platform}"}

    if not approved_by_human:
        return {
            "ok": False,
            "platform": platform,
            "reason": "缺少人工审批标记，已拦截（approved_by_human 必须为 True）",
        }

    if len((content or "").strip()) < 50:
        return {"ok": False, "platform": platform, "reason": "正文过短，疑似空稿"}

    # TODO: 替换为真实的平台 OpenAPI 调用
    draft_id = f"{platform}-{int(time.time())}"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "draft_id": draft_id,
        "platform": platform,
        "title": title,
        "chars": len(content),
        "published_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (LOG_DIR / f"{draft_id}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"ok": True, "platform": platform, "draft_id": draft_id, "reason": ""}


# ------------------------------------------------------------------ 内部工具


def _md_to_html(text: str) -> str:
    """极简 Markdown → HTML（只处理标题/加粗/列表/代码块）。"""
    out: list[str] = []
    in_code = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            out.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(_esc(line))
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            continue
        if line.strip().startswith(("- ", "* ")):
            out.append(f"<li>{_inline(line.strip()[2:])}</li>")
            continue
        if not line.strip():
            out.append("")
            continue
        out.append(f"<p>{_inline(line)}</p>")
    return "\n".join(out)


def _md_to_plain(text: str) -> str:
    """Markdown → 纯文本（用于 twitter 这类无格式平台）。"""
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"^[-*]\s+", "• ", text, flags=re.MULTILINE)
    return text


def _inline(text: str) -> str:
    return _esc(re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text))


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


# ------------------------------------------------------------------ 入口

if __name__ == "__main__":
    # stdio 传输：日志必须走 stderr，否则会污染 MCP 的 stdout 协议流
    print("启动 zhixun-publisher MCP Server（stdio）…", file=sys.stderr)
    mcp.run(transport="stdio")
