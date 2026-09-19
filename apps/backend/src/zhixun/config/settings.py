"""全局配置（唯一来源）。

约定（见第一篇 5.2 节）：
- 所有配置都在这里声明，**任何业务代码都不直接读 os.environ**
- 通过 `from zhixun.config.settings import settings` 获取全局单例

第 1 篇只是把配置骨架立起来，具体字段会随各篇逐步补齐。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 路径推导：config/settings.py 位于 <repo>/apps/backend/src/zhixun/config/settings.py
#   parents[0]=config  [1]=zhixun  [2]=src  [3]=backend  [4]=apps  [5]=<repo>
REPO_ROOT = Path(__file__).resolve().parents[5]
BACKEND_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """智讯助手全局配置。"""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------ 运行环境
    app_name: str = "智讯助手"
    env: Literal["dev", "staging", "prod"] = "dev"
    debug: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_prefix: str = "/api/v1"

    # ------------------------------------------------------------ LLM
    # 模型 id 一律以 Agno 3.x 的默认为基准，升级框架时只需改这里
    llm_provider: Literal["openai", "deepseek", "anthropic"] = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4"
    openai_light_model: str = "gpt-5.4-mini"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_light_model: str = "deepseek-v4-flash"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    llm_temperature: float = 0.3

    # ------------------------------------------------------------ 数据库
    # 开发态默认 SQLite，生产态切 Postgres（第 4 篇展开）
    database_url: str = f"sqlite+aiosqlite:///{BACKEND_ROOT / 'zhixun.db'}"

    # ------------------------------------------------------------ 向量库
    vector_db_uri: str = str(BACKEND_ROOT / ".lancedb")
    vector_table_articles: str = "historical_articles"

    # ------------------------------------------------------------ 知识层（第 4 篇）
    dedup_similarity_threshold: float = 0.85
    rag_top_k: int = 5

    # ------------------------------------------------------------ 采集（第 3 篇）
    github_token: str = ""
    collector_max_items: int = 30

    # ------------------------------------------------------------ 调度（第 5 篇）
    scheduler_enabled: bool = False
    weekly_report_cron: str = "0 9 * * 1"  # 每周一 09:00

    # ------------------------------------------------------------ Agent 层（第 2 篇）
    # 提示词模板目录（相对 backend 根目录），支持按 env 覆盖做 A/B 实验
    prompts_dir: str = "src/zhixun/prompts"
    # 生产环境关闭"内联提示词"，强制所有 Agent 从模板加载，避免提示词散落
    allow_inline_prompts: bool = False

    # ------------------------------------------------------------ Harness（第 7 篇）
    enable_harness: bool = True
    context_unload_threshold: float = 0.85
    context_max_tokens: int = 128_000
    # Agno 3.x 原生能力：工具结果超过阈值即卸载到 AgentFS，只留信封（preview+size+result_id）
    # 这是"动态上下文工程"第一道防线，第 7 篇会在其之上叠加渐进式披露
    offload_tool_results: bool = True
    tool_offload_threshold_chars: int = 16_000
    # Agno 3.x 原生护栏（PromptInjection / PII / Moderation），第 7 篇接入
    enable_native_guardrails: bool = False
    # 在 Agent 上启用 CodeMode（工具多且需要组合调用时才开，默认关闭）
    enable_code_mode: bool = False

    # ------------------------------------------------------------ 便捷属性
    @property
    def is_dev(self) -> bool:
        return self.env == "dev"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """带缓存的配置读取（测试里可用 get_settings.cache_clear() 重置）。"""
    return Settings()


settings = get_settings()
