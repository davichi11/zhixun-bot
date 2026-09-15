# 智讯助手 · 后端（zhixun-backend）

Agno 业务核心：Agent 定义、工具系统、知识层、流水线、Harness 驾驭层、HTTP API 与调度器。

## 快速开始

```bash
# 1. 安装依赖（推荐 uv）
uv sync --extra dev

# 2. 配置环境变量
cp ../../.env.example ../../.env    # 填好 OPENAI_API_KEY 或 DEEPSEEK_API_KEY

# 3. 跑一次干运行（不发布）
uv run zhixun run --dry-run

# 4. 启动 API
uv run zhixun serve --reload
#   文档：http://127.0.0.1:8000/docs
```

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
| `agents/` | 采集员 / 分析师 / 写手 / 编辑 / 平台写手 Team | 第 2、5 篇 |
| `tools/` | GitHub、搜索、抓取、发布等工具 | 第 3 篇 |
| `knowledge/` | 知识层：`memory/`（去重、压缩）+ `rag/`（向量检索）+ `unified_retriever` | 第 4 篇 |
| `workflows/` | 周报主流程与六个步骤节点 | 第 5 篇 |
| `harness/` | 驾驭层：`context/` `guards/` `entropy/` 三大支柱 | 第 7 篇 |
| `api/` | HTTP 接口（选题 / 草稿 / 流程 / 调度） | 第 5、9 篇 |
| `scheduler/` | APScheduler 定时任务 | 第 5 篇 |
| `db/` | SQLAlchemy 模型、会话、Alembic 迁移 | 第 4 篇 |

## 依赖方向（重要）

```
api / scheduler  →  workflows  →  agents / tools  →  knowledge  →  db / config
                                    ↑
                            harness（横切，只依赖接口）
```

**禁止反向依赖**。任何"下层 import 上层"的写法都会在 review 中被拦下。
