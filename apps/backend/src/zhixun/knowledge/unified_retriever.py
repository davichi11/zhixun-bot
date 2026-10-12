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
第 4 篇：落地 memory / rag 子层实现 + 渐进式披露（`detail_level`）。
第 7 篇：通过 `ContextProvider` 协议被 Harness 的动态上下文工程接管。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from zhixun.config.logging import get_logger

logger = get_logger(__name__)

# 渐进式披露档位 —— Harness 埋点⑤ 的载体
DetailLevel = Literal["summary", "standard", "full"]

# 每个档位注入多少条：`档位 -> (项目条数, 范文条数)`
DETAIL_LIMITS: dict[str, tuple[int, int]] = {
    "summary": (20, 0),    # 采集员用：只要知道"别重复"
    "standard": (80, 3),   # 默认
    "full": (500, 5),      # 写手用：真的要照着范文写
}


# ------------------------------------------------------------------ 数据契约


@dataclass(slots=True)
class PublishedProject:
    """历史上已发布过的项目（用于去重）。"""

    full_name: str
    url: str
    title: str
    published_at: str
    issue_no: int | None = None


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

    def render(
        self,
        *,
        detail_level: DetailLevel = "standard",
        max_style_samples: int | None = None,
        max_projects: int | None = None,
    ) -> str:
        """渲染成可直接注入提示词的文本块。

        Args:
            detail_level: 渐进式披露档位
                - `summary`：只给项目名 + 期号，**不含范文**（~200 token）
                - `standard`：项目清单 + 3 篇范文（默认）
                - `full`：全部候选 + 5 篇范文（只在最终写作时用）
            max_style_samples: 覆盖默认范文条数
            max_projects: 覆盖默认项目条数

        Notes:
            **不同角色用不同档位**是这一层最重要的用法：
            采集员只需要知道"别重复"→ `summary`；
            写手真的要用范文 → `full`。
            把两者都设成 `full` 是最常见也最贵的浪费。
        """
        defaults_projects, defaults_styles = DETAIL_LIMITS.get(detail_level, DETAIL_LIMITS["standard"])
        n_projects = max_projects if max_projects is not None else defaults_projects
        n_styles = max_style_samples if max_style_samples is not None else defaults_styles

        parts: list[str] = []

        if self.focus_topics:
            parts.append("## 读者关注方向\n" + "、".join(self.focus_topics))

        if self.published_projects:
            lines = [
                f"- {p.full_name}（第 {p.issue_no} 期 {p.published_at[:10]}）"
                if p.issue_no
                else f"- {p.full_name}"
                for p in self.published_projects[:n_projects]
            ]
            header = "## 已发布过的项目（本期不得重复）"
            if len(self.published_projects) > n_projects:
                header += f"\n（仅列出最近 {n_projects} 条，共 {len(self.published_projects)} 条）"
            parts.append(header + "\n" + "\n".join(lines))

        if self.style_samples and n_styles > 0:
            blocks = [f"### 范文：{s.title}\n{s.excerpt}" for s in self.style_samples[:n_styles]]
            parts.append("## 风格参考（模仿其语气与句式，不要照抄内容）\n" + "\n\n".join(blocks))

        return "\n\n".join(parts)

    def is_empty(self) -> bool:
        return not (self.published_projects or self.style_samples or self.focus_topics)


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
        embedder: Any | None = None,
    ) -> None:
        # 允许 None 以便**离线测试**：不注入任何子层时，retrieve 返回空上下文而不是崩溃
        self._memory_store = memory_store
        self._dedup = dedup
        self._retriever = retriever
        self._embedder = embedder

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

        Notes:
            **两路都失败不抛异常，返回空上下文**。
            因为知识层是"增强"不是"依赖" —— 知识层挂了应该让流程降级跑完，
            而不是让整条流水线中断。这是 Harness「能失败的环节显式失败」原则的
            一个例外：**可选能力不该成为单点故障**。
        """
        ctx = KnowledgeContext()

        if need_dedup:
            if self._memory_store is not None:
                try:
                    ctx.published_projects = await self._memory_store.list_published()
                    ctx.focus_topics = await self._memory_store.list_focus_topics()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("knowledge.memory_failed_degrade", error=str(exc))

        if need_style:
            if self._retriever is not None:
                try:
                    ctx.style_samples = await self._retriever.search_style(query, top_k=top_k)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("knowledge.rag_failed_degrade", error=str(exc))

        logger.debug(
            "knowledge.retrieved",
            need_dedup=need_dedup,
            need_style=need_style,
            projects=len(ctx.published_projects),
            samples=len(ctx.style_samples),
        )
        return ctx

    # ---------- 去重入口（Part 1 的对外 API） ----------

    async def filter_duplicates(
        self,
        candidates: list[Any],
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        """用历史记忆过滤重复项目。"""
        if self._dedup is None or self._embedder is None:
            logger.warning("knowledge.dedup_unavailable", reason="未装配 dedup/embedder")
            return list(candidates), []

        published = await self.retrieve("dedup", need_dedup=True, need_style=False)
        return await self._dedup.filter_duplicates(
            candidates, embedder=self._embedder, published=published.published_projects
        )


# ------------------------------------------------------------------ 工厂

_retriever_singleton: UnifiedRetriever | None = None


def get_retriever() -> UnifiedRetriever:
    """装配真实实现（进程内单例）。

    为什么要单例？因为 `HybridRetriever` 内部持有 BM25 索引，
    每次 `get_retriever()` 都重建一次索引是纯浪费。
    **索引的生命周期应该和进程一致，而不是和请求一致。**
    """
    global _retriever_singleton
    if _retriever_singleton is not None:
        return _retriever_singleton

    from zhixun.knowledge.memory.dedup import DedupStrategy
    from zhixun.knowledge.memory.storage import get_memory_store
    from zhixun.knowledge.rag.embedders import get_embedder
    from zhixun.knowledge.rag.retriever import HybridRetriever

    embedder = get_embedder()
    _retriever_singleton = UnifiedRetriever(
        memory_store=get_memory_store(),
        dedup=DedupStrategy(),
        retriever=HybridRetriever(embedder=embedder),
        embedder=embedder,
    )
    logger.info("knowledge.retriever_ready")
    return _retriever_singleton


def reset_retriever() -> None:
    """清空单例（测试与配置热更新时用）。"""
    global _retriever_singleton
    _retriever_singleton = None