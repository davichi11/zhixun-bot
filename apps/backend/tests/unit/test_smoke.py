"""冒烟测试：保证第 1 篇交付的骨架能被导入、能跑通空流程。

注意：单元测试里**绝不调用真实 LLM**（见第一篇 5.5 节）。
"""

from __future__ import annotations

import pytest

from zhixun.config.settings import settings
from zhixun.harness import HarnessContext, build_default_chain
from zhixun.knowledge import get_retriever
from zhixun.knowledge.memory.compressor import ContextCompressor, estimate_tokens

pytestmark = pytest.mark.unit


def test_settings_loaded() -> None:
    assert settings.app_name == "智讯助手"
    assert settings.api_prefix.startswith("/api")


def test_estimate_tokens_monotonic() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello world") > 0
    assert estimate_tokens("hello world hello world") > estimate_tokens("hello world")


def test_compressor_triggers_unload() -> None:
    compressor = ContextCompressor(max_tokens=1000, unload_threshold=0.85)
    assert compressor.should_unload(900) is True
    assert compressor.should_unload(100) is False

    long_text = "a" * 8000
    result = compressor.compress(long_text)
    assert result.compressed_tokens < result.original_tokens
    assert result.ratio > 0


async def test_empty_harness_chain_passes_through() -> None:
    chain = build_default_chain()
    ctx = HarnessContext(task="测试任务", agent_name="分析师")
    out = await chain.run(ctx)
    assert out.blocked is False


async def test_unified_retriever_shape_without_submodules() -> None:
    """知识层**未装配任何子层**时，必须安全返回空上下文而不是抛异常。

    注意不要在这里调 `get_retriever()` —— 它会装配真实子层，
    从而碰到数据库和 Embedding API，违反"单元测试绝不联网、绝不落库"的约定。
    真实装配的测试见 `tests/unit/test_knowledge.py`。
    """
    from zhixun.knowledge import UnifiedRetriever

    ctx = await UnifiedRetriever().retrieve("本周 AI 开源周报", need_style=True)
    assert ctx.is_empty()
    assert isinstance(ctx.render(), str)


def test_retriever_factory_is_callable() -> None:
    """装配入口存在且可调用（不真的执行，避免触库）。"""
    assert callable(get_retriever)
