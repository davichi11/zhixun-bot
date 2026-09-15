# 智讯助手（zhixun-bot） 

> AI 资讯聚合与内容创作智能体 —— 自动采集 AI 领域开源项目，智能筛选去重，仿照你的写作风格生成多平台内容，定时发布。
>
> 本仓库是《**Agno 实战系列：从零开发一个完整的生产级智能体**》的配套工程，当前进度：**第一篇（项目骨架 + 完整目录树）**。

---

## 这是什么

不是 "AI 写作 Demo"，而是一个完整产品：

| 层 | 组成 |
|----|------|
| 调度层 | APScheduler 定时触发，让流水线自己跑 |
| 智能体层 | Workflow 主导 + Team 局部嵌套（三平台并行改写） |
| 工具与知识层 | GitHub / 搜索 / 抓取 工具 + 记忆与 RAG 知识层 |
| 存储层 | Postgres（业务）+ LanceDB（向量） |
| 控制台层 | React + TS 四面板（选题 / 草稿 / 审校 / 调度） |

🛡️ 全栈贯穿 **Harness Engineering**（动态上下文工程 / 机械强制 / 熵管理）—— 给 3μs 启动的极速 Agent 套上缰绳。

---

## 目录结构

```
zhixun-bot/
├── apps/
│   ├── backend/          # Agno 后端服务（Python / FastAPI）
│   └── frontend/         # React 控制台（TypeScript / Vite）
├── packages/
│   └── shared-types/     # 前后端共享的 API 类型（从 OpenAPI 生成）
├── infra/
│   ├── docker/           # 镜像与编排
│   ├── nginx/            # 反向代理
│   └── scripts/          # 开发与部署脚本
├── docs/
│   ├── architecture.md   # 架构决策记录（ADR）
│   └── api.md            # API 说明
├── .github/workflows/    # CI
├── .env.example
├── pyproject.toml        # uv workspace 根
├── pnpm-workspace.yaml   # Node workspace 根
└── README.md
```

后端与前端各自的目录职责见：
- [`apps/backend/README.md`](apps/backend/README.md)
- [`apps/frontend/README.md`](apps/frontend/README.md)

---

## 快速开始

### 0. 前置要求

- Python ≥ 3.11、[uv](https://docs.astral.sh/uv/)
- Node ≥ 20、[pnpm](https://pnpm.io/)
- 一个 LLM API Key（OpenAI / DeepSeek / Anthropic 任一）

### 1. 配置

```bash
cp .env.example .env
# 编辑 .env，至少填好 OPENAI_API_KEY（或 DEEPSEEK_API_KEY）
```

### 2. 起后端

```bash
uv sync --all-extras
uv run zhixun run --dry-run      # 干跑一次流水线
uv run zhixun serve --reload     # 启动 API，文档见 /docs
```

### 3. 起前端

```bash
pnpm install
pnpm --filter @zhixun/frontend dev    # http://localhost:5173
```

前端开发服务器已把 `/api` 代理到 `127.0.0.1:8000`，无需额外配置跨域。

### 4. 一键起全套（可选）

```bash
bash infra/scripts/dev.sh
```

---

## 依赖方向（**改代码前必读**）

```
api / scheduler  →  workflows  →  agents / tools  →  knowledge  →  db / config
                                     ↑
                             harness（横切，只依赖接口）
```

四条铁律：

1. **`config` 是叶子**：被所有模块依赖，自己不依赖任何业务模块
2. **`db` 只被 `knowledge` 和 `api` 依赖**：业务模块不直接碰数据库
3. **`harness` 是横切层**：它依赖业务的**接口**，但业务代码**不得 import 它的实现**
4. **`api` 是最外层**：能看见所有内部模块，但内部模块之间不得互相耦合

违反这四条会在 CI 的 import-linter 检查里失败（第 9 篇接入）。

---

## 当前进度

| 里程碑 | 内容 | 状态 |
|--------|------|------|
| M0 | 项目骨架 + 完整目录树 | ✅ 当前 |
| M1 | 核心 Agent 与提示词工程 | ⏳ 第 2 篇 |
| M2 | 工具系统（GitHub 采集） | ⏳ 第 3 篇 |
| M3 | 知识层（去重 + RAG 风格化） | ⏳ 第 4 篇 |
| M4 | 流水线编排（Workflow + 内嵌 Team） | ⏳ 第 5 篇 |
| M5 | MCP + Skills 生态 | ⏳ 第 6 篇 |
| M6 | Harness Engineering 护栏就位 | ⏳ 第 7 篇 |
| M7 | 评估 / 测试 / 可观测性 | ⏳ 第 8 篇 |
| M8 | 部署上线与开源 | ⏳ 第 9 篇 |

---

## 许可

MIT
