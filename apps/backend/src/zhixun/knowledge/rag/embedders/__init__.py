"""Embedding 模型封装 —— 一个协议，两个实现。

## 为什么要自己包一层？

本项目需要三种 Embedding 场景，它们的成本和可用性要求完全不同：

| 场景 | 需要 | 不能接受 |
|---|---|---|
| 生产入库 | 语义质量（"推理优化" ≈ "推理加速"） | —— |
| 开发调试 | 语义质量 | 花钱 |
| **单元测试** | **确定性** | **联网 + 花钱** |

第三行是关键。测试里如果用真实 Embedding，你就得为了断言
"这两条相似度 > 0.85"而调用一次付费 API（还可能因为网络抖动而 flaky）。

所以这里有一个**降级实现** `HashEmbedder` —— 它不是"随便糊一个"，
而是满足一条硬约束：**同样的文本永远得到同样的向量**。

> 降级实现的第一要求不是"能跑"，而是**确定性**。
> 随机向量会让"去重阈值 0.85"这种断言完全失去意义。

## HashEmbedder 怎么工作

就是 hashing trick：把每个字符哈希到固定维度的某一维上，累加后做 L2 归一化。

它**没有语义** —— "推理优化" 和 "推理加速" 的相似度只来自共现字符，比值很低。
它只适合"完全相同的文本 → 相似度 1.0"这一种判断，
而这恰好覆盖了去重的主要场景：同一个项目名再次出现。

换句话说：`HashEmbedder` 是**去重的兜底**，不是**语义检索的实现**。
配置里 `EMBEDDING_PROVIDER` 默认 `openai`；切到 `hash` 时知识层仍然可用，
但你会失去风格迁移能力 —— **降级必须诚实，不能假装自己还行。**
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Protocol, runtime_checkable

from zhixun.config.logging import get_logger

logger = get_logger(__name__)

__all__ = ["Embedder", "HashEmbedder", "OpenAIEmbedder", "cosine_similarity", "get_embedder"]


# ------------------------------------------------------------------ 工具函数


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度（纯 Python，不依赖 numpy）。

    手写而不是 `numpy.dot`，有两个理由：
    1. 少一个重量级依赖 —— 1536 维的纯 Python 点积在毫秒级，本项目完全够用
    2. 教学价值：把公式摊开看，比调库更清楚"相似度"到底在算什么

    公式：`cos(a, b) = (a·b) / (|a| × |b|)`

    Returns:
        [-1, 1] 区间内的相似度；维度不匹配或任一向量为零时返回 0.0。
    """
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y

    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


# ------------------------------------------------------------------ 协议


@runtime_checkable
class Embedder(Protocol):
    """Embedding 协议 —— 换模型只改实现，检索逻辑不动。"""

    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


# ------------------------------------------------------------------ 降级实现


class HashEmbedder:
    """确定性 hashing embedder —— 零依赖、零网络、可复现。

    ⚠️ **没有语义能力**。它只能判断"这两段文本是不是几乎一样的字"。
    生产环境请用 `OpenAIEmbedder` 或本地模型。
    """

    name = "hash"

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        normalized = (text or "").strip().lower()
        if not normalized:
            return vector

        # 按字符切分（中文不需要分词就能有稳定特征），再哈希到固定维度
        for ch in normalized:
            h = int(hashlib.blake2b(ch.encode("utf-8"), digest_size=8).hexdigest(), 16)
            vector[h % self.dim] += 1.0

        # L2 归一化：归一化后"完全相同的文本"余弦相似度精确等于 1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return self.embed_sync(texts)

    def embed_sync(self, texts: list[str]) -> list[list[float]]:
        """同步版本：入库与去重这类"确定要算"的场景不需要异步。"""
        return [self.embed_one(t) for t in texts]


# ------------------------------------------------------------------ 生产实现


class OpenAIEmbedder:
    """OpenAI Embedding 实现（延迟 import + 失败降级）。"""

    name = "openai"

    def __init__(self, model: str = "text-embedding-3-small", *, api_key: str | None = None) -> None:
        self.model = model
        self.dim = 1536
        self._api_key = api_key

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量编码。

        批量而不是逐条调用：Embedding API 按 token 计费，但**请求开销是固定的**，
        一次传 64 条比 64 次单独调用快一个数量级。

        失败时**降级为 `HashEmbedder`** 而不是抛异常 —— 一次索引失败不该让
        整个入库任务中断。降级会打 warning，归因时能看见。
        """
        if not texts:
            return []

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self._api_key) if self._api_key else AsyncOpenAI()
            resp = await client.embeddings.create(model=self.model, input=texts)
            return [item.embedding for item in resp.data]
        except Exception as exc:  # noqa: BLE001 - 缺 SDK / 缺 key / 网络错误都要降级
            logger.warning("embedder.openai_failed_fallback_hash", error=str(exc), count=len(texts))
            fallback = HashEmbedder(dim=self.dim)
            return fallback.embed_sync(texts)


# ------------------------------------------------------------------ 工厂


def get_embedder(provider: str | None = None) -> Embedder:
    """按配置返回 Embedding 实现。

    配置项 `EMBEDDING_PROVIDER`：`openai`（默认）/ `hash`。
    """
    from zhixun.config.settings import settings

    provider = (provider or settings.embedding_provider).lower()
    if provider == "hash":
        logger.info("embedder.hash_selected", dim=settings.embedding_hash_dim)
        return HashEmbedder(dim=settings.embedding_hash_dim)
    return OpenAIEmbedder(
        model=settings.embedding_model,
        api_key=settings.openai_api_key or None,
    )


def describe_embedder() -> dict[str, Any]:
    """给 CLI 展示用（不实例化，不发请求）。"""
    from zhixun.config.settings import settings

    is_hash = settings.embedding_provider.lower() == "hash"
    return {
        "provider": settings.embedding_provider,
        "model": "-" if is_hash else settings.embedding_model,
        "dim": settings.embedding_hash_dim if is_hash else 1536,
        "note": "hash 模式无语义能力，仅供离线与去重兜底" if is_hash else "",
    }