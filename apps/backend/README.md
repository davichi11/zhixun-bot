# 智讯助手 · 后端（zhixun-backend）

Agno 业务核心：Agent 定义、工具系统、知识层、流水线、Harness 驾驭层、HTTP API 与调度器。

> 框架基线：**Agno 3.1.x**（`agno>=3.1.2`）。v3 是破坏性版本，升级前请先读 `../../docs/architecture.md` 的 ADR-007 与 ADR-016~018。

## 快速开始

```bash
# 1. 安装依赖（推荐 uv）
uv sync --extra dev

# 2. 配置环境变量
cp ../../.env.example ../../.env    # 填好 OPENAI_API_KEY 或 DEEPSEEK_API_KEY

# 3. 看一眼所有 Agent 与提示词（不需要 API key）
uv run zhixun agents --list
uv run zhixun agents --audit                  # 提示词治理自检，建议挂 CI
uv run zhixun agents --show-prompt analyst    # 打印渲染后的完整提示词

# 4. 看一眼工具授权表与内置工具可用性（不需要联网）
uv run zhixun tools --list
uv run zhixun tools --builtin                 # 缺哪些可选依赖，会给出 pip 提示

# 5. 单独调一个工具（真联网）
uv run zhixun tools --call fetch_trending_repos --arg days=7 --arg limit=3

# 5. 跑一次干运行（不发布、不调 LLM）
uv run zhixun run --dry-run --skip-review --issue 42

# 6. 正式跑（会在"人工审校"处挂起）
uv run zhixun run --dry-run --issue 43
#   → 提示：uv run zhixun approve <run_id> --session-id <sid>

# 7. 人工审批（通过 / 驳回）
uv run zhixun approve <run_id> --session-id <sid>
uv run zhixun approve --latest --reject --feedback "数据不准"

# 8. 启动 API
uv run zhixun serve --reload
#   文档：http://127.0.0.1:8000/docs
```

## 流水线编排（第 5 篇）

**Workflow 主导 + Team 局部嵌套**（ADR-002 / ADR-016~018）：

```
① 采集 → ② 筛选 → [Condition: 候选 ≥ 3 → ③ 摘要 + ④ 改写（Team）/ else 显式收尾]
                    → ⑤ 审校（顶层 HumanReview，⏸ 挂起等人工）→ ⑥ 发布
```

两个**实测得到**的框架行为（都有回归测试守着）：

| 行为 | 后果 | 本项目的处理 |
|---|---|---|
| `HumanReview` 嵌在 `Condition` 内**不生效** | 会静默自动发布且不报错 | 审校步骤提到顶层 |
| `on_reject="skip"` **不阻止后续步骤** | 人工驳回后发布仍会执行 | 改用 `on_reject="cancel"` |

另外：`Step.max_retries` **默认 3 次**，且失败步骤的后续步骤总会执行 ——
**"框架会替你把住发布这道门"是错觉，闸门必须自己写。**

## 工具系统（第 3 篇）

工具**按角色授权**，不存在"全局工具表"（理由见 ADR-008）：

| 角色 | 授予的工具 |
|---|---|
| `collector` | `fetch_trending_repos` / `get_repo_readme` / `web_search` / `hackers_news` |
| `analyst` | （无 —— 刻意的） |
| `writer` | （无 —— 刻意的） |
| `editor` | `web_search` / `fetch_webpage_markdown` |
| `publisher` | `publish_draft`（唯一写操作） |

三层护栏（理由见 ADR-009）：

```
tools/guards.py
├── clamp_int / clamp_text     ① 参数钳制：能自动纠正的，不报错
├── assert_url_allowed         ② 硬拦截：内网/元数据地址直接抛，不可重试
└── audit_tool_call (pre_hook) ③ 调用配额：超预算抛 AgentRunException，物理阻断
```

联网工具一律走 `tools/http.py`（统一重试 + 错误分类 + 抖动），**禁止直接 `httpx.get`**。

## 知识层（第 4 篇）

「记忆」（去重）和「RAG」（风格）是同一层的两种形态，对外只暴露 `unified_retriever`（ADR-011）：

```python
from zhixun.knowledge import get_retriever

retriever = get_retriever()

# 1) 查"我该知道什么"
ctx = await retriever.retrieve("本周 AI 开源周报", need_style=True)

# 2) 按角色选披露档位渲染（渐进式披露，ADR-015）
prompt_block = ctx.render(detail_level="full")     # 写手用 full，采集员用 summary

# 3) 过滤重复（两段式：URL 规范化 → 标题语义，ADR-012）
fresh, dropped = await retriever.filter_duplicates(candidates)
```

```bash
uv run zhixun knowledge                 # 管道配置 + 知识层状态
uv run zhixun knowledge --ingest        # 把 data/history/ 入库（切片→Embedding→索引）
uv run zhixun knowledge --search "混合检索怎么实现"
uv run zhixun knowledge --check-dup "Agno 智能体框架" --url https://github.com/agno-agi/agno
```

**零依赖也能跑**：没装 `lancedb` 自动降级为内存向量库；
`EMBEDDING_PROVIDER=hash` 启用确定性 HashEmbedder（无语义能力，仅供离线与去重兜底）。

## 提示词工程（第 2 篇）

提示词一律外置为模板，**不允许内联在 Python 里**（理由见 ADR-006）：

```
src/zhixun/prompts/
├── __init__.py        # front matter 解析 + {{ 变量 }} 注入
├── collector.md       # 采集员（tier: light）
├── analyst.md         # 分析师（tier: primary）
├── writer.md          # 写手（无 output_schema）
└── editor.md          # 编辑（tier: primary）
```

改提示词**不需要动 Python**：编辑 `.md` → `zhixun agents --show-prompt <name>` 确认效果 → 提交。

## 测试

```bash
uv run pytest -m unit          # 单元测试（不调 LLM）
uv run pytest -m integration   # 集成测试（需要数据库）
RUN_E2E=1 uv run pytest -m e2e # 端到端（需要真实 LLM）
```

## 目录职责

| 目录 | 职责 | 详解篇目 |
|------|------|---------|
| `config/` | 全局配置、日志、模型工厂（唯一读环境变量的地方） | 第 1 篇 |
| `prompts/` | 提示词模板与加载器（front matter + 变量注入） | 第 2 篇 |
| `agents/` | 采集员 / 分析师 / 写手 / 编辑 / 平台写手 Team | 第 2、5 篇 |
| `mcp_servers/` | MCP Server（发布/排版/封面），stdio 传输 | 第 6 篇 |
| `skills/` | 沉淀的 Skills（SKILL.md：排版 / 核查 / 封面） | 第 6 篇 |
| `tools/` | 工具系统：`errors.py`（错误分类）`http.py`（重试）`guards.py`（护栏）`github.py` `search.py` `scraper.py` `publisher.py` + `builtin/`（可选依赖降级） | 第 3 篇 |
| `knowledge/` | 知识层：`memory/`（去重、渐进式披露）+ `rag/`（分词/BM25、Embedding、向量库、混合检索）+ `ingest.py` + `unified_retriever` | 第 4 篇 |
| `workflows/` | 周报主流程：`steps/`（六个步骤）+ `weekly_report.py`（Workflow 编排 + HITL） | 第 5 篇 |
| `harness/` | 驾驭层：`context/` `guards/` `entropy/` 三大支柱 | 第 7 篇 |
| `api/` | HTTP 接口（选题 / 草稿 / 流程 / 调度） | 第 5、9 篇 |
| `scheduler/` | APScheduler 定时任务 | 第 5 篇 |
| `db/` | SQLAlchemy 模型、会话、Alembic 迁移 | 第 4 篇 |

## 依赖方向（重要）

```
api / scheduler  →  workflows  →  agents / tools  →  knowledge  →  db / config
                                    ↑                    ↑
                              prompts/（被 agents 依赖）  │
                                    harness（横切，只依赖接口）
```

**禁止反向依赖**。任何"下层 import 上层"的写法都会在 review 中被拦下。



## 能力扩展（第 6 篇）

**MCP** 把发布能力挪到独立进程（主进程碰不到平台 SDK 与凭证）：

```bash
uv pip install -e ".[mcp]"                          # mcp + fastmcp 两个都要
uv run zhixun mcp --list                            # Server 注册表与可用性
uv run zhixun mcp --call render_markdown --arg markdown="# 标题" --arg platform=wechat
```

**Skills** 把"怎么做对"从提示词里搬出来，按角色挂载（延续最小权限思路）：

| Agent | 技能 |
|---|---|
| collector / analyst | （无） |
| writer | `wechat-format` |
| editor | `tech-fact-check` |
| publisher | `cover-design` |

```bash
uv run zhixun skills --list
```

两个实测坑（已写成测试）：**MCP 连接成功要以"发现 N 个工具"为准**
（`connect()` 在 Server 挂掉时不抛异常）；**同步工具里调异步 SDK 要走独立线程**
（`asyncio.run()` 在事件循环里会抛 RuntimeError）。
