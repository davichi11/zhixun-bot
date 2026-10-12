"""上下文压缩器 —— Harness「动态上下文工程」的引子（第 7 篇收束）。

## 问题：知识层越建越胖，最后自己把自己压垮

第四篇给知识层加了两块东西：历史项目清单（可能几百条）+ 风格范文（几段长文）。
它们都会进提示词。于是有了这个循环：

```
知识层变丰富 → 注入的上下文变大 → token 成本上升 / 超过窗口 → 质量下降
```

**"Agent 知道得越多，反而写得越差"** —— 这是真的发生过的事。
模型在上下文里翻太久，会把开头的指令稀释掉（lost in the middle）。

## 三种应对，按本篇的成熟度排序

| 做法 | 什么时候用 | 本篇实现 |
|---|---|---|
| **① 渐进式披露** | 默认就应该是 | ✅ 本篇：按"重要度"决定注入多少 |
| ② 阈值卸载 | 上下文快满了 | ✅ 本篇：`compress()` + 句柄 |
| ③ 动态上下文工程 | 需要"按需展开"时 | ⏳ 第 7 篇：真正的动态装载 |

### ① 渐进式披露（Progressive Disclosure）

一句话：**默认给最少的信息，模型要更多时再给。**

本篇把它落在 `KnowledgeContext.render(detail_level=...)` 上：

- `summary`：只给项目名 + 发布时间（最省，~200 token）
- `standard`：给项目名 + 简介 + 3 篇范文（默认）
- `full`：给全部候选 + 完整范文（贵，只在最终写作时用）

关键点：**不同角色用不同档位**。采集员要 `summary`（它只需要知道"别重复"），
写手要 `full`（它真的要用范文）。把这两者都设成 `full` 是最常见的浪费。

### ② 阈值卸载

超过 `context_max_tokens × unload_threshold`（默认 85%）时，
把大段内容换成"摘要头 + 句柄"，并留一个可回查的引用。

**注意"可回查"这件事** —— 卸载不是删除。如果 Agent 发现摘要不够用，
它应该有一个办法把原文拿回来。第 7 篇会把这个句柄接到真正的按需加载上。
本篇先把句柄的**格式约定**定下来：

```
…（原文 4210 tokens 已卸载，回查句柄：ctx://readme/agno-agno#3f2a）
```

先定协议，后接实现 —— 这样第 7 篇改动最小。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings

logger = get_logger(__name__)

__all__ = ["CompressionResult", "ContextCompressor", "estimate_tokens"]


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
    """粗略估算 token 数。

    经验值：**英文约 4 字符/token，中文约 1.5 字/token**。
    不是精确值，但对"要不要卸载"这个二值决策来说够用了。

    第 7 篇会换成真实 tokenizer（tiktoken / 模型自带）。
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

    def make_handle(self, content: str, *, source: str = "") -> str:
        """生成一个稳定的回查句柄。

        用内容哈希前 4 位做 id，这样**同样的内容永远得到同样的句柄** ——
        好处是日志可对照，也方便第 7 篇做缓存键。
        """
        digest = hashlib.blake2b(content.encode("utf-8"), digest_size=2).hexdigest()
        return f"ctx://{source or 'blob'}/{digest}"

    def compress(self, content: str, *, keep_head: int = 2000, source: str = "") -> CompressionResult:
        """把超长内容压缩为「摘要头 + 回查句柄」。

        保留头部而不是"总结"内容，是因为**头部的信息密度通常最高**
        （标题、导语、关键结论），而总结需要模型参与 —— 那又是一笔成本和不确定性。
        """
        original = estimate_tokens(content)
        if not self.should_unload(original):
            return CompressionResult(content, original, original)

        head = content[:keep_head]
        handle = self.make_handle(content, source=source)
        compressed = f"{head}\n\n…（原文 {original} tokens 已卸载，回查句柄：{handle}）"

        result = CompressionResult(
            compressed,
            original,
            estimate_tokens(compressed),
            unloaded=[handle],
        )
        logger.info(
            "context.compressed",
            original=result.original_tokens,
            compressed=result.compressed_tokens,
            ratio=round(result.ratio, 3),
            handle=handle,
        )
        return result

    def fit(
        self,
        parts: list[str],
        *,
        max_tokens: int | None = None,
        priority: list[int] | None = None,
    ) -> tuple[list[str], dict[str, Any]]:
        """把一组上下文块压进预算内。

        Args:
            parts: 上下文块列表
            max_tokens: 本次预算（默认用 `unload_threshold × max_tokens`）
            priority: 与 `parts` 等长，**数值越小越重要**（越小越晚被丢）

        Returns:
            `(保留的块, 预算报告)`

        Notes:
            按重要性**从后往前**丢弃 —— 这就是渐进式披露的执行层。
            提示词的主体（importance=0）永远不会被丢。
        """
        budget = max_tokens or int(self.max_tokens * self.unload_threshold)
        order = priority if priority is not None else list(range(len(parts)))

        # 重要性排序（大的先丢）
        drop_order = sorted(range(len(parts)), key=lambda i: order[i], reverse=True)

        kept = list(parts)
        dropped: list[int] = []
        used = sum(estimate_tokens(p) for p in parts)

        for idx in drop_order:
            if used <= budget:
                break
            saved = estimate_tokens(kept[idx])
            kept[idx] = ""
            dropped.append(idx)
            used -= saved

        report = {
            "used": used,
            "budget": budget,
            "usage": round(used / self.max_tokens, 3),
            "dropped_parts": dropped,
            "should_unload": self.should_unload(used),
        }
        if dropped:
            logger.info("context.fit", dropped=len(dropped), used=used, budget=budget)
        return [p for p in kept if p], report

    def budget(self, parts: list[str]) -> dict[str, Any]:
        """给出上下文预算概览。"""
        used = sum(estimate_tokens(p) for p in parts)
        return {
            "used": used,
            "max": self.max_tokens,
            "usage": round(used / self.max_tokens, 3),
            "should_unload": self.should_unload(used),
        }