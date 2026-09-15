"""知识层 —— 记忆与 RAG 的统一入口（见第一篇 4.2 节 ④）。

对外只暴露 `unified_retriever`，内部结构对调用方不可见：

    knowledge/
    ├── memory/     # 业务记忆：已发布项目、去重、上下文压缩
    ├── rag/        # 检索增强：文章向量、混合检索
    └── unified_retriever.py  # 唯一对外接口

业务 Agent 只应该这样用：
    from zhixun.knowledge import get_retriever
    ctx = await get_retriever().retrieve("本周 AI 开源周报", need_style=True)
"""

from __future__ import annotations

from zhixun.knowledge.unified_retriever import (
    ContextProvider,
    KnowledgeContext,
    PublishedProject,
    StyleSample,
    UnifiedRetriever,
    get_retriever,
)

__all__ = [
    "ContextProvider",
    "KnowledgeContext",
    "PublishedProject",
    "StyleSample",
    "UnifiedRetriever",
    "get_retriever",
]
