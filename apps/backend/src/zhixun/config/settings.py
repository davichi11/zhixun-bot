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
    # lancedb 是可选依赖；缺失时自动降级为内存实现（几百篇规模完全够用）
    vector_backend: Literal["lancedb", "memory"] = "memory"

    # ------------------------------------------------------------ 知识层（第 4 篇）
    dedup_similarity_threshold: float = 0.85
    rag_top_k: int = 5
    # Embedding：openai = 有语义；hash = 零依赖确定性降级（无语义，仅供离线与去重兜底）
    embedding_provider: Literal["openai", "hash"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_hash_dim: int = 512
    # 去重时最多拿多少条历史项目参与标题相似度比对（越多越准，也越贵）
    dedup_max_candidates: int = 500
    # 历史文章目录（风格范文来源），相对 backend 根目录
    history_articles_dir: str = "data/history"
    # 渐进式披露：默认注入多少条范文
    context_style_samples: int = 3

    # ------------------------------------------------------------ MCP（第 6 篇）
    # ⚠️ MCP Server 的启动命令**只来自这里**，不接受运行时注入 ——
    # 它等于"在生产机器上执行任意进程"，风险等级与 SSRF 同级。
    # 相对 backend 根目录；客户端会自动用 sys.executable 拼成完整命令。
    mcp_publisher_server: str = "mcp_servers/zhixun_publisher/server.py"
    # 关掉后发布能力自动降级为内置实现，不影响流水线运行
    mcp_publisher_enabled: bool = True
    # 本账号的关注方向（运营策略，属于配置而不是业务数据）
    focus_topics: list[str] = ["大模型应用", "Agent 工程", "推理优化", "开源生态"]

    # ------------------------------------------------------------ 采集（第 3 篇）
    github_token: str = ""
    collector_max_items: int = 30

    # ------------------------------------------------------------ 工具层（第 3 篇）
    # 单次工具调用的超时与重试。三个数字构成"退避曲线"：
    # 第 n 次重试等待 tool_retry_base_delay * 2^(n-1)，再叠加 0~100% 抖动
    tool_timeout_seconds: float = 15.0
    tool_max_attempts: int = 3
    tool_retry_base_delay: float = 0.5
    # 单次 Agent 运行允许的工具调用总次数（Harness「机械强制」第一道闸）
    tool_call_budget: int = 12
    # 单个工具结果的最大字符数（超出即截断，防上下文爆炸）
    tool_result_max_chars: int = 16_000

    # 网页抓取用 Jina Reader（免费，直接返回 Markdown，无需 API key）
    jina_reader_base_url: str = "https://r.jina.ai/"
    jina_search_base_url: str = "https://s.jina.ai/"
    jina_api_key: str = ""
    # 抓取目标允许的域名后缀白名单（空列表 = 不限制，仅校验协议与内网地址）
    scraper_domain_allowlist: list[str] = []

    # ------------------------------------------------------------ 调度（第 5 篇）
    scheduler_enabled: bool = False
    weekly_report_cron: str = "0 9 * * 1"  # 每周一 09:00

    # ------------------------------------------------------------ 流水线（第 5 篇）
    # Agno Workflow 的 db 文件。**HITL 的暂停状态存在这里**，
    # 所以开发态也不能省 —— 没有它，流程挂起后无法恢复。
    workflow_db: str = "agno_workflow.db"
    # 候选少于这个数就不写一期（走 Condition 的 else 分支显式收尾）
    min_candidates: int = 3

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
