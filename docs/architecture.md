# 架构决策记录（ADR）

本文件记录「智讯助手」的关键架构决策与**当时的理由**。
被否决的方案也会写在这里 —— 因为"为什么不这么做"往往比"怎么做"更有价值。

---

## ADR-001：为什么用 Monorepo 而不是两个仓库

**决策**：前后端放在同一个仓库，`apps/backend` + `apps/frontend`。

**理由**：
- 后端 FastAPI 自动生成 OpenAPI → 用 `openapi-typescript` 转成前端类型，**同仓才能在一处改完**
- 单次 PR 可以完整表达一个功能（接口 + 页面 + 类型）
- 小团队协作成本最低

**代价**：仓库体积会变大。当前后端团队各自超过 5 人时，再拆。

---

## ADR-002：为什么主干用 Workflow 而不是 Team

**决策**：内容生产主流程由 Agno Workflow 编排，**Team 只用在"改写"这一步内部**。

**理由**：
- 内容生产是**确定性流水线**：采集 → 筛选 → 摘要 → 改写 → 审校 → 发布，步骤与依赖关系明确
- 生产环境要求**可审计、可回放、可失败重试** —— 这些是 Workflow 的能力，不是 Team 的
- Team 的自主决策适合探索性任务（"帮我研究一下这个方向"），用在生产流水线会带来不确定性

**Team 的唯一用武之地**：改写步骤里，公众号 / 知乎 / Twitter 三个写手**并行 + 各自人格独立**，
天然适合 Team（coordinate 模式）。

**否决方案**：全部用 Team 的 coordinate 模式串起来。问题是 Leader 的调度不可复现，
同一份输入两次运行结果可能不同，无法做回归测试。

---

## ADR-003：为什么把「记忆」和「RAG」合成一个知识层

**决策**：`knowledge/` 下单设 `memory/` 与 `rag/` 两个子层，对外只暴露 `unified_retriever`。

**理由**：
- 对业务 Agent 来说，两者是同一个问题："我需要知道什么"
- 拆成两个接口会导致：业务层要懂两套 API、上下文拼装逻辑散落各处、Harness 没有统一接入口

**否决方案**：memory 和 rag 作为两个平级顶层模块。
结果是每个 Agent 都要同时注入两个依赖，且第 7 篇的动态上下文工程无处安放。

---

## ADR-004：为什么 Harness 是横切层而不是一个模块

**决策**：`harness/` 独立在顶层，包含 `context/` `guards/` `entropy/` 三个子包；
**业务模块依赖它的接口，不依赖它的实现**。

**理由**：
- Harness 的职责是"约束与治理"，它天然要知道所有模块在做什么
- 但如果业务代码直接 `import harness.guards`，将来整套替换（LangSmith / OpenTelemetry）就要改业务代码
- 通过 `harness/middlewares.py` 中的协议解耦后，替换 Herness 实现只需改一个目录

**验证方式**：CI 里加一条规则 —— 除 `api/` 与 `scheduler/` 外，任何模块不得 import `zhixun.harness.*` 的具体实现。

---

## ADR-005：为什么开发态用 SQLite + LanceDB

**决策**：开发态 SQLite + 嵌入式 LanceDB；生产态 Postgres + LanceDB（或 PgVector）。

**理由**：
- **零运维**：clone 下来就能跑，不需要先起 Docker
- **接口一致**：`knowledge/` 层的接口不变，切换只改配置
- LanceDB 的嵌入式特性和 SQLite 组合，让"单机个人部署"成为可能（这也是目标用户之一）

**代价**：SQLite 的并发写能力弱。当并发采集任务变多时（第 5 篇的并行步骤），需要切 Postgres。
