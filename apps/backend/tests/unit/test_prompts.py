"""提示词模块单元测试。

这些测试是「提示词工程」能成立的前提 —— 如果模板加载、变量注入没有测试兜底，
提示词就会悄悄退化成"没人敢改的字符串常量"。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zhixun import prompts
from zhixun.prompts import PromptError, load_prompt, render, render_prompt

pytestmark = pytest.mark.unit

CORE_PROMPTS = ["analyst", "collector", "editor", "writer"]


def test_core_prompts_exist() -> None:
    available = prompts.list_prompts()
    for name in CORE_PROMPTS:
        assert name in available, f"缺少核心提示词模板：{name}"


@pytest.mark.parametrize("name", CORE_PROMPTS)
def test_prompt_parses_and_has_instructions(name: str) -> None:
    prompt = load_prompt(name)
    assert prompt.meta.name == name
    assert prompt.meta.title
    assert prompt.meta.description
    assert prompt.meta.tier in ("primary", "light")
    assert len(prompt.instructions) >= 3, "指令节太少，模型缺少行为约束"
    # 每条指令都应有小节标题作为语义锚点
    for block in prompt.instructions:
        assert block.startswith("【") and "】" in block


@pytest.mark.parametrize("name", CORE_PROMPTS)
def test_no_unresolved_variable_after_render(name: str) -> None:
    """带默认值的变量必须在渲染后被替换掉，不能残留 {{ }} 给模型看。"""
    prompt = load_prompt(name)
    for block in prompt.render_instructions():
        assert "{{" not in block, f"{name} 渲染后仍残留模板变量：{block[:80]}"


def test_render_uses_default_value() -> None:
    assert render("上限 {{ n | 30 }} 条") == "上限 30 条"


def test_render_overrides_default() -> None:
    assert render("上限 {{ n | 30 }} 条", n=5) == "上限 5 条"


def test_render_keeps_unknown_variable() -> None:
    """没有默认值又没传值：原样保留，方便一眼看出漏注入。"""
    assert render("主题：{{ topic }}") == "主题：{{ topic }}"


def test_prompt_variables_lists_only_required() -> None:
    """variables 只列"没有默认值"的变量。"""
    prompt = load_prompt("collector")
    assert all("{{" not in v for v in prompt.variables)
    assert "max_items" not in prompt.variables  # 它带默认值


def test_render_prompt_replaces_runtime_values() -> None:
    text = render_prompt("collector", max_items=7)
    assert "条数上限 7" in text
    assert "{{ max_items" not in text


def test_missing_prompt_raises_with_hint() -> None:
    with pytest.raises(PromptError) as exc:
        load_prompt("not-exists")
    assert "analyst" in str(exc.value), "报错信息里应列出可用模板"


def test_missing_front_matter_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "broken.md").write_text("## 没有 front matter\n- 规则一\n", encoding="utf-8")
    monkeypatch.setattr(prompts, "PROMPT_DIR", tmp_path)
    prompts.clear_cache()
    try:
        with pytest.raises(PromptError):
            load_prompt("broken")
    finally:
        prompts.clear_cache()


def test_prompt_without_sections_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "empty.md").write_text(
        "---\nname: empty\ntitle: 空\ndescription: 无指令\n---\n\n只有正文没有分节\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prompts, "PROMPT_DIR", tmp_path)
    prompts.clear_cache()
    try:
        with pytest.raises(PromptError):
            load_prompt("empty")
    finally:
        prompts.clear_cache()


def test_invalid_tier_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "bad.md").write_text(
        "---\nname: bad\ntitle: 坏\ndescription: tier 非法\ntier: turbo\n---\n\n## 规则\n- 一\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prompts, "PROMPT_DIR", tmp_path)
    prompts.clear_cache()
    try:
        with pytest.raises(PromptError):
            load_prompt("bad")
    finally:
        prompts.clear_cache()
