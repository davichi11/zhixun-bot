"""Embedding 模型封装。

选型建议：
- 线上：OpenAI text-embedding-3-small（便宜、效果好）
- 中文优先 / 离线：BAAI/bge-m3（本地推理）

统一接口的意义：换模型只改这里，向量库与检索逻辑不动。

第 1 篇：定义接口。
第 4 篇：落地实现与批量编码。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from zhixun.config.logging import get_logger

logger = get_logger(__name__)


@runtime_checkable
class Embedder(Protocol):
    """Embedding 协议。"""

    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    """OpenAI Embedding 实现。"""

    def __init__(self, model: str = "text-embedding-3-small") -> None:
        self.model = model
        self.dim = 1536

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # TODO(第 4 篇): 调用 OpenAI Embeddings API，带批量与重试
        logger.debug("embedder.embed", model=self.model, count=len(texts))
        return []


def get_embedder() -> Embedder:
    """工厂：按配置返回 Embedding 实现。"""
    return OpenAIEmbedder()
