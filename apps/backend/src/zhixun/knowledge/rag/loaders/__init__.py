"""历史文章加载器 —— 把过往文章转成可入库的切片。

## 切片策略：按二级标题（`##`）切，而不是按固定长度切

固定长度切片（每 500 字一刀）是 RAG 里最常见的做法，也是最容易踩坑的做法：

- 一段完整的论证被从中间劈开，两半单独看都没意义
- 检索命中了后半段，喂给模型的是"……所以我们决定采用 B 方案"，
  **而它不知道前面在讨论什么**
- 切片边界和语义边界毫无关系

按标题切的好处：**每个切片自带完整语义**，而且标题本身就是最好的检索词。
本项目的文章全是 Markdown（公众号同步过来就是 md），标题结构规范，
所以这个策略几乎零成本。

## 单篇 vs 多篇

切片粒度还有一个更粗的选择：整篇一篇，还是每个 `##` 一篇？

- 整篇入库 → 检索粒度太粗，注入上下文时又太长
- 每个 `##` 入库 → 粒度合适；但**风格参考需要整篇的语气**

所以我们两条都留：`Chunk` 负责检索，`ArticleRecord` 负责风格 ——
入库时每个 chunk 存一份，但**同一篇文章的 chunk 共享 `article_id`**，
风格检索时可以按 `article_id` 聚合。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from zhixun.config.logging import get_logger

logger = get_logger(__name__)

__all__ = ["Chunk", "Loader", "MarkdownDirLoader", "parent_of", "record_id"]


def record_id(chunk: "Chunk") -> str:
    """切片级唯一 ID：`art-2026-09-01-xxx#3`。

    向量库按切片存（检索粒度细），风格检索按父级去重（保证给的是不同文章）。
    """
    return f"{chunk.article_id}#{chunk.index}"


def parent_of(article_id: str) -> str:
    """取父级（整篇）ID：`art-2026-09-01-xxx#3` → `art-2026-09-01-xxx`。"""
    return article_id.split("#", 1)[0]

# 文件名里带日期的形如 2026-09-01-标题.md
_DATE_IN_NAME = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_H2 = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


@dataclass(slots=True)
class Chunk:
    """一个可入库的文本切片。"""

    article_id: str
    title: str
    heading: str
    content: str
    source_path: str = ""
    published_at: str = ""
    index: int = 0

    @property
    def full_text(self) -> str:
        """检索时使用的文本：标题 + 小标题 + 正文（三段一起参与匹配）。"""
        return "\n".join(p for p in (self.title, self.heading, self.content) if p)


@runtime_checkable
class Loader(Protocol):
    """加载器协议。"""

    def load(self) -> list[Chunk]: ...


def _extract_title(text: str, fallback: str) -> str:
    """取第一个一级标题作为文章标题。"""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _extract_date(stem: str) -> str:
    """从文件名里抠出日期（形如 `2026-09-01-标题`）。"""
    m = _DATE_IN_NAME.search(stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


def _strip_front_matter(text: str) -> str:
    """去掉 front matter（提示词模板那种 `---` 包裹的元信息）。"""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip("\n")
    return text


def split_by_h2(text: str) -> list[tuple[str, str]]:
    """按二级标题切分，返回 `[(小标题, 正文), ...]`。

    第一个 `##` 之前的内容归入一个标题为空的小节（通常是导语），
    **不要丢** —— 导语往往包含这篇文章最凝练的判断。

    Example:
        >>> split_by_h2("导语\\n\\n## A\\n甲\\n\\n## B\\n乙")
        [('', '导语'), ('A', '甲'), ('B', '乙')]
    """
    text = _strip_front_matter(text)
    matches = list(_H2.finditer(text))
    if not matches:
        return [("", text.strip())]

    sections: list[tuple[str, str]] = []
    head = text[: matches[0].start()].strip()
    if head:
        sections.append(("", head))

    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end() : end].strip()
        sections.append((m.group(1), body))
    return sections


class MarkdownDirLoader:
    """从目录批量加载 Markdown 文章。"""

    def __init__(
        self,
        root: str | Path,
        *,
        article_id_prefix: str = "art",
        min_chars: int = 80,
        recursive: bool = True,
    ) -> None:
        self.root = Path(root)
        self.prefix = article_id_prefix
        # 小于这个长度的切片直接丢掉：它几乎不可能是有用的检索结果
        self.min_chars = min_chars
        self.recursive = recursive

    def load(self) -> list[Chunk]:
        """扫描目录并切片。

        跳过规则（写出来是为了让"为什么这条没入库"可解释）：
        - 目录不存在 → 记 warning 后返回空列表，**不抛异常**
        - 以 `_` 或 `.` 开头的文件（草稿、隐藏文件）
        - 切片正文短于 `min_chars`
        """
        if not self.root.exists():
            logger.warning("loader.missing_dir", root=str(self.root))
            return []
        if not self.root.is_dir():
            logger.warning("loader.not_a_dir", root=str(self.root))
            return []

        pattern = "**/*.md" if self.recursive else "*.md"
        files = sorted(p for p in self.root.glob(pattern) if not p.name.startswith((".", "_")))

        chunks: list[Chunk] = []
        for path in files:
            chunks.extend(self._load_one(path))

        logger.info("loader.done", files=len(files), chunks=len(chunks), root=str(self.root))
        return chunks

    def _load_one(self, path: Path) -> list[Chunk]:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("loader.read_failed", path=str(path), error=str(exc))
            return []

        title = _extract_title(text, fallback=path.stem)
        published_at = _extract_date(path.stem)
        article_id = f"{self.prefix}-{path.stem}"
        rel = str(path.relative_to(self.root)) if path.is_relative_to(self.root) else path.name

        out: list[Chunk] = []
        for idx, (heading, body) in enumerate(split_by_h2(text)):
            if len(body) < self.min_chars and not heading:
                continue
            out.append(
                Chunk(
                    article_id=article_id,
                    title=title,
                    heading=heading,
                    content=body,
                    source_path=rel,
                    published_at=published_at,
                    index=idx,
                )
            )
        return out


def get_loader(root: str | Path | None = None) -> MarkdownDirLoader:
    """工厂：按配置返回加载器（默认读 `history_articles_dir`）。"""
    from zhixun.config.settings import BACKEND_ROOT, settings

    base = Path(root) if root else BACKEND_ROOT / settings.history_articles_dir
    return MarkdownDirLoader(base)