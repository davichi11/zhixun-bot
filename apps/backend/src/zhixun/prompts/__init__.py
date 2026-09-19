"""提示词工程 —— 把提示词当代码来管。

## 为什么提示词要外置成文件？

把提示词写成 Python 字符串有三个后果，项目一大就会痛：

1. **没法 review**：改一句提示词混在业务 diff 里，reviewer 看不出重点
2. **没法多人协作**：产品/运营同学想调语气，得让工程师改代码发版
3. **没法版本化对比**：想知道"改这版提示词到底有没有变好"，没有可回溯的基线

所以本项目把提示词统一放到 `src/zhixun/prompts/*.md`，用一套极简的
「front matter + 分节 Markdown」格式管理，由本模块负责解析与变量注入。

## 文件格式

```markdown
---
name: collector
title: 采集员
role: collector
tier: light
version: 3
description: 负责从指定信源抓取 AI 领域的开源项目与技术动态。
updated: 2026-09-15
---

## 职责边界
- 只负责「抓取」，不做价值判断

## 工作方式
- 按信源清单依次抓取，源挂了就跳过并记录
```

- front matter 用 YAML 风格的 `key: value`（不引入 PyYAML，够用就行）
- 正文按 `##` 拆分为若干**指令节**，每节渲染成一条 instruction
- 正文里可写 `{{ 变量 }}`，由 `render_prompt()` 注入运行时上下文

## 用法

    from zhixun.prompts import load_prompt, render_prompt

    p = load_prompt("analyst")
    p.meta.tier        # 'primary'
    p.instructions     # ['【职责边界】\\n- ...', ...]

    text = render_prompt("writer", focus="大模型推理优化", count=5)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from zhixun.config.logging import get_logger

logger = get_logger(__name__)

PROMPT_DIR = Path(__file__).resolve().parent

# front matter 必填字段
_REQUIRED_META = ("name", "title", "description")
_VALID_TIERS = ("primary", "light")

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
# 支持 `{{ 变量 }}` 与带默认值的 `{{ 变量 | 默认值 }}`
_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\|\s*([^}]*?))?\s*\}\}")


def _iter_vars(text: str) -> list[tuple[str, str | None]]:
    """返回 [(变量名, 默认值 or None), ...]。"""
    return [(m.group(1), m.group(2)) for m in _VAR_RE.finditer(text)]


class PromptError(ValueError):
    """提示词格式错误 / 变量缺失。"""


@dataclass(slots=True)
class PromptMeta:
    """提示词的元信息（来自 front matter）。"""

    name: str
    title: str
    description: str
    role: str = ""
    tier: Literal["primary", "light"] = "primary"
    version: int = 1
    updated: str = ""

    def __post_init__(self) -> None:
        if self.tier not in _VALID_TIERS:
            raise PromptError(f"tier 只能是 {_VALID_TIERS}，收到 {self.tier!r}")


@dataclass(slots=True)
class Prompt:
    """一份解析完成的提示词。"""

    meta: PromptMeta
    sections: dict[str, list[str]] = field(default_factory=dict)
    body: str = ""
    source: Path | None = None

    @property
    def instructions(self) -> list[str]:
        """把分节正文渲染成 Agno 的 instructions 列表（只套用模板里的默认值）。

        每个 `## 小节` 变成一条 instruction，保留小节标题作为语义锚点 ——
        模型对"分组的规则"比"一长串平铺的规则"遵守得更好。

        需要注入运行时变量时，用 `render_instructions(**variables)`。
        """
        return self.render_instructions()

    def render_instructions(self, **variables: Any) -> list[str]:
        """渲染分节正文，`{{ 变量 }}` 用 variables 覆盖，缺省回落到模板默认值。"""
        out: list[str] = []
        for heading, bullets in self.sections.items():
            if not bullets:
                continue
            lines = "\n".join(
                f"- {render(b, _source=f'{self.meta.name}#{heading}', **variables)}" for b in bullets
            )
            out.append(f"【{heading}】\n{lines}")
        return out

    @property
    def variables(self) -> list[str]:
        """正文里用到、且**没有默认值**的模板变量名。"""
        return sorted({name for name, default in _iter_vars(self.body) if default is None})


def _parse_front_matter(text: str, source: Path) -> tuple[dict[str, Any], str]:
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        raise PromptError(f"{source.name} 缺少 front matter（文件必须以 --- 开头）")

    raw_meta, body = m.group(1), m.group(2)
    meta: dict[str, Any] = {}
    for line in raw_meta.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise PromptError(f"{source.name} front matter 行无法解析：{line!r}")
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, body


def _parse_sections(body: str) -> dict[str, list[str]]:
    """按 `## 标题` 拆节，节内的 `- ` 行视为要点。"""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current is not None:
            sections[current] = list(buffer)

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            flush()
            current = stripped[3:].strip()
            buffer = []
        elif stripped.startswith("# "):
            continue  # 一级标题只做人类可读，不进指令
        elif current is not None and stripped.startswith(("- ", "* ")):
            buffer.append(stripped[2:].strip())
    flush()
    return sections


@lru_cache(maxsize=32)
def load_prompt(name: str) -> Prompt:
    """按名字加载提示词（带缓存）。名字即文件名，不含 .md。"""
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        available = ", ".join(list_prompts()) or "(空)"
        raise PromptError(f"提示词 {name!r} 不存在。可用：{available}")

    raw = path.read_text(encoding="utf-8")
    meta_raw, body = _parse_front_matter(raw, path)

    missing = [k for k in _REQUIRED_META if not meta_raw.get(k)]
    if missing:
        raise PromptError(f"{path.name} 缺少必填字段：{missing}")

    meta = PromptMeta(
        name=str(meta_raw["name"]),
        title=str(meta_raw["title"]),
        description=str(meta_raw["description"]),
        role=str(meta_raw.get("role", "")),
        tier=str(meta_raw.get("tier", "primary")),  # type: ignore[arg-type]
        version=int(meta_raw.get("version", 1)),
        updated=str(meta_raw.get("updated", "")),
    )

    prompt = Prompt(
        meta=meta,
        sections=_parse_sections(body),
        body=body.strip(),
        source=path,
    )
    if not prompt.instructions:
        raise PromptError(f"{path.name} 没有任何 `##` 指令节，Agent 会缺少行为约束")
    return prompt


def render_prompt(name: str, **variables: Any) -> str:
    """渲染整份提示词正文（用于 CLI 预览 / 人工 review）。

    只替换 `{{ var }}`；未提供的变量会原样保留，并在 DEBUG 日志里提示。
    """
    prompt = load_prompt(name)
    return render(prompt.body, _source=name, **variables)


def render(text: str, *, _source: str = "<text>", **variables: Any) -> str:
    """极简模板渲染：把 `{{ 变量 }}` 换成 variables[变量]，带默认值的缺失则用默认值。"""
    missing = {
        name
        for name, default in _iter_vars(text)
        if default is None and name not in variables
    }
    if missing:
        logger.debug("prompt.missing_vars", source=_source, missing=sorted(missing))

    def _sub(m: re.Match[str]) -> str:
        key, default = m.group(1), m.group(2)
        if key in variables:
            return str(variables[key])
        if default is not None:
            return default.strip()
        return m.group(0)  # 无默认值又没传：原样保留，便于发现漏注入

    return _VAR_RE.sub(_sub, text)


def list_prompts() -> list[str]:
    """列出所有可用提示词（按文件名排序）。"""
    if not PROMPT_DIR.exists():
        return []
    return sorted(p.stem for p in PROMPT_DIR.glob("*.md"))


def clear_cache() -> None:
    """清空提示词缓存（测试 / 热更新提示词时使用）。"""
    load_prompt.cache_clear()
