"""工具层单元测试。

原则（见第一篇 5.5 节）：**单元测试绝不联网、绝不调用真实 LLM**。
本文件覆盖四类东西：

1. 参数钳制与文本截断（Harness「能自动纠正的不要失败」）
2. URL 安全校验（Harness「不能纠正的必须拦截」）
3. 错误分类与重试判定（生产级工具的核心逻辑）
4. 按角色最小权限授权（谁能调用什么）
"""

from __future__ import annotations

import pytest

from zhixun.tools import TOOLSETS, describe_toolsets, resolve_toolset, tools_for
from zhixun.tools.builtin import load_builtin_tools
from zhixun.tools.errors import (
    FatalToolError,
    RetryableToolError,
    classify_status,
    is_retryable,
)
from zhixun.tools.guards import (
    assert_url_allowed,
    audit_tool_call,
    budget_remaining,
    clamp_int,
    clamp_text,
    redact_args,
    reset_budget,
)
from zhixun.tools.publisher import publish_draft

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- ① 参数钳制


def test_clamp_int_clamps_both_bounds() -> None:
    assert clamp_int(99999, lo=1, hi=100, name="limit") == 100
    assert clamp_int(0, lo=1, hi=100, name="limit") == 1
    assert clamp_int(42, lo=1, hi=100, name="limit") == 42


def test_clamp_int_tolerates_string_and_bad_type() -> None:
    """入口不做格式审判，只做边界保证。"""
    assert clamp_int("10", lo=1, hi=100, name="limit") == 10
    assert clamp_int("不是数字", lo=1, hi=100, name="limit") == 100  # 兜底取上界
    assert clamp_int(None, lo=1, hi=100, name="limit") == 100
    assert clamp_int(7.9, lo=1, hi=100, name="limit") == 7


def test_clamp_text_marks_truncation() -> None:
    """截断必须留痕 —— 否则模型会以为资料就这么多。"""
    text = "字" * 100
    out = clamp_text(text, max_chars=10, name="demo")
    assert out.startswith("字" * 10)
    assert "已截断" in out
    assert "100" in out


def test_clamp_text_noop_when_short() -> None:
    assert clamp_text("短文本", max_chars=100, name="demo") == "短文本"


# ---------------------------------------------------------------- ② URL 硬拦截


def test_assert_url_allowed_accepts_public_https() -> None:
    url = "https://github.com/agno-agi/agno"
    assert assert_url_allowed(url, tool="demo") == url


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://169.254.169.254/latest/meta-data/",  # 云元数据：SSRF 头号目标
        "http://127.0.0.1:8000/api/v1/drafts",  # 本机服务
        "http://192.168.1.1/admin",  # 内网
        "http://10.0.0.5/internal",  # 内网
        "file:///etc/passwd",  # 本地文件
        "ftp://example.com/x",  # 非 http 协议
    ],
)
def test_assert_url_allowed_blocks_dangerous_targets(bad_url: str) -> None:
    with pytest.raises(FatalToolError):
        assert_url_allowed(bad_url, tool="demo")


def test_assert_url_allowed_rejects_empty() -> None:
    with pytest.raises(FatalToolError):
        assert_url_allowed("   ", tool="demo")


def test_assert_url_allowed_can_opt_into_private() -> None:
    """显式 allow_private 时才放行内网 —— 默认必须是关的。"""
    url = "http://192.168.1.10/health"
    assert assert_url_allowed(url, tool="demo", allow_private=True) == url


# ---------------------------------------------------------------- ③ 错误分类


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_classify_status_retryable(status: int) -> None:
    assert classify_status(status) is RetryableToolError


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_classify_status_fatal(status: int) -> None:
    assert classify_status(status) is FatalToolError


def test_is_retryable_only_accepts_retryable_type() -> None:
    assert is_retryable(RetryableToolError("x"))
    assert not is_retryable(FatalToolError("x"))
    # 关键：普通异常默认不重试，避免"字符串匹配"式的误重试
    assert not is_retryable(ValueError("timeout happened"))


def test_tool_error_as_dict_shape() -> None:
    payload = RetryableToolError("x", tool="fetch", detail="HTTP 429").as_dict()
    assert payload["retryable"] is True
    assert payload["tool"] == "fetch"


# ---------------------------------------------------------------- ④ 审计与脱敏


def test_redact_args_hides_secrets() -> None:
    out = redact_args({"api_key": "sk-123", "token": "t", "query": "ai"})
    assert out["api_key"] == "***"
    assert out["token"] == "***"
    assert out["query"] == "ai"


def test_redact_args_truncates_long_text() -> None:
    out = redact_args({"content": "长" * 300}, keep=10)
    assert out["content"].startswith("长" * 10)
    assert "+290" in out["content"]


class _FakeFunction:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeCall:
    """最小化模拟 Agno 的 FunctionCall（只用到 function / arguments）。"""

    def __init__(self, name: str, arguments: dict | None = None) -> None:
        self.function = _FakeFunction(name)
        self.arguments = arguments or {}


def test_audit_tool_call_decrements_budget() -> None:
    reset_budget(3)
    assert budget_remaining() == 3
    audit_tool_call(_FakeCall("fetch_trending_repos", {"limit": 10}))
    assert budget_remaining() == 2


def test_audit_tool_call_raises_when_budget_exhausted() -> None:
    """预算耗尽必须**物理阻断**，而不是打条日志继续跑。"""
    from agno.exceptions import AgentRunException

    reset_budget(1)
    audit_tool_call(_FakeCall("web_search"))  # 用掉最后一次
    assert budget_remaining() == 0
    with pytest.raises(AgentRunException):
        audit_tool_call(_FakeCall("web_search"))


# ---------------------------------------------------------------- ⑤ 最小权限授权


def test_collector_gets_tools_writer_gets_none() -> None:
    assert len(tools_for("collector")) > 0
    # 写手与分析师是刻意的空工具集
    assert tools_for("writer") == []
    assert tools_for("analyst") == []


def test_editor_gets_verification_tools_only() -> None:
    names = {t.name for t in tools_for("editor")}
    assert "web_search" in names
    assert "fetch_webpage_markdown" in names
    # 编辑不该有发布权，也不该有采集权
    assert "publish_draft" not in names
    assert "fetch_trending_repos" not in names


def test_publisher_is_isolated_in_its_own_toolset() -> None:
    assert {t.name for t in tools_for("publisher")} == {"publish_draft"}
    # 只有 publisher 一个角色能拿到写操作工具
    owners = [role for role in TOOLSETS if "publish_draft" in {t.name for t in tools_for(role)}]
    assert owners == ["publisher"]


def test_resolve_toolset_rejects_unknown_role() -> None:
    """未授权角色必须报错 —— "忘记授权"和"故意不授权"是两件事。"""
    with pytest.raises(KeyError):
        resolve_toolset("hacker")


def test_describe_toolsets_shape() -> None:
    rows = describe_toolsets()
    assert {r["role"] for r in rows} == set(TOOLSETS)
    for row in rows:
        assert row["reason"], f"{row['role']} 必须说明授权理由"


# ---------------------------------------------------------------- ⑥ 可选依赖降级


def test_load_builtin_unknown_name_degrades_without_raising() -> None:
    """未知工具包不能抛异常，只能被记进 missing。"""
    result = load_builtin_tools(["不存在的工具包"])
    assert result.tools == []
    assert "不存在的工具包" in result.missing
    assert not result.ok


def test_load_builtin_reports_missing_dependency() -> None:
    """缺可选依赖时给出 pip 安装提示，且不影响其他工具加载。"""
    result = load_builtin_tools(["duckduckgo", "hackernews"])
    if "duckduckgo" in result.missing:
        assert "pip install" in result.missing["duckduckgo"]


# ---------------------------------------------------------------- ⑦ 工具行为


def test_publish_requires_human_approval() -> None:
    """机械强制第一课：没有人工审批标记就不许发。"""
    out = publish_draft.entrypoint(
        platform="wechat", title="标题", content="正文" * 40, approved_by_human=False
    )
    assert out["ok"] is False
    assert "人工审批" in out["reason"]


def test_publish_rejects_unknown_platform() -> None:
    with pytest.raises(FatalToolError):
        publish_draft.entrypoint(
            platform="tiktok", title="标题", content="正文" * 40, approved_by_human=True
        )


def test_publish_rejects_too_short_content() -> None:
    out = publish_draft.entrypoint(
        platform="wechat", title="标题", content="太短", approved_by_human=True
    )
    assert out["ok"] is False
    assert "过短" in out["reason"]


def test_publish_rejects_empty_title() -> None:
    out = publish_draft.entrypoint(
        platform="wechat", title="  ", content="正文" * 40, approved_by_human=True
    )
    assert out["ok"] is False


def test_publish_is_marked_as_side_effect() -> None:
    """写操作工具必须带 side-effect 标记（装饰器不支持，建后补的）。"""
    assert publish_draft.has_side_effects is True


def test_repo_readme_rejects_malformed_name() -> None:
    from zhixun.tools.github import get_repo_readme

    with pytest.raises(FatalToolError):
        get_repo_readme.entrypoint(full_name="https://github.com/a/b/c/d")


def test_scraper_blocks_private_url_before_network() -> None:
    """护栏在联网之前生效 —— 这条断言证明拦截没有依赖网络。"""
    from zhixun.tools.scraper import fetch_webpage_markdown

    with pytest.raises(FatalToolError):
        fetch_webpage_markdown.entrypoint(url="http://169.254.169.254/latest/meta-data/")


def test_github_merges_topics_and_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    """多 topic 分路查询：同一仓库出现在两个 topic 里只保留一条。"""
    from zhixun.tools import github as gh

    calls: list[dict] = []

    def fake_request_json(url, *, tool="", params=None, headers=None, **kwargs):  # noqa: ANN001, ANN003
        calls.append(params or {})
        q = (params or {}).get("q", "")
        if "topic:ai" in q:
            return {
                "items": [
                    {"full_name": "a/dup", "html_url": "u1", "stargazers_count": 10},
                    {"full_name": "a/only-ai", "html_url": "u2", "stargazers_count": 5},
                ]
            }
        if "topic:llm" in q:
            # a/dup 同时带 ai 和 llm 两个 topic
            return {"items": [{"full_name": "a/dup", "html_url": "u1", "stargazers_count": 10}]}
        return {"items": []}

    monkeypatch.setattr(gh, "request_json", fake_request_json)

    out = gh.fetch_trending_repos.entrypoint(days=7, limit=10, topics=["ai", "llm", "agent"])
    names = [i["full_name"] for i in out["items"]]
    assert names.count("a/dup") == 1
    assert out["count"] == 2
    # 按 star 降序
    assert names[0] == "a/dup"
    assert len(calls) == 3  # 三个 topic 各一次请求


def test_github_clamps_topics_and_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """模型给 30 个 topic / limit=99999 都不能把接口打爆。"""
    from zhixun.tools import github as gh

    seen: list[int] = []

    def fake_request_json(url, *, tool="", params=None, headers=None, **kwargs):  # noqa: ANN001, ANN003
        seen.append(params["per_page"])
        return {"items": []}

    monkeypatch.setattr(gh, "request_json", fake_request_json)

    gh.fetch_trending_repos.entrypoint(
        days=3650, limit=99999, topics=[f"t{i}" for i in range(30)]
    )
    # 最多 5 路查询，每路 per_page 不超过 100
    assert len(seen) == gh.MAX_TOPICS
    assert max(seen) <= gh.GITHUB_MAX_PER_PAGE


def test_github_partial_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """一个 topic 挂了，其余 topic 的结果照常返回（部分成功）。"""
    from zhixun.tools import github as gh
    from zhixun.tools.errors import RetryableToolError

    def fake_request_json(url, *, tool="", params=None, headers=None, **kwargs):  # noqa: ANN001, ANN003
        if "topic:llm" in params["q"]:
            raise RetryableToolError("boom", tool="fetch_trending_repos", detail="HTTP 503")
        return {"items": [{"full_name": "a/ok", "html_url": "u", "stargazers_count": 7}]}

    monkeypatch.setattr(gh, "request_json", fake_request_json)

    out = gh.fetch_trending_repos.entrypoint(topics=["ai", "llm"])
    assert out["ok"] is True
    assert out["count"] == 1
    assert len(out["failed_sources"]) == 1
    assert "llm" in out["failed_sources"][0]


def test_search_rejects_empty_query() -> None:
    from zhixun.tools.search import web_search

    out = web_search.entrypoint(query="  ")
    assert out["ok"] is False
    assert out["error"]


def test_all_tools_have_audit_hook() -> None:
    """审计钩子必须挂在每一个工具上 —— 漏一个就等于漏了一条调用记录。"""
    from zhixun.tools import TOOL_GROUPS

    for group, tools in TOOL_GROUPS.items():
        for t in tools:
            assert t.pre_hook is not None, f"{group}/{t.name} 缺少审计 pre_hook"
