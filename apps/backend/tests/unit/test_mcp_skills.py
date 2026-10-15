"""MCP 与 Skills 层测试（第 6 篇）。

原则：不联网、不启动外部进程、不依赖 LLM。
真实 MCP 连接由 `mcp_servers/zhixun_publisher/server.py` 的独立验证脚本覆盖，
单测只测**编排逻辑与降级路径**。
"""

from __future__ import annotations

import pytest

from zhixun.mcp import (
    describe_mcp_servers,
    load_mcp_tools,
    load_publisher_tools,
    mcp_available,
)
from zhixun.skills import SKILLS_BY_AGENT, describe_skills, get_skills, skills_for_agent

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- MCP


def test_mcp_server_registry_has_publisher() -> None:
    rows = describe_mcp_servers()
    assert rows, "MCP Server 注册表不应为空"
    names = [r["name"] for r in rows]
    assert "zhixun-publisher" in names


def test_mcp_command_comes_from_config_not_input() -> None:
    """回归防护：MCP 启动命令必须只来自配置。

    它等于"在生产机器上执行任意进程"，风险等级与 SSRF 同级，
    所以绝不能开放运行时注入入口。
    """
    row = next(r for r in describe_mcp_servers() if r["name"] == "zhixun-publisher")
    assert str(row["command"]).endswith("mcp_servers/zhixun_publisher/server.py")


def test_mcp_availability_reports_hint_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺依赖时必须给出 pip 提示（降级要可见）。"""
    import zhixun.mcp as m

    monkeypatch.setattr(m, "mcp_available", lambda: False)
    rows = describe_mcp_servers()
    assert all(not r["ready"] for r in rows)
    assert all("pip install" in r["hint"] for r in rows)


async def test_load_mcp_degrades_without_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP 不可用时返回空结果而非抛异常 —— 主进程必须能起来。"""
    import zhixun.mcp as m

    monkeypatch.setattr(m, "mcp_available", lambda: False)
    result = await load_publisher_tools()

    assert result.ok is False
    assert result.tools == []
    assert "降级" in result.unavailable_reason


async def test_load_mcp_unknown_server_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """未注册的 Server 名字要进 failed，不能静默跳过。"""
    import zhixun.mcp as m

    monkeypatch.setattr(m, "mcp_available", lambda: True)
    result = await load_mcp_tools(names=["不存在的服务"])

    assert "不存在的服务" in result.failed
    assert result.ok is False


def test_mcp_available_checks_both_packages() -> None:
    """认知固化：Agno 的 MCP 客户端依赖 fastmcp，不只是 mcp。

    只装 mcp 时会在 `_build_fastmcp_client()` 处抛 ImportError。
    """
    ok = mcp_available()
    if not ok:
        from importlib.util import find_spec

        assert find_spec("mcp") is None or find_spec("fastmcp") is None


# ---------------------------------------------------------------- 发布：MCP 降级路径


def test_publish_blocks_when_mcp_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP 不可用时**必须阻止发布并明确说明**，不能假装成功。

    这是第三篇"降级必须诚实"原则在第六篇的延续 ——
    发布是不可逆操作，"发不出去"比"假装发了"好一万倍。
    """
    import zhixun.tools.publisher as pub

    monkeypatch.setattr(pub, "_publish_via_mcp", lambda **kw: None)
    out = pub.publish_draft.entrypoint(
        platform="wechat", title="标题", content="正文" * 200, approved_by_human=True
    )
    assert out["ok"] is False
    assert "MCP" in out["reason"]


def test_publish_returns_mcp_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP 返回的结构化 payload 要被正确透传。"""
    import zhixun.tools.publisher as pub

    monkeypatch.setattr(
        pub,
        "_publish_via_mcp",
        lambda **kw: {"ok": True, "platform": "wechat", "draft_id": "wechat-123", "reason": ""},
    )
    out = pub.publish_draft.entrypoint(
        platform="wechat", title="标题", content="正文" * 200, approved_by_human=True
    )
    assert out["ok"] is True
    assert out["draft_id"] == "wechat-123"


def test_publish_approval_gate_still_blocks_before_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    """闸门②必须在调 MCP **之前**生效 —— 未审批不该触发任何外部调用。"""
    import zhixun.tools.publisher as pub

    called = []
    monkeypatch.setattr(pub, "_publish_via_mcp", lambda **kw: called.append(kw))
    out = pub.publish_draft.entrypoint(
        platform="wechat", title="标题", content="正文" * 200, approved_by_human=False
    )
    assert out["ok"] is False
    assert called == [], "未审批时不应调用 MCP"


def test_mcp_payload_extraction_prefers_structured() -> None:
    """优先用框架已解析的 structured_content，退回字符串解析。"""
    from zhixun.tools.publisher import _extract_mcp_payload

    class _Raw:
        content = '{"ok": true, "from": "string"}'
        metadata = {"structured_content": {"ok": True, "from": "structured"}}

    assert _extract_mcp_payload(_Raw())["from"] == "structured"

    class _RawNoMeta:
        content = '{"ok": true, "from": "string"}'
        metadata = None

    assert _extract_mcp_payload(_RawNoMeta())["from"] == "string"


# ---------------------------------------------------------------- Skills


def test_skills_are_discoverable() -> None:
    info = describe_skills()
    assert info.available, "技能目录不可用"
    assert {"wechat-format", "tech-fact-check", "cover-design"} <= set(info.names)


def test_skill_metadata_has_required_fields() -> None:
    """SKILL.md 的 frontmatter 必须有 name / description / instructions。"""
    collection = get_skills()
    assert collection is not None
    for name in collection.get_skill_names():
        skill = collection.get_skill(name)
        assert skill is not None, f"{name} 加载失败"
        assert skill.name
        assert skill.description
        assert len(skill.instructions) > 100, f"{name} 的正文过短"


def test_skills_allowed_tools_use_mcp_prefixed_names() -> None:
    """技能里声明的工具名必须与 MCP 实际暴露的一致。

    Agno 的 `tool_name_prefix` 会再补一个下划线分隔符，
    所以真实名字是 `zhixun-publisher__render_markdown`（**双下划线**）。
    这个不一致很容易写错，所以用测试钉住。
    """
    collection = get_skills()
    assert collection is not None
    fmt = collection.get_skill("wechat-format")
    assert fmt is not None
    assert "zhixun-publisher__render_markdown" in (fmt.allowed_tools or [])


def test_skills_assigned_by_role_with_least_privilege() -> None:
    """延续第三篇"最小权限"：采集员与分析师不该挂任何技能。"""
    assert SKILLS_BY_AGENT["collector"] == ()
    assert SKILLS_BY_AGENT["analyst"] == ()
    assert SKILLS_BY_AGENT["writer"] == ("wechat-format",)
    assert SKILLS_BY_AGENT["editor"] == ("tech-fact-check",)


def test_skills_for_agent_returns_none_when_unassigned() -> None:
    assert skills_for_agent("collector") is None


def test_skills_for_agent_rejects_unknown_role() -> None:
    """未配置的角色要报错 —— "忘记配置"和"故意不配置"是两件事。"""
    with pytest.raises(KeyError):
        skills_for_agent("不存在的角色")


def test_agents_get_skills_mounted() -> None:
    """写手与编辑应挂上技能，采集员不应有。"""
    from zhixun.agents import build_agent_by_role

    writer = build_agent_by_role("writer")
    editor = build_agent_by_role("editor")
    collector = build_agent_by_role("collector")

    assert getattr(writer, "skills", None) is not None
    assert "wechat-format" in writer.skills.get_skill_names()
    assert "tech-fact-check" in editor.skills.get_skill_names()
    assert getattr(collector, "skills", None) is None


def test_build_agent_can_skip_skills() -> None:
    """测试要能拿到完全离线的 Agent（不挂技能）。"""
    from zhixun.agents import build_agent_by_role

    agent = build_agent_by_role("writer", with_skills=False)
    assert getattr(agent, "skills", None) is None