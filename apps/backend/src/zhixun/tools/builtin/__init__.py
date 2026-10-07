"""Agno 内置工具包的适配层 —— 让"可选依赖"变成可控能力。

## 为什么值得单独一层

Agno 3.x 内置 20+ 工具包，但**几乎每个都拖着第三方 SDK**：

| 工具包 | 额外依赖 |
|---|---|
| `DuckDuckGoTools` | `ddgs` |
| `ExaTools` | `exa_py` |
| `ArxivTools` | `arxiv` |
| `TrafilaturaTools` | `trafilatura` |
| `HackerNewsTools` | 无 ✅ |
| `JinaReaderTools` | 无（走 httpx）✅ |
| `WebTools` | 无 ✅ |

直接 `from agno.tools.duckduckgo import DuckDuckGoTools` 写在模块顶部，
只要这台机器没装 `ddgs`，**整个服务都起不来** —— 一个可选能力拖垮了主进程。

所以这里用 `try/except ImportError` 把每个工具包包起来，
**缺依赖的进 `missing` 列表，有的进 `tools` 列表**，然后由调用方决定怎么办。

## 这一层的第二个价值：升级隔离

Agno 升级时，内置工具偶尔会改名或改签名。有这一层，
业务代码只改这里，不用全仓库搜替换。
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from typing import Any, Callable

from zhixun.config.logging import get_logger

logger = get_logger(__name__)

# 名称 → (构造函数, 需要的额外依赖说明)
# 依赖为 None 表示开箱可用
_BUILTIN_FACTORIES: dict[str, tuple[Callable[[], Any], str | None]] = {
    "hackernews": (lambda: _import("agno.tools.hackernews", "HackerNewsTools")(), None),
    "jina": (lambda: _import("agno.tools.jina", "JinaReaderTools")(), None),
    "webtools": (lambda: _import("agno.tools.webtools", "WebTools")(), None),
    "duckduckgo": (lambda: _import("agno.tools.duckduckgo", "DuckDuckGoTools")(), "ddgs"),
    "exa": (lambda: _import("agno.tools.exa", "ExaTools")(), "exa_py"),
    "arxiv": (lambda: _import("agno.tools.arxiv", "ArxivTools")(), "arxiv"),
}


def _import(module: str, attr: str) -> Any:
    """延迟 import 一个 Agno 内置工具类。"""
    mod = __import__(module, fromlist=[attr])
    return getattr(mod, attr)


@dataclass(slots=True)
class BuiltinLoadResult:
    """内置工具加载结果（把"少了什么"显式暴露出来）。"""

    tools: list[Any] = field(default_factory=list)
    missing: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.missing


def load_builtin_tools(names: list[str] | None = None) -> BuiltinLoadResult:
    """按名称加载 Agno 内置工具包。

    Args:
        names: 工具包名列表，如 `["hackernews", "jina"]`

    Returns:
        `BuiltinLoadResult`，含成功加载的工具与缺失依赖的说明。

    Notes:
        **缺依赖不会抛异常**，只会被记进 `missing`。
        调用方（`tools_for`）会把它打到日志，第 8 篇的评估脚本会读它做归因。
    """
    result = BuiltinLoadResult()

    for name in names or []:
        spec = _BUILTIN_FACTORIES.get(name)
        if spec is None:
            result.missing[name] = "未知的内置工具包名"
            logger.warning("builtin_tools.unknown", name=name, known=sorted(_BUILTIN_FACTORIES))
            continue

        factory, dep = spec
        try:
            result.tools.append(factory())
            logger.debug("builtin_tools.loaded", name=name, requires=dep)
        except ImportError as exc:
            hint = f"pip install {dep}" if dep else str(exc)
            result.missing[name] = hint
            logger.warning("builtin_tools.missing_dep", name=name, hint=hint)
        except Exception as exc:  # noqa: BLE001 - 内置工具的构造异常不该拖垮主流程
            result.missing[name] = f"{type(exc).__name__}: {exc}"
            logger.warning("builtin_tools.load_failed", name=name, error=str(exc))

    return result


def available_builtins() -> list[str]:
    """列出本机当前可用的内置工具包（给 CLI 展示）。

    实现上**先查依赖是否存在，再去构造** —— 否则每探一次可用性都会打一串
    "缺少依赖"的告警日志，把真正的告警淹掉。
    """
    available: list[str] = []
    for name, (_, dep) in _BUILTIN_FACTORIES.items():
        if dep is not None and importlib.util.find_spec(dep) is None:
            continue
        try:
            _BUILTIN_FACTORIES[name][0]()
        except Exception:  # noqa: BLE001 - 探测失败即视为不可用
            continue
        available.append(name)
    return available


def unavailable_builtins() -> dict[str, str]:
    """列出本机缺依赖的内置工具包 → 安装提示。

    这个函数的存在本身就是一种态度：**降级必须可见**。
    如果你不知道自己少了什么能力，那"优雅降级"就变成了"静默阉割"。
    """
    out: dict[str, str] = {}
    for name, (_, dep) in _BUILTIN_FACTORIES.items():
        if dep is not None and importlib.util.find_spec(dep) is None:
            out[name] = f"pip install {dep}"
    return out


__all__ = [
    "BuiltinLoadResult",
    "available_builtins",
    "load_builtin_tools",
    "unavailable_builtins",
]
