"""HTTP API 层 —— 系统最外层（见第一篇 4.2 节 ⑦）。

它是唯一"能看见所有内部模块"的地方，但**内部模块之间不能互相耦合**：
- 路由只做：参数校验 → 调 service（知识层/流水线）→ 组装响应
- 禁止在路由里写业务逻辑
"""

from __future__ import annotations

from zhixun.api.routes import api_router

__all__ = ["api_router"]
