"""Harness 支柱二 · 机械强制（Mechanical Enforcement）。

核心思想：**用代码物理拦截，而不是用提示词"恳求"模型别乱来。**

两类护栏：
1. 输入/输出护栏（Guard）：敏感词、事实核查、格式 Linter
2. 工具护栏（ToolGuard）：危险参数的输入校验，写操作必须人工批准

拦截后不是"报错退出"，而是**把修复指令注入上下文，触发自我修复循环**。

第 1 篇：定义协议。
第 3 篇：落地工具参数护栏（配合 `tools/publisher`）。
第 7 篇：落地内容质量护栏 Agent，接入中间件链。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from zhixun.config.logging import get_logger

logger = get_logger(__name__)

# 高危函数 / 模式（示例，第 7 篇会外置成规则文件）
FORBIDDEN_PATTERNS = ("eval(", "exec(", "os.system(", "rm -rf")


@dataclass(slots=True)
class GuardResult:
    """护栏检查结果。"""

    ok: bool
    level: str = "info"  # info / warn / block
    violations: list[str] = field(default_factory=list)
    feedback: str = ""  # 注入给模型的修复指令


@runtime_checkable
class Guard(Protocol):
    """护栏协议。"""

    name: str

    def check(self, *, text: str, meta: dict[str, object] | None = None) -> GuardResult: ...


class ContentFormatGuard:
    """格式与安全 Linter（机械强制示例）。"""

    name = "content_format_guard"

    def check(self, *, text: str, meta: dict[str, object] | None = None) -> GuardResult:
        violations = [p for p in FORBIDDEN_PATTERNS if p in text]
        if violations:
            return GuardResult(
                ok=False,
                level="block",
                violations=violations,
                feedback=(
                    f"系统拦截：检测到危险模式 {violations}。"
                    "请移除这些内容后重新生成，不要解释拦截原因。"
                ),
            )
        if not text.strip():
            return GuardResult(ok=False, level="warn", violations=["空内容"], feedback="内容为空")
        return GuardResult(ok=True)

    # TODO(第 7 篇): 补齐敏感词库外置、事实核查 Agent、标题长度/emoji 规范
