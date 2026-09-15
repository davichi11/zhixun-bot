"""知识层统一对外接口（本项目关键架构决策，见第一篇 4.2 / 第 4 篇）。

为什么要有这一层？
「记忆」和「RAG」对外都只是同一句话：**Agent 需要知道什么，来这里拿**。
如果让每个 Agent 分别去调 memory 和 rag，会出现三个问题：
  1. 业务 Agent 需要知道两套 API，耦合到存储细节
  2. 上下文拼装逻辑散落各处，无法统一治理
  3. Harness 的动态上下文工程（第 7 篇）没有统一接入口

所以：**所有 Agent 只依赖 `UnifiedRetriever` 一个接口**，
它内部再决定这次要查记忆、查 RAG，还是两者都查。

第 1 篇：定义接口与数据契约。
第 4 篇：落地 memory / rag 子层实现。
第 7 篇：通过 `ContextProvider` 协议被 Harness 的动态上下文工程接管。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from zhixun.config.logging import get_logger

logger = get_logger(__name__)


# ------------------------------------------------------------------ 数据契约


@dataclass(slots=True)
class PublishedProject:
    """历史上已发布过的项目（用于去重）。"""

    full_name: str
    url: str
    title: str
    published_at: str


@dataclass(slots=True)
class StyleSample:
    """风格范文片段（用于 Few-shot 注入）。"""

    article_id: str
    title: str
    excerpt: str
    score: float = 0.0


@dataclass(slots=True)
class KnowledgeContext:
    """一次检索的完整结果 —— Agent 需要的"所有该知道的东西"。"""

    published_projects: list[PublishedProject] = field(default_factory=list)
    style_samples: list[StyleSample] = field(default_factory=list)
    focus_topics: list[str] = field(default_factory=list)

    def render(self, *, max_style_samples: int = 3) -> str:
        """渲染成可直接注入提示词的文本块。

        注意：这里会做**渐进式披露**的前置裁剪 —— 只放最必要的部分，
        完整的上下文预算控制交给 Harness（第 7 篇）。
        """
        parts: list[str] = []

        if self.focus_topics:
            parts.append("## 读者关注方向\n" + "、".join(self.focus_topics))

        if self.published_projects:
            lines = [f"- {p.full_name}（{p.published_at}）" for p in self.published_projects[:50]]
            parts.append("## 已发布过的项目（不得重复）\n" + "\n".join(lines))

        if self.style_samples:
            samples = self.style_samples[:max_style_samples]
            blocks = [f"### 范文：{s.title}\n{s.excerpt}" for s in samples]
            parts.append("## 风格参考\n" + "\n\n".join(blocks))

        return "\n\n".join(parts)


# ------------------------------------------------------------------ 接口协议


@runtime_checkable
class ContextProvider(Protocol):
    """上下文提供者协议 —— Harness 的动态上下文工程依赖此抽象，而非具体实现。"""

    async def retrieve(
        self,
        query: str,
        *,
        need_dedup: bool = True,
        need_style: bool = False,
        top_k: int | None = None,
    ) -> KnowledgeContext: ...


# ------------------------------------------------------------------ 默认实现


class UnifiedRetriever:
    """知识层默认实现：组合 memory 子层与 rag 子层。"""

    def __init__(
        self,
        *,
        memory_store: Any | None = None,
        dedup: Any | None = None,
        retriever: Any | None = None,
    ) -> None:
        # 延迟到第 4 篇注入真实实现，这里允许 None 以便第 1 篇就能导入与测试
        self._memory_store = memory_store
        self._dedup = dedup
        self._retriever = retriever

    async def retrieve(
        self,
        query: str,
        *,
        need_dedup: bool = True,
        need_style: bool = False,
        top_k: int | None = None,
    ) -> KnowledgeContext:
        """统一检索入口。

        Args:
            query: 本次任务的语义描述（如"本周 AI 开源项目周报"）
            need_dedup: 是否需要历史已发布项目清单
            need_style: 是否需要风格范文
            top_k: 范文条数上限，默认取配置 `rag_top_k`
        """
        ctx = KnowledgeContext()

        if need_dedup and self._memory_store is not None:
            ctx.published_projects = await self._memory_store.list_published()
            ctx.focus_topics = await self._memory_store.list_focus_topics()

        if need_style and self._retriever is not None:
            ctx.style_samples = await self._retriever.search_style(query, top_k=top_k)

        logger.debug(
            "knowledge.retrieved",
            need_dedup=need_dedup,
            need_style=need_style,
            projects=len(ctx.published_projects),
            samples=len(ctx.style_samples),
        )
        return ctx


def get_retriever() -> UnifiedRetriever:
    """工厂函数：第 4 篇会在这里装配 memory / rag 的真实实现。"""
    # TODO(第 4 篇): 注入 SqliteStorage/PostgresStorage + LanceDB retriever
    return UnifiedRetriever()
