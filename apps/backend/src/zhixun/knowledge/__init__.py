"""知识层 —— 记忆与 RAG 的统一入口（见第一篇 4.2 节 ④）。

对外只暴露 `unified_retriever`，内部结构对调用方不可见：

    knowledge/
    ├── memory/       # 业务记忆：已发布项目、两段式去重、渐进式披露
    ├── rag/          # 检索增强：分词/BM25、Embedding、向量库、混合检索
    ├── ingest.py     # 入库管道（Markdown 目录 → 切片 → 向量 → 索引）
    └── unified_retriever.py  # 唯一对外接口

业务 Agent 只应该这样用：

    from zhixun.knowledge import get_retriever

    # 1) 查"我该知道什么"
    ctx = await get_retriever().retrieve("本周 AI 开源周报", need_style=True)
    # 2) 按角色选披露档位渲染
    prompt_block = ctx.render(detail_level="full")      # 写手
    # 3) 过滤重复
    fresh, dropped = await get_retriever().filter_duplicates(candidates)
"""

from __future__ import annotations

from zhixun.knowledge.unified_retriever import (
    DETAIL_LIMITS,
    ContextProvider,
    DetailLevel,
    KnowledgeContext,
    PublishedProject,
    StyleSample,
    UnifiedRetriever,
    get_retriever,
    reset_retriever,
)

__all__ = [
    "DETAIL_LIMITS",
    "ContextProvider",
    "DetailLevel",
    "KnowledgeContext",
    "PublishedProject",
    "StyleSample",
    "UnifiedRetriever",
    "get_retriever",
    "reset_retriever",
]