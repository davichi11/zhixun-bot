"""智讯助手 · Agno 后端服务。

模块分层（依赖方向自上而下，禁止反向依赖）：

    api / scheduler        ← 最外层：HTTP 与定时触发
        ↓
    workflows              ← 业务主干：把一切编排成流水线
        ↓
    agents / tools         ← 能力层：Agent 定义与工具
        ↓
    knowledge              ← 数据层：记忆（memory） + 检索（rag）
        ↓
    db / config            ← 基础设施：数据库与配置

横切：harness（驾驭层）—— 依赖业务"接口"，不被业务依赖。

详见《Agno实战系列（第一篇）：项目介绍与整体架构》4.2 节。
"""

__version__ = "0.1.0"
