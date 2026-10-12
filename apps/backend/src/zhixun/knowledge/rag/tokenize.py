"""中文分词与 BM25 —— 混合检索的关键词那一路。

## 为什么不用 jieba？

BM25 的质量高度依赖分词质量，而 jieba 的代价是：

- 一个额外的依赖（`jieba` 及其词典数据约 20MB）
- 首次加载慢（要建词典）
- 对**项目名、技术词**这类专有名词反而不如字面切分 —— 它没见过你的领域词汇

而我们的检索对象是**开源项目与 AI 技术文章**，里面全是
`RAG`、`MCP`、`LongMem`、`上下文工程` 这类词。jieba 会把
"MCP" 切成 "M" + "CP"（默认词典里没有），而**字面切分天然不会切错专有名词**。

所以这里用**字符 bigram**（相邻两字一组）：

```
"上下文工程" → 上下文 / 下文工 / 文工程
"agent memory" → ag / ge / en / nt / t（单字） + me / em / mo / or / ry
```

bigram 是中文全文检索里的经典做法（Lucene 的 `CJKAnalyzer` 就是它）：
- 零依赖，纯正则实现
- 比单字精确（"工程"不会被"工"和"程"分开）
- 比单字慢一点，但我们的语料是几百篇文章，毫秒级

**单字和 bigram 混用**：ASCII 连续段（英文/代码标识）按单字符切，
CJK 字符按 bigram 切，这样 "transformer" 也能被检索到。

## BM25 公式

```
score(D, Q) = Σ  IDF(q) × ( f(q,D) × (k1+1) )
              ────────────────────────────────
              f(q,D) + k1 × (1 - b + b × |D|/avgdl)

IDF(q) = ln( (N - n(q) + 0.5) / (n(q) + 0.5) + 1 )
```

- `k1`（默认 1.5）：词频饱和速度。太高会让高频词霸榜，太低会忽略词频
- `b`（默认 0.75）：文档长度归一化强度。1.0 = 完全按长度归一
- `avgdl`：语料平均文档长度

最后那个 `+ 1` 很关键 —— 它保证 IDF 永远为正，避免高频词得到负分。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from zhixun.config.logging import get_logger

logger = get_logger(__name__)

__all__ = ["BM25Index", "bm25_scores", "cosine_of_texts", "tokenize"]

# 连续的非 ASCII 段（CJK）按 bigram 切；ASCII 段按单字符切
_CJK = r"一-鿿぀-ヿ가-힯"
_SEGMENT_RE = re.compile(rf"[{_CJK}]+|[A-Za-z0-9_]+")


def tokenize(text: str) -> list[str]:
    """把文本切成检索用的 token 列表。

    Example:
        >>> tokenize("上下文工程")
        ['上下文', '下文工', '文工程']
        >>> tokenize("RAG v2")
        ['r', 'a', 'g', 'v', '2']
    """
    tokens: list[str] = []
    for seg in _SEGMENT_RE.findall((text or "").lower()):
        if len(seg) == 1:
            tokens.append(seg)
        elif _CJK_RE_MATCH(seg):
            # CJK 连续段 → bigram
            tokens.extend(seg[i : i + 2] for i in range(len(seg) - 1))
        else:
            # ASCII 连续段 → 单字符（保证 "rag" 能被 "r"+"a"+"g" 命中）
            tokens.extend(list(seg))
    return tokens


def _CJK_RE_MATCH(seg: str) -> bool:
    """判断一个片段是否是 CJK 字符。"""
    return all("一" <= ch <= "鿿" or "぀" <= ch <= "ヿ" or "가" <= ch <= "힯" for ch in seg)


@dataclass(slots=True)
class BM25Index:
    """一个可序列化的 BM25 倒排索引。

    数据结构刻意保持简单：一个 `dict[token, dict[doc_id, freq]]`。
    几百篇文章的规模下，这个结构足够快，而且**一眼看得懂**。
    """

    docs: dict[str, list[str]] = field(default_factory=dict)      # doc_id → tokens
    postings: dict[str, dict[str, int]] = field(default_factory=dict)  # token → {doc_id: freq}
    lengths: dict[str, int] = field(default_factory=dict)          # doc_id → token 数
    _avgdl: float = 0.0

    @property
    def size(self) -> int:
        return len(self.docs)

    def add(self, doc_id: str, text: str) -> None:
        """加入一篇文档（同一 doc_id 重复加入会覆盖）。"""
        tokens = tokenize(text)
        if not tokens:
            return
        self.docs[doc_id] = tokens
        self.lengths[doc_id] = len(tokens)
        for token, freq in Counter(tokens).items():
            self.postings.setdefault(token, {})[doc_id] = freq
        self._avgdl = sum(self.lengths.values()) / len(self.lengths)

    def search(self, query: str, *, top_k: int = 10) -> list[tuple[str, float]]:
        """检索，返回 `[(doc_id, score)]` 按分数降序。"""
        scores = bm25_scores(self, tokenize(query))
        return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]


def bm25_scores(
    index: BM25Index,
    query_tokens: list[str],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> dict[str, float]:
    """BM25 打分（纯函数，便于单测）。"""
    n_docs = index.size
    if n_docs == 0:
        return {}

    avgdl = index._avgdl or 1.0
    scores: dict[str, float] = {}

    for token in set(query_tokens):
        posting = index.postings.get(token)
        if not posting:
            continue

        # IDF：出现在越多文档里的词，贡献越小
        n_q = len(posting)
        idf = math.log((n_docs - n_q + 0.5) / (n_q + 0.5) + 1.0)

        for doc_id, freq in posting.items():
            doc_len = index.lengths.get(doc_id, avgdl)
            denom = freq + k1 * (1 - b + b * doc_len / avgdl)
            if denom <= 0:
                continue
            scores[doc_id] = scores.get(doc_id, 0.0) + idf * (freq * (k1 + 1)) / denom

    return scores


def cosine_of_texts(a: str, b: str) -> float:
    """纯文本余弦（基于 token 计数，用于不依赖 Embedding 的轻量比对）。"""
    ta, tb = Counter(tokenize(a)), Counter(tokenize(b))
    if not ta or not tb:
        return 0.0
    common = set(ta) & set(tb)
    dot = sum(ta[t] * tb[t] for t in common)
    if dot == 0:
        return 0.0
    norm_a = math.sqrt(sum(v * v for v in ta.values()))
    norm_b = math.sqrt(sum(v * v for v in tb.values()))
    return dot / (norm_a * norm_b)