"""MCP 接入层 —— 把外部能力标准化地挂进 Agent 的工具表。

## 这一层存在的三个理由

**① 可选依赖降级。** `mcp` / `fastmcp` 都不是必需依赖。
装了就能用 MCP，不装就走内置工具 —— 主进程不能因为"想接个外部服务"而起不来。

**② 能力注册集中。** 业务代码只调 `load_publisher_tools()`，
不关心 MCP 怎么连、连不上怎么办。

**③ 护栏不因接入方式而放松。** 无论能力来自本地 `@tool` 还是 MCP Server，
**审批闸门都必须过**。这一点由 `tools/publisher.py` 保证，与传输方式解耦。

## MCP 给了什么

第三篇我们自己写了 `publish_draft`。那为什么还要 MCP？

| | 自研工具 | MCP 工具 |
|---|---|---|
| 部署 | 主进程内 | **独立进程 / 独立机器** |
| 平台 SDK 依赖 | 污染主依赖树 | **隔离在 Server 侧** |
| 接入新平台 | 改一行业务代码 | **改配置就行** |
| 跨语言 | 做不到 | 天然支持 |

> **MCP 的价值不只是"接工具"，而是"把能力挪到合适的进程边界里"。**

## 一个必须知道的安全设计（Agno 内置）

`MCPTools(command=...)` 的 `command` 是**整条命令字符串**，不是 `command + args`：

```python
# ❌ 没有 args 参数，传了会报 TypeError
MCPTools(command="python", args=["server.py"])

# ✅ 整条命令，Agno 内部用 shlex.split 拆
MCPTools(command=f"{sys.executable} mcp_servers/zhixun_publisher/server.py")
```

Agno 的 `prepare_command()` 对这条命令做了两层防护：

1. **禁止 shell 元字符** `& | ; $ ( )` 与反引号
2. **可执行文件白名单**：`python / python3 / uv / uvx / node / npx / docker …`
   （绝对路径需要文件真实存在）

所以 MCP Server 的启动命令**不能来自模型或用户输入** ——
它必须来自配置。这条我们在 `settings` 里写死，不给外部注入的入口。
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from typing import Any

from zhixun.config.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "MCPServerSpec",
    "mcp_available",
    "describe_mcp_servers",
    "load_mcp_tools",
    "load_publisher_tools",
]


# ------------------------------------------------------------------ 可用性探测


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def mcp_available() -> bool:
    """客户端与协议库是否齐备。

    ⚠️ 实测：**Agno 的 MCP 客户端依赖 `fastmcp`，不只是 `mcp`**。
    只装 `mcp` 时，`_build_fastmcp_client()` 会抛
    `ImportError: fastmcp not installed`。
    所以这里同时探测两个。
    """
    return _has("mcp") and _has("fastmcp")


@dataclass(slots=True)
class MCPServerSpec:
    """一个 MCP Server 的连接描述。

    Attributes:
        name: 逻辑名（用于日志与工具名前缀）
        command: **完整命令字符串**（不是 command + args）
        description: 说明，会写进 CLI 展示
        enabled: 是否启用（配置里可以关掉）
    """

    name: str
    command: str
    description: str = ""
    enabled: bool = True


# ------------------------------------------------------------------ 内置 Server 注册表


def _server_registry() -> dict[str, MCPServerSpec]:
    """从配置构造 Server 列表。

    ⚠️ 命令**只来自配置**，不接受运行时注入 ——
    因为 MCP Server 的启动命令等于"在你机器上执行任意进程"，
    这和第三篇 `assert_url_allowed` 防的是同一类风险。
    """
    from zhixun.config.settings import BACKEND_ROOT, settings

    return {
        "publisher": MCPServerSpec(
            name="zhixun-publisher",
            command=f"{sys.executable} {BACKEND_ROOT / settings.mcp_publisher_server}",
            description="发布能力：排版 / 封面 / 发布到各平台",
            enabled=settings.mcp_publisher_enabled,
        )
    }


def describe_mcp_servers() -> list[dict[str, Any]]:
    """给 CLI 展示用（不连接）。"""
    reg = _server_registry()
    available = mcp_available()
    return [
        {
            "name": spec.name,
            "enabled": spec.enabled,
            "ready": available and spec.enabled,
            "description": spec.description,
            "command": spec.command,
            "hint": "" if available else "pip install 'mcp>=2.1.0,<3.0.0' fastmcp",
        }
        for spec in reg.values()
    ]


# ------------------------------------------------------------------ 加载


@dataclass(slots=True)
class MCPLoadResult:
    """加载结果 —— 把"接上了几个 / 少了什么"显式暴露。"""

    tools: list[Any] = field(default_factory=list)
    connected: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    unavailable_reason: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.tools)


async def load_mcp_tools(*, names: list[str] | None = None) -> MCPLoadResult:
    """连接 MCP Server 并把它的工具加载成 Agno Function。

    Args:
        names: 要加载的 Server 名；不传则加载全部启用的

    Returns:
        `MCPLoadResult`。**失败不抛异常** —— MCP 是可选能力，
        接不上就降级回内置工具，而不是让整个服务起不来。
    """
    result = MCPLoadResult()

    if not mcp_available():
        result.unavailable_reason = "mcp/fastmcp 未安装，已降级为内置工具"
        logger.warning("mcp.unavailable", hint="pip install 'mcp>=2.1.0,<3.0.0' fastmcp")
        return result

    from agno.tools.mcp import MCPTools  # 延迟 import：装了就用，没装也不影响导入

    reg = _server_registry()
    wanted = names if names is not None else list(reg)

    for key in wanted:
        spec = reg.get(key)
        if spec is None:
            result.failed[key] = "未注册的 MCP Server"
            continue
        if not spec.enabled:
            result.failed[key] = "已通过配置禁用"
            continue

        try:
            tools = MCPTools(
                command=spec.command,
                name=spec.name,
                timeout_seconds=30,
                # 工具名前缀，避免多个 Server 的同名工具撞车
                tool_name_prefix=f"{spec.name}_",
            )
            await tools.connect()

            # ⚠️ **实测坑**：`connect()` 在 Server 启动失败时**不一定抛异常** ——
            # 它可能只是安静地返回 0 个工具。所以必须显式校验工具数，
            # 否则日志会打 "connected" 而实际上一个工具都没有。
            found = len(getattr(tools, "functions", {}) or {})
            if found == 0:
                raise RuntimeError("连接成功但未发现任何工具（Server 可能启动失败或协议不兼容）")

            result.tools.append(tools)
            result.connected.append(spec.name)
            logger.info("mcp.connected", server=spec.name, tool_count=found)
        except Exception as exc:  # noqa: BLE001 - 外部进程失败千奇百怪，一律降级
            result.failed[key] = f"{type(exc).__name__}: {exc}"
            logger.warning("mcp.connect_failed", server=spec.name, error=str(exc))

    return result


async def load_publisher_tools() -> MCPLoadResult:
    """加载发布能力（MCP 优先）。

    这是 `step_publish` 与 `publisher.py` 的统一入口：
    **它不关心能力从哪来** —— MCP 还是内置实现，对调用方完全一样。
    """
    return await load_mcp_tools(names=["publisher"])
