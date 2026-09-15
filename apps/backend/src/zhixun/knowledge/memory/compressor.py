"""上下文压缩器 —— Harness「动态上下文工程」的埋点②（第 7 篇收束）。

问题：采集 100 个项目的 Readme，会瞬间把上下文窗口打满。
传统做法是"少抓点"，但那样会丢信息；正确做法是**渐进式披露 + 按需卸载**：

- 平时只把"项目名 + 一句话摘要"放进上下文
- Agent 需要细节时，再按需把某个项目的 Readme 展开进来
- 上下文占用超过阈值（默认 85%）时，把历史轮次压缩成摘要并卸载原文

第 1 篇：定义压缩策略与阈值配置。
第 4 篇：基础版（token 估算 + 截断）。
第 7 篇：接管 UnifiedRetriever，成为完整的动态上下文工程。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings

logger = get_logger(__name__)


@dataclass(slots=True)
class CompressionResult:
    """压缩结果。"""

    content: str
    original_tokens: int
    compressed_tokens: int
    unloaded: list[str] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return 1 - self.compressed_tokens / self.original_tokens


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中文约 1.5 字/token，英文约 4 字符/token）。

    TODO(第 7 篇): 换成真实 tokenizer（tiktoken / 模型自带）。
    """
    if not text:
        return 0
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    non_ascii = len(text) - ascii_chars
    return ascii_chars // 4 + non_ascii * 2 // 3


class ContextCompressor:
    """上下文压缩与卸载。"""

    def __init__(
        self,
        *,
        max_tokens: int | None = None,
        unload_threshold: float | None = None,
    ) -> None:
        self.max_tokens = max_tokens or settings.context_max_tokens
        self.unload_threshold = unload_threshold or settings.context_unload_threshold

    def should_unload(self, current_tokens: int) -> bool:
        """是否触发卸载（达到阈值比例）。"""
        return current_tokens >= self.max_tokens * self.unload_threshold

    def compress(self, content: str, *, keep_head: int = 2000) -> CompressionResult:
        """把超长内容压缩为"摘要头 + 引用句柄"。

        TODO(第 7 篇): 用轻量模型做真实摘要，并把原文卸载到 /memories/ 目录。
        """
        original = estimate_tokens(content)
        if not self.should_unload(original):
            return CompressionResult(content, original, original)

        head = content[:keep_head]
        compressed = f"{head}\n\n…（原文 {original} tokens 已卸载，可按需回查）"
        result = CompressionResult(compressed, original, estimate_tokens(compressed))
        logger.info(
            "context.compressed",
            original=result.original_tokens,
            compressed=result.compressed_tokens,
            ratio=round(result.ratio, 3),
        )
        return result

    def budget(self, parts: list[str]) -> dict[str, Any]:
        """给出上下文预算（用于第 7 篇的分配策略）。"""
        used = sum(estimate_tokens(p) for p in parts)
        return {
            "used": used,
            "max": self.max_tokens,
            "usage": round(used / self.max_tokens, 3),
            "should_unload": self.should_unload(used),
        }
