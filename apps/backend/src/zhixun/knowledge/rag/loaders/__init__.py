"""历史文章加载器 —— 把过往文章转成可入库的切片。

来源：本地 Markdown 目录 / 公众号导出 / 语雀等。
切片策略：按二级标题切，保留标题作为 metadata（检索时可加权）。

第 1 篇：定义加载器协议。
第 4 篇：落地 Markdown 目录加载。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from zhixun.config.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class Chunk:
    """一个可入库的文本切片。"""

    article_id: str
    title: str
    heading: str
    content: str


@runtime_checkable
class Loader(Protocol):
    """加载器协议。"""

    def load(self) -> list[Chunk]: ...


class MarkdownDirLoader:
    """从目录批量加载 Markdown 文章。"""

    def __init__(self, root: str | Path, *, article_id_prefix: str = "art") -> None:
        self.root = Path(root)
        self.prefix = article_id_prefix

    def load(self) -> list[Chunk]:
        # TODO(第 4 篇): 遍历 *.md，按二级标题切片
        logger.info("loader.scan", root=str(self.root), exists=self.root.exists())
        return []
