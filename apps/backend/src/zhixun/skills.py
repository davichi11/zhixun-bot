"""Skills 接入层 —— 把"怎么做好某件事"从提示词里搬出来。

## 为什么需要 Skills（而不是继续写在提示词里）

第二篇我们把提示词外置成了 `.md` 文件。第四篇的知识层解决"Agent 知道什么"，
第五篇的编排解决"步骤怎么走"。但还有一个问题没解决：

> **"怎么写一篇好的技术文章"这种知识，该放哪？**

塞进 `prompts/writer.md`？问题有三个：

1. **它是可选的** —— 采集员完全不需要"公众号排版规范"
2. **它会污染提示词** —— 全量注入意味着每次调用都带着 3000 token 的排版规则
3. **它有生命周期** —— 技能会独立迭代（改排版规范不用动写手人格）

Skills 正好解决这三点：**按需注入、按角色挂载、独立版本**。

## 本项目的挂载策略

延续第三篇的"按角色最小权限"思路：

| Agent | 挂哪些技能 | 为什么 |
|---|---|---|
| `collector` | （无） | 采集不需要排版和核查 |
| `analyst` | （无） | 打分是结构化的，不需要叙事规范 |
| `writer` | `wechat-format` | 它决定结构与段落 |
| `editor` | `tech-fact-check` | 审校的核心就是核实事实 |
| 流水线末端 | `cover-design` | 封面是发布前的最后一步 |

> **技能是"按需加载的说明书"，不是"常驻的系统提示"。**
> 把所有技能塞给所有 Agent，等于回到"全局工具表"的错误。

## 一个实测坑：allowed-tools 必须是 YAML 列表

```markdown
# ❌ 校验失败：Field 'allowed-tools' must be a list
allowed-tools: web_search, fetch_webpage_markdown

# ✅ 正确
allowed-tools:
  - web_search
  - fetch_webpage_markdown
```

行内逗号分隔的写法会直接抛 `SkillValidationError`。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zhixun.config.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "SKILLS_DIR",
    "SKILLS_BY_AGENT",
    "describe_skills",
    "get_skills",
    "skills_for_agent",
]

# 技能目录：相对 apps/backend
SKILLS_DIR = "skills"

# 角色 → 技能名（第 3 篇"最小权限"思路在技能层的延续）
SKILLS_BY_AGENT: dict[str, tuple[str, ...]] = {
    "collector": (),
    "analyst": (),
    "writer": ("wechat-format",),
    "editor": ("tech-fact-check",),
    # 发布环节由流水线末端负责，不绑定到某个 Agent
    "publisher": ("cover-design",),
}


@dataclass(slots=True)
class SkillsInfo:
    """技能清单（给 CLI 与文档站展示）。"""

    available: bool
    names: list[str]
    by_agent: dict[str, list[str]]
    detail: list[dict[str, Any]]
    error: str = ""


def _skills_root() -> Path:
    from zhixun.config.settings import BACKEND_ROOT

    return BACKEND_ROOT / SKILLS_DIR


def skills_available() -> bool:
    """技能目录是否存在且非空。"""
    root = _skills_root()
    return root.exists() and any(root.glob("*/SKILL.md"))


def get_skills(*, names: tuple[str, ...] | None = None) -> Any | None:
    """加载技能集合。

    Args:
        names: 只要这些技能；不传则全量加载

    Returns:
        `agno.skills.Skills` 实例；技能不可用时返回 `None`（调用方降级）

    Notes:
        ⚠️ `LocalSkills` 是**加载器**，不是集合 —— 必须用 `Skills([...])` 包装。
        直接调 `LocalSkills.get_skill_names()` 会 AttributeError。
    """
    root = _skills_root()
    if not (root.exists() and any(root.glob("*/SKILL.md"))):
        logger.warning("skills.no_dir", root=str(root))
        return None

    try:
        from agno.skills import LocalSkills, Skills as SkillsCollection

        collection = SkillsCollection([LocalSkills(str(root), validate=True)])
        loaded = collection.get_skill_names()

        if names:
            missing = set(names) - set(loaded)
            if missing:
                logger.warning("skills.missing", missing=sorted(missing))
            # 目录级过滤：每个技能一个子目录，按名字精确取
            keep = {n: _skills_root() / n for n in names if (root / n / "SKILL.md").exists()}
            if not keep:
                return None
            collection = SkillsCollection([LocalSkills(str(p), validate=True) for p in keep.values()])

        logger.info("skills.loaded", count=len(collection.get_skill_names()))
        return collection
    except Exception as exc:  # noqa: BLE001 - 技能不可用不该阻断服务
        logger.warning("skills.load_failed", error=str(exc))
        return None


def skills_for_agent(role: str) -> Any | None:
    """按角色取技能 —— 与 `tools_for(role)` 同一套思路。"""
    names = SKILLS_BY_AGENT.get(role)
    if names is None:
        raise KeyError(f"未配置技能的角色：{role!r}。可用：{sorted(SKILLS_BY_AGENT)}")
    if not names:
        return None
    return get_skills(names=names)


def describe_skills() -> SkillsInfo:
    """给 CLI 展示（不抛异常）。"""
    collection = get_skills()
    if collection is None:
        return SkillsInfo(
            available=False,
            names=[],
            by_agent={k: list(v) for k, v in SKILLS_BY_AGENT.items()},
            detail=[],
            error=f"技能目录不可用：{_skills_root()}",
        )

    detail: list[dict[str, Any]] = []
    for name in collection.get_skill_names():
        skill = collection.get_skill(name)
        detail.append(
            {
                "name": name,
                "description": skill.description[:80] if skill else "",
                "allowed_tools": ", ".join(skill.allowed_tools or []) if skill else "",
                "chars": len(skill.instructions) if skill else 0,
            }
        )

    return SkillsInfo(
        available=True,
        names=collection.get_skill_names(),
        by_agent={k: list(v) for k, v in SKILLS_BY_AGENT.items()},
        detail=detail,
    )
