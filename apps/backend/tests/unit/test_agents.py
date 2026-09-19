"""Agent 层单元测试。

原则（见第一篇 5.5 节）：**单元测试绝不调用真实 LLM**。
本文件只验证"装配逻辑"与"输出契约"，真正跑模型属于 e2e（默认跳过）。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from zhixun.agents import (
    AGENT_BUILDERS,
    SPECS,
    AnalysisResult,
    CollectResult,
    ReviewIssue,
    ReviewResult,
    audit_specs,
    build_agent_by_role,
    content_to_text,
    run_text,
    spec_from_prompt,
    spec_summary,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- 注册表 / 治理


def test_registry_covers_four_core_agents() -> None:
    assert set(SPECS) == {"collector", "analyst", "writer", "editor"}
    assert set(AGENT_BUILDERS) == set(SPECS)


def test_audit_specs_passes() -> None:
    """提示词治理自检必须零问题 —— 这条建议挂进 CI。"""
    assert audit_specs() == []


def test_every_spec_is_prompt_backed() -> None:
    for key, spec in SPECS.items():
        assert spec.is_prompt_backed, f"{key} 未绑定提示词模板"
        assert spec.prompt_version >= 1


def test_agent_names_unique() -> None:
    names = [s.name for s in SPECS.values()]
    assert len(names) == len(set(names))


# ---------------------------------------------------------------- 规格装配


def test_spec_from_prompt_takes_meta_from_template() -> None:
    spec = spec_from_prompt("analyst", output_schema=AnalysisResult)
    assert spec.name == "分析师"
    assert spec.role == "analyst"
    assert spec.tier == "primary"
    assert spec.description
    assert spec.instructions


def test_collector_uses_light_tier() -> None:
    """采集是机械活，必须走便宜模型 —— 这是成本设计的一部分。"""
    assert SPECS["collector"].tier == "light"
    assert SPECS["analyst"].tier == "primary"


def test_only_structured_agents_have_schema() -> None:
    """写手故意不设 output_schema：文章不该被 schema 框死。"""
    assert SPECS["collector"].output_schema is CollectResult
    assert SPECS["analyst"].output_schema is AnalysisResult
    assert SPECS["editor"].output_schema is ReviewResult
    assert SPECS["writer"].output_schema is None


def test_spec_from_prompt_injects_variables() -> None:
    spec = spec_from_prompt("analyst", variables={"top_n": 3, "focus_topics": "推理优化"})
    joined = "\n".join(spec.instructions)
    assert "3 条以内" in joined
    assert "推理优化" in joined
    assert "{{" not in joined


def test_extra_instructions_appended_last() -> None:
    spec = spec_from_prompt("writer", extra_instructions=["本期不要提到公司名"])
    assert spec.instructions[-1] == "本期不要提到公司名"


def test_spec_summary_shape() -> None:
    summary = spec_summary(SPECS["editor"])
    assert summary["schema"] == "ReviewResult"
    assert summary["prompt"] == "editor"


def test_build_agent_by_role_unknown_raises() -> None:
    with pytest.raises(KeyError):
        build_agent_by_role("nope")


# ---------------------------------------------------------------- 真实构造


def test_build_analyzer_with_real_agno() -> None:
    """用真实 Agno 类构造（不发网络请求），验证工厂参数确实被接受。"""
    agent = build_agent_by_role("analyst", top_n=4)
    assert agent.name == "分析师"
    assert agent.output_schema is AnalysisResult
    assert agent.instructions
    assert "{{" not in "\n".join(agent.instructions)


def test_all_agents_build_without_error() -> None:
    for role in AGENT_BUILDERS:
        agent = build_agent_by_role(role)
        assert agent.name
        assert agent.model is not None


# ---------------------------------------------------------------- 输出契约


def test_analysis_result_rejects_out_of_range_score() -> None:
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(
            {
                "items": [
                    {
                        "repo": "a/b",
                        "score": 99,  # 超过 10
                        "novelty": 1,
                        "relevance": 1,
                        "momentum": 1,
                        "reason": "x",
                    }
                ],
                "summary": "s",
            }
        )


def test_collect_result_defaults() -> None:
    result = CollectResult.model_validate({"items": [{"name": "a/b", "url": "u"}]})
    assert result.items[0].stars is None
    assert result.failed_sources == []


def test_review_result_helpers() -> None:
    result = ReviewResult(
        passed=False,
        issues=[
            ReviewIssue(level="blocker", category="fact", detail="star 数不符", suggestion="改为 1200"),
            ReviewIssue(level="minor", category="format", detail="缺反引号", suggestion="补上"),
        ],
    )
    assert len(result.blockers) == 1
    assert result.by_category == {"fact": 1, "format": 1}


# ---------------------------------------------------------------- 运行辅助


class _FakeOutput:
    content = "生成的稿件正文"


class _FakeAgent:
    def run(self, message, **kwargs):  # noqa: ANN001, ANN003
        return _FakeOutput()


def test_run_text_extracts_content() -> None:
    assert run_text(_FakeAgent(), "写点什么") == "生成的稿件正文"


def test_content_to_text_handles_pydantic_and_none() -> None:
    assert content_to_text(None) == ""
    assert content_to_text("abc") == "abc"
    dumped = content_to_text(CollectResult())
    assert "items" in dumped
