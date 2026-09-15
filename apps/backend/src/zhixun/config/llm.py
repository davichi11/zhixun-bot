"""模型工厂 —— 全项目统一的多模型切换入口。

为什么要有这一层？
- **单一事实来源**：模型 id / 温度 / 超时只在这里出现，避免散落各处
- **随时切换供应商**：改一行配置就能从 OpenAI 换到 DeepSeek，符合 Agno「模型无关」理念
- **分级用模型**：重活（写作/分析）用主力模型，轻活（GC/查重打标）用便宜模型，控制成本

用法：
    from zhixun.config.llm import get_model
    agent = Agent(model=get_model(), ...)
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal

from zhixun.config.logging import get_logger
from zhixun.config.settings import settings

if TYPE_CHECKING:  # pragma: no cover
    from agno.models.base import Model

logger = get_logger(__name__)

Tier = Literal["primary", "light"]


def _build(provider: str, *, model_id: str | None, tier: Tier) -> Model:
    """按 provider 构造 Agno Model 实例（延迟 import，避免缺依赖时启动失败）。"""
    temperature = settings.llm_temperature if tier == "primary" else 0.0

    if provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(
            id=model_id or settings.openai_model,
            api_key=settings.openai_api_key or None,
            temperature=temperature,
        )

    if provider == "deepseek":
        from agno.models.deepseek import DeepSeek

        return DeepSeek(
            id=model_id or settings.deepseek_model,
            api_key=settings.deepseek_api_key or None,
            temperature=temperature,
        )

    if provider == "anthropic":
        from agno.models.anthropic import Claude

        return Claude(
            id=model_id or settings.anthropic_model,
            api_key=settings.anthropic_api_key or None,
            temperature=temperature,
        )

    raise ValueError(f"不支持的 LLM provider: {provider!r}")


@lru_cache(maxsize=4)
def get_model(tier: Tier = "primary", override_id: str | None = None) -> Any:
    """获取模型实例。

    Args:
        tier: primary=主力模型（写作/分析）；light=轻量模型（GC/打标/查重）
        override_id: 临时指定 model id（一般只用于评估实验）
    """
    provider = settings.llm_provider
    if tier == "light":
        # 轻量档优先用便宜供应商，没有就退回主力供应商的 mini 系模型
        provider = "deepseek" if settings.deepseek_api_key else provider
        model_id = override_id or ("deepseek-chat" if provider == "deepseek" else "gpt-4o-mini")
    else:
        model_id = override_id

    model = _build(provider, model_id=model_id, tier=tier)
    logger.debug("llm.resolved", provider=provider, tier=tier, model=getattr(model, "id", model_id))
    return model
