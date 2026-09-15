# 智讯助手 · 前端控制台（zhixun-frontend）

React 18 + TypeScript + Vite 的操作台：选题、草稿、审校、调度四个核心面板。

## 快速开始

```bash
pnpm install
pnpm dev          # http://localhost:5173 （/api 自动代理到后端 8000）
```

其它命令：

```bash
pnpm build        # 产物到 dist/
pnpm typecheck    # 类型检查
pnpm lint
pnpm gen:api      # 从后端 OpenAPI 生成 src/types/api.ts（第 9 篇接入 CI）
```

## 目录职责

| 目录 | 职责 | 详解篇目 |
|------|------|---------|
| `pages/` | 六个页面（Dashboard / Projects / Drafts / Review / Schedule / Settings） | 第 5 篇 |
| `components/layout/` | 外壳：侧边栏、顶栏、页头 | 第 1 篇 |
| `components/ui/` | shadcn/ui 基础组件（按需 `shadcn add`） | 第 5 篇 |
| `components/workflow/` | 流水线步骤可视化 | 第 5 篇 |
| `components/chat/` | 与 Agent 的对话面板 | 第 5 篇 |
| `services/` | API 客户端 + **API 格式 ↔ 领域模型**映射 | 第 1 篇 |
| `stores/` | 纯客户端状态（Zustand）：UI、认证、编辑器 | 第 1 篇 |
| `hooks/` | TanStack Query 封装 + 实时进度订阅 | 第 5、8 篇 |
| `types/` | `api.ts`（自动生成）+ `domain.ts`（业务模型） | 第 1 篇 |
| `lib/` | 纯工具函数（格式化、Markdown 处理） | 第 1 篇 |

## 状态管理原则（重要）

| 状态类型 | 放哪 | 例子 |
|---------|------|------|
| 服务端状态 | TanStack Query | 项目列表、稿件列表、任务状态 |
| 客户端状态 | Zustand | 侧边栏开合、主题、正在编辑的正文 |
| 局部状态 | `useState` | 表单输入、弹窗开关 |

判断标准：**服务端需要知道吗？** 需要 → Query；不需要 → Zustand。

## 分层约定

```
pages/  →  hooks/  →  services/  →  后端 API
   ↓                      ↓
components/            types/domain.ts
   ↓
stores/（仅纯客户端状态）
```

`pages/` **不直接调 axios**，一律通过 `hooks/`；`hooks/` 只调 `services/`；
`services/` 负责 DTO ↔ 领域模型转换。这样接口改字段时，改动被限制在 `services/` 一层。
