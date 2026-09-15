"""驾驭层（Harness Engineering）—— 横切所有业务的工程化护栏。

三大支柱：
    ① context/   动态上下文工程（渐进式披露、按需卸载）
    ② guards/    机械强制（代码级拦截 + 反馈注入）
    ③ entropy/   熵管理（后台 GC Agent）

**依赖方向约定**：本层可以依赖任何业务模块的**接口**，
但业务模块**不得 import 本层的具体实现**（只依赖 `middlewares` 中的协议）。
这样将来整体替换 Harness 实现时，业务代码零改动。
"""

from __future__ import annotations

from zhixun.harness.middlewares import (
    HarnessChain,
    HarnessContext,
    Middleware,
    NoopMiddleware,
    build_default_chain,
)

__all__ = [
    "HarnessChain",
    "HarnessContext",
    "Middleware",
    "NoopMiddleware",
    "build_default_chain",
]
