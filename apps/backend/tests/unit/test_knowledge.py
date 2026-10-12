"""知识层单元测试。

原则（见第一篇 5.5 节）：**绝不联网、绝不调用真实 LLM、绝不落真实数据库**。

所有需要 Embedding 的测试统一注入 `HashEmbedder` ——
它没有语义能力，但**完全确定性**，这正是单测需要的。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from zhixun.knowledge import (
    DETAIL_LIMITS,
    KnowledgeContext,
    PublishedProject,
    StyleSample,
    UnifiedRetriever,
)
from zhixun.knowledge.ingest import ingest_history
from zhixun.knowledge.memory.compressor import ContextCompressor, estimate_tokens
from zhixun.knowledge.memory.dedup import DedupStrategy, normalize_url
from zhixun.knowledge.rag.embedders import HashEmbedder, cosine_similarity
from zhixun.knowledge.rag.loaders import MarkdownDirLoader, parent_of, record_id, split_by_h2
from zhixun.knowledge.rag.retriever import HybridRetriever, rrf_fuse
from zhixun.knowledge.rag.tokenize import BM25Index, bm25_scores, tokenize
from zhixun.knowledge.rag.vector_store import ArticleRecord, InMemoryVectorStore

pytestmark = pytest.mark.unit


@dataclass(slots=True)
class Candidate:
    """模拟采集员产出的候选素材。"""

    name: str
    url: str
    title: str = ""


def _embedder() -> HashEmbedder:
    return HashEmbedder(dim=256)


# ---------------------------------------------------------------- 分词


def test_tokenize_uses_bigram_for_cjk() -> None:
    assert tokenize("上下文工程") == ["上下", "下文", "文工", "工程"]


def test_tokenize_uses_single_char_for_ascii() -> None:
    """专有名词不该被切错：rag 要能被 r/a/g 命中。"""
    assert tokenize("RAG") == ["r", "a", "g"]
    assert tokenize("LongMem") == list("longmem")


def test_tokenize_is_case_insensitive() -> None:
    assert tokenize("RAG") == tokenize("rag")


def test_tokenize_handles_empty() -> None:
    assert tokenize("") == []


# ---------------------------------------------------------------- BM25


def test_bm25_ranks_the_relevant_doc_first() -> None:
    idx = BM25Index()
    idx.add("a", "Agno 3.x 的 Agent 工具系统开发与机械强制护栏")
    idx.add("b", "RAG 检索增强与向量数据库选型")
    idx.add("c", "上下文工程：渐进式披露与动态上下文")

    assert idx.search("护栏", top_k=1)[0][0] == "a"
    assert idx.search("向量", top_k=1)[0][0] == "b"
    assert idx.search("上下文", top_k=1)[0][0] == "c"


def test_bm25_rare_token_scores_higher_than_common_one() -> None:
    """IDF 的意义：到处都是的词不该主导排名。"""
    idx = BM25Index()
    idx.add("a", "护栏与参数钳制")
    for i in range(5):
        idx.add(f"common{i}", "护栏 出现在很多文档里的通用词")

    scores = bm25_scores(idx, tokenize("护栏"))
    assert scores["a"] > max(scores[f"common{i}"] for i in range(5))


def test_bm25_empty_index_returns_nothing() -> None:
    assert bm25_scores(BM25Index(), tokenize("任意")) == {}
    assert BM25Index().search("任意") == []


def test_bm25_ignores_empty_docs() -> None:
    idx = BM25Index()
    idx.add("a", "有内容")
    idx.add("b", "   ")
    assert idx.size == 1


# ---------------------------------------------------------------- Embedding 与余弦


def test_cosine_similarity_identical_is_one() -> None:
    emb = _embedder()
    assert cosine_similarity(emb.embed_one("agno"), emb.embed_one("agno")) == 1.0


def test_cosine_similarity_edge_cases() -> None:
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0  # 维度不匹配


def test_hash_embedder_is_deterministic() -> None:
    """降级实现的第一要求：同样输入永远同样输出，否则断言无法成立。"""
    emb = _embedder()
    assert emb.embed_one("Agno 3.x") == emb.embed_one("Agno 3.x")
    assert emb.embed_one("Agno") != emb.embed_one("完全不同的东西")


def test_hash_embedder_empty_text_is_zero_vector() -> None:
    emb = _embedder()
    assert set(emb.embed_one("")) == {0.0}


# ---------------------------------------------------------------- URL 规范化


@pytest.mark.parametrize(
    "raw",
    [
        "https://github.com/agno-agi/agno",
        "https://GitHub.com/Agno-AGI/Agno/",
        "http://www.github.com/agno-agi/agno.git",
        "https://github.com/agno-agi/agno?utm_source=newsletter#readme",
        "https://github.com/agno-agi/agno/tree/main/src",
        "github.com/agno-agi/agno",
    ],
)
def test_normalize_url_folds_all_variants(raw: str) -> None:
    assert normalize_url(raw) == "github.com/agno-agi/agno"


def test_normalize_url_empty() -> None:
    assert normalize_url("") == ""
    assert normalize_url(None) == ""


# ---------------------------------------------------------------- 两段式去重


def _published() -> list[PublishedProject]:
    return [
        PublishedProject("agno-agi/agno", "https://github.com/agno-agi/agno", "Agno 智能体框架", "2026-08-01", 1),
        PublishedProject("mem0ai/mem0", "https://github.com/mem0ai/mem0", "Mem0 长期记忆", "2026-09-01", 2),
    ]


async def test_dedup_url_stage_short_circuits() -> None:
    """URL 命中就不该再走语义段 —— 那是真实的 Embedding 调用。"""
    ds = DedupStrategy()
    verdict = await ds.check(
        url="https://www.github.com/agno-agi/agno?utm_source=x",
        title="完全不同的标题",
        published=_published(),
        embedder=_embedder(),
    )
    assert verdict.is_duplicate
    assert verdict.stage == "url"


async def test_dedup_title_stage_catches_same_topic_different_repo() -> None:
    """同题异构：仓库名不同但标题相同 —— 这正是第二段存在的意义。"""
    ds = DedupStrategy()
    verdict = await ds.check(
        url="https://github.com/agno-agi/agno-v2",
        title="Agno 智能体框架",
        published=_published(),
        embedder=_embedder(),
    )
    assert verdict.is_duplicate
    assert verdict.stage == "title"
    assert verdict.similarity >= ds.threshold


async def test_dedup_keeps_genuinely_new_project() -> None:
    ds = DedupStrategy()
    verdict = await ds.check(
        url="https://github.com/brand-new/ai",
        title="一个全新的 AI 项目",
        published=_published(),
        embedder=_embedder(),
    )
    assert not verdict.is_duplicate
    assert verdict.stage == "title"


async def test_dedup_without_embedder_only_runs_url_stage() -> None:
    ds = DedupStrategy()
    verdict = await ds.check(
        url="https://github.com/brand-new/ai",
        title="任意",
        published=_published(),
        embedder=None,
    )
    assert not verdict.is_duplicate
    assert verdict.stage == "url"


async def test_filter_duplicates_reports_reason_per_item() -> None:
    """被剔除的条目必须带原因 —— 否则运营无法复盘"为什么这条没了"。"""
    ds = DedupStrategy()
    cands = [
        Candidate("agno-agi/agno", "https://github.com/agno-agi/agno?utm_source=x", "别的标题"),
        Candidate("agno-agi/agno-v2", "https://github.com/agno-agi/agno-v2", "Agno 智能体框架"),
        Candidate("brand-new/ai", "https://github.com/brand-new/ai", "全新项目"),
    ]
    keep, dropped = await ds.filter_duplicates(cands, embedder=_embedder(), published=_published())

    assert [c.name for c in keep] == ["brand-new/ai"]
    assert {d["stage"] for d in dropped} == {"url", "title"}
    assert all(d["reason"] for d in dropped)


def test_semantic_text_prefers_title_over_repo_name() -> None:
    """回归防护：曾经用 name 优先，导致"同题异构"100% 漏判。"""
    from zhixun.knowledge.memory.dedup import _semantic_text

    assert _semantic_text(Candidate("agno/agno-v2", "u", "Agno 智能体框架")) == "Agno 智能体框架"
    assert _semantic_text(Candidate("agno/agno", "u", "")) == "agno/agno"


# ---------------------------------------------------------------- 切片与加载


def test_split_by_h2_keeps_preamble() -> None:
    """第一个 ## 之前的导语不能丢 —— 那里往往是最凝练的判断。"""
    sections = split_by_h2("导语正文\n\n## A\n甲\n\n## B\n乙")
    assert sections == [("", "导语正文"), ("A", "甲"), ("B", "乙")]


def test_split_by_h2_without_headings_returns_whole_text() -> None:
    assert split_by_h2("只有正文") == [("", "只有正文")]


def test_split_by_h2_strips_front_matter() -> None:
    text = "---\nname: x\n---\n\n# 标题\n\n## A\n正文"
    sections = split_by_h2(text)
    joined = "".join(body for _, body in sections)
    assert "name: x" not in joined
    assert ("A", "正文") in sections


def test_record_id_and_parent_of() -> None:
    from zhixun.knowledge.rag.loaders import Chunk

    chunk = Chunk(article_id="art-2026-09-01-x", title="t", heading="h", content="c", index=3)
    rid = record_id(chunk)
    assert rid == "art-2026-09-01-x#3"
    assert parent_of(rid) == "art-2026-09-01-x"
    assert parent_of("no-suffix") == "no-suffix"


def test_loader_missing_dir_degrades(tmp_path: Path) -> None:
    """目录不存在要 warning + 空列表，不能抛异常打断服务启动。"""
    assert MarkdownDirLoader(tmp_path / "不存在").load() == []


def test_loader_skips_hidden_and_short_sections(tmp_path: Path) -> None:
    (tmp_path / "_草稿.md").write_text("# 草稿\n\n## A\n" + "内容" * 50, encoding="utf-8")
    (tmp_path / "2026-09-01-正式.md").write_text(
        "# 正式文章\n\n## 有内容的小节\n" + "正文" * 100,
        encoding="utf-8",
    )
    chunks = MarkdownDirLoader(tmp_path).load()
    assert {c.article_id for c in chunks} == {"art-2026-09-01-正式"}
    assert chunks[0].published_at == "2026-09-01"


def test_chunk_full_text_includes_title_and_heading() -> None:
    from zhixun.knowledge.rag.loaders import Chunk

    chunk = Chunk(article_id="a", title="标题", heading="小标题", content="正文")
    assert "标题" in chunk.full_text and "小标题" in chunk.full_text


# ---------------------------------------------------------------- RRF 与混合检索


def test_rrf_fuse_rewards_agreement_between_rankings() -> None:
    fused = dict(rrf_fuse([["a", "b"], ["a", "c"]]))
    assert fused["a"] > fused["b"]
    assert fused["a"] > fused["c"]


def test_rrf_score_matches_formula() -> None:
    fused = dict(rrf_fuse([["x"]], k=60))
    assert fused["x"] == pytest.approx(1 / 61)


def test_rrf_single_ranking_is_still_sorted() -> None:
    fused = dict(rrf_fuse([["a", "b", "c"]]))
    assert fused["a"] > fused["b"] > fused["c"]


async def test_hybrid_search_dedupes_by_parent_article() -> None:
    """三篇范文必须来自三篇不同的文章，否则风格参考失去意义。"""
    store = InMemoryVectorStore()
    emb = _embedder()
    records = [
        ArticleRecord("art-a#0", "文章A", "混合检索与 RRF 融合的实现", emb.embed_one("混合检索与 RRF 融合的实现")),
        ArticleRecord("art-a#1", "文章A", "混合检索的另一个小节", emb.embed_one("混合检索的另一个小节")),
        ArticleRecord("art-b#0", "文章B", "BM25 与中文分词", emb.embed_one("BM25 与中文分词")),
    ]
    await store.upsert(records)

    retriever = HybridRetriever(store=store, embedder=emb)
    samples = await retriever.search_style("混合检索 RRF", top_k=5)

    ids = [s.article_id for s in samples]
    assert ids.count("art-a") == 1
    assert len(set(ids)) == len(ids)


async def test_vector_store_upsert_overwrites_same_id() -> None:
    store = InMemoryVectorStore()
    emb = _embedder()
    await store.upsert([ArticleRecord("a", "旧标题", "旧内容", emb.embed_one("旧"))])
    await store.upsert([ArticleRecord("a", "新标题", "新内容", emb.embed_one("新"))])

    assert len(await store.all_records()) == 1
    assert (await store.get("a")).title == "新标题"


async def test_vector_store_search_returns_nearest() -> None:
    store = InMemoryVectorStore()
    emb = _embedder()
    target = "向量检索与混合召回"
    await store.upsert(
        [
            ArticleRecord("near", "近", target, emb.embed_one(target)),
            ArticleRecord("far", "远", "完全不相干的园艺种植内容", emb.embed_one("完全不相干的园艺种植内容")),
        ]
    )
    hits = await store.search(emb.embed_one(target), limit=2)
    assert hits[0]["article_id"] == "near"


# ---------------------------------------------------------------- 入库管道


async def test_ingest_end_to_end(tmp_path: Path) -> None:
    (tmp_path / "2026-09-01-甲.md").write_text(
        "# 甲文章\n\n导语" + "内容" * 40 + "\n\n## 小节一\n" + "正文" * 60, encoding="utf-8"
    )
    (tmp_path / "2026-09-02-乙.md").write_text(
        "# 乙文章\n\n## 小节二\n" + "正文" * 60, encoding="utf-8"
    )

    store = InMemoryVectorStore()
    result = await ingest_history(tmp_path, store=store, embedder=_embedder())

    assert result.files == 2
    assert result.chunks >= 2
    assert result.written == result.chunks
    assert result.bm25_docs == result.chunks
    assert result.elapsed_ms >= 0


async def test_ingest_empty_dir_is_noop(tmp_path: Path) -> None:
    store = InMemoryVectorStore()
    result = await ingest_history(tmp_path, store=store, embedder=_embedder())
    assert result.chunks == 0
    assert result.written == 0


# ---------------------------------------------------------------- 渐进式披露


def _rich_context(n_projects: int = 200, n_styles: int = 8) -> KnowledgeContext:
    return KnowledgeContext(
        published_projects=[
            PublishedProject(f"owner{i}/repo{i}", f"https://github.com/owner{i}/repo{i}", f"项目 {i}", "2026-09-01", i // 8 + 1)
            for i in range(n_projects)
        ],
        style_samples=[
            StyleSample(f"art-{i}", f"文章 {i}", "这是一段用于风格迁移的范文正文。" * 60)
            for i in range(n_styles)
        ],
        focus_topics=["Agent 工程", "推理优化"],
    )


def test_render_tiers_are_ordered_by_cost() -> None:
    """渐进式披露的核心承诺：三档必须严格递增，否则"默认最小信息"就失去意义。"""
    ctx = _rich_context()
    sizes = [estimate_tokens(ctx.render(detail_level=lv)) for lv in ("summary", "standard", "full")]
    assert sizes[0] < sizes[1] < sizes[2]


def test_summary_tier_has_no_style_samples() -> None:
    """采集员用 summary —— 它只需要知道"别重复"，不需要学写作风格。"""
    ctx = _rich_context()
    text = ctx.render(detail_level="summary")
    assert "风格参考" not in text
    assert "已发布过的项目" in text


def test_render_truncates_and_announces() -> None:
    ctx = _rich_context(n_projects=200)
    text = ctx.render(detail_level="summary")
    assert "仅列出最近 20 条，共 200 条" in text


def test_render_full_includes_style_samples() -> None:
    ctx = _rich_context()
    text = ctx.render(detail_level="full")
    assert "风格参考" in text
    assert "模仿其语气与句式" in text


def test_detail_limits_shape() -> None:
    assert DETAIL_LIMITS["summary"][1] == 0
    assert DETAIL_LIMITS["summary"][0] < DETAIL_LIMITS["standard"][0] < DETAIL_LIMITS["full"][0]


def test_empty_context_renders_empty() -> None:
    assert KnowledgeContext().render() == ""
    assert KnowledgeContext().is_empty()


# ---------------------------------------------------------------- 上下文压缩


def test_compressor_does_not_compress_when_under_threshold() -> None:
    result = ContextCompressor(max_tokens=100_000).compress("短文本")
    assert result.unloaded == []
    assert result.ratio == 0.0


def test_compressor_unloads_with_stable_handle() -> None:
    c = ContextCompressor(max_tokens=100, unload_threshold=0.5)
    content = "字" * 5000
    first = c.compress(content, source="readme")
    second = c.compress(content, source="readme")

    assert first.unloaded and first.unloaded[0].startswith("ctx://readme/")
    # 同样的内容必须得到同样的句柄，否则日志无法对照、缓存无法命中
    assert first.unloaded == second.unloaded
    assert first.ratio > 0


def test_fit_drops_by_priority_not_by_position() -> None:
    """低优先级的块先被丢；priority=0 的主体永远不丢。"""
    c = ContextCompressor(max_tokens=500, unload_threshold=1.0)
    parts = ["主体指令" * 10, "范文甲" * 200, "范文乙" * 200, "关注方向"]
    kept, report = c.fit(parts, priority=[0, 5, 5, 9])

    assert report["dropped_parts"], "超预算时至少应丢弃一块"
    assert "主体指令" in kept[0], "priority=0 的主体永远不丢"
    assert "关注方向" not in "".join(kept), "priority=9 的应最先被丢"
    assert len("".join(kept)) < len("".join(parts))


def test_estimate_tokens_separates_cjk_and_ascii() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("中文中文") > estimate_tokens("abcd")


# ---------------------------------------------------------------- 统一入口


async def test_unified_retriever_degrades_when_submodules_missing() -> None:
    """知识层是"增强"不是"依赖" —— 不装配任何子层也不该崩。"""
    ctx = await UnifiedRetriever().retrieve("任意查询", need_dedup=True, need_style=True)
    assert ctx.is_empty()


async def test_unified_retriever_swallows_submodule_failure() -> None:
    class _Boom:
        async def list_published(self, limit=None):  # noqa: ANN001, ANN003
            raise RuntimeError("数据库挂了")

        async def list_focus_topics(self):  # noqa: ANN001, ANN003
            raise RuntimeError("数据库挂了")

    ctx = await UnifiedRetriever(memory_store=_Boom()).retrieve("q")
    assert ctx.is_empty()


async def test_unified_retriever_collects_both_sources() -> None:
    class _Mem:
        async def list_published(self, limit=None):  # noqa: ANN001, ANN003
            return [PublishedProject("a/b", "u", "t", "2026-09-01")]

        async def list_focus_topics(self):  # noqa: ANN001, ANN003
            return ["Agent 工程"]

    class _Rag:
        async def search_style(self, query, top_k=None):  # noqa: ANN001, ANN003
            return [StyleSample("art-1", "文章", "范文正文")]

    retriever = UnifiedRetriever(memory_store=_Mem(), retriever=_Rag())
    ctx = await retriever.retrieve("q", need_style=True)

    assert len(ctx.published_projects) == 1
    assert len(ctx.style_samples) == 1
    assert "已发布过的项目" in ctx.render()