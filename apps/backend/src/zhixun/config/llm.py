"""模型工厂 —— 全项目统一的多模型切换入口。

为什么要有这一层？
- **单一事实来源**：模型 id / 温度 / 超时只在这里出现，避免散落各处
- **随时切换供应商**：改一行配置就能从 OpenAI 换到 DeepSeek，符合 Agno「模型无关」理念
- **分级用模型**：重活（写作/分析）用主力模型，轻活（采集/查重打标）用便宜模型，控制成本

Agno 3.x 适配要点：
- 模型类构造签名未变（`OpenAIChat(id=..., api_key=..., temperature=...)`），
  但**默认 model id 已整体换代**（gpt-5.x / deepseek-v4），所以这里不再硬编码 id，
  一律从 `settings` 读取，升级框架时只改配置不动代码。
- 延迟 import：只有真正用到某个 provider 时才 import 对应 SDK，
  缺 `anthropic` 之类的可选依赖不会让整个服务起不来。

用法：
    from zhixun.config.llm import get_model
    agent = Agent(model=get_model("primary"), ...)
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

# tier → 各 provider 的配置字段名与 API key 字段名
_MODEL_FIELDS: dict[str, dict[str, str]] = {
    "openai": {"primary": "openai_model", "light": "openai_light_model"},
    "deepseek": {"primary": "deepseek_model", "light": "deepseek_light_model"},
    "anthropic": {"primary": "anthropic_model", "light": "anthropic_model"},
}
_API_KEY_FIELDS = {
    "openai": "openai_api_key",
    "deepseek": "deepseek_api_key",
    "anthropic": "anthropic_api_key",
}


def _resolve_provider(tier: Tier) -> str:
    """决定这一档用哪个供应商。

    light 档如果配了 DeepSeek key，就优先走 DeepSeek —— 采集、打标、查重这类
    机械活没必要烧主力模型的额度。
    """
    if tier == "light" and settings.deepseek_api_key:
        return "deepseek"
    return settings.llm_provider


def _resolve_model_id(provider: str, tier: Tier, override_id: str | None) -> str:
    if override_id:
        return override_id
    return str(getattr(settings, _MODEL_FIELDS[provider][tier]))


def _build(provider: str, *, model_id: str, tier: Tier) -> Model:
    """按 provider 构造 Agno Model 实例（延迟 import，避免缺依赖时启动失败）。"""
    temperature = settings.llm_temperature if tier == "primary" else 0.0
    api_key = getattr(settings, _API_KEY_FIELDS[provider]) or None
    if not api_key:
        logger.warning("llm.missing_api_key", provider=provider, tier=tier)

    if provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=model_id, api_key=api_key, temperature=temperature)

    if provider == "deepseek":
        from agno.models.deepseek import DeepSeek

        return DeepSeek(id=model_id, api_key=api_key, temperature=temperature)

    if provider == "anthropic":
        from agno.models.anthropic import Claude

        return Claude(id=model_id, api_key=api_key, temperature=temperature)

    raise ValueError(f"不支持的 LLM provider: {provider!r}")


@lru_cache(maxsize=8)
def get_model(tier: Tier = "primary", override_id: str | None = None) -> Any:
    """获取模型实例（带缓存，同一档位全局复用一个实例）。

    Args:
        tier: primary=主力模型（写作/分析）；light=轻量模型（采集/打标/查重）
        override_id: 临时指定 model id（一般只用于评估实验）
    """
    provider = _resolve_provider(tier)
    model_id = _resolve_model_id(provider, tier, override_id)
    model = _build(provider, model_id=model_id, tier=tier)
    logger.debug("llm.resolved", provider=provider, tier=tier, model=model_id)
    return model


def describe() -> dict[str, str]:
    """返回当前生效的模型矩阵（给 CLI / 监控面板展示，不实例化模型）。"""
    out: dict[str, str] = {}
    for tier in ("primary", "light"):
        provider = _resolve_provider(tier)  # type: ignore[arg-type]
        out[tier] = f"{provider}:{_resolve_model_id(provider, tier, None)}"
    return out


def reset_cache() -> None:
    """清空模型缓存（切换配置 / 测试时使用）。"""
    get_model.cache_clear()
