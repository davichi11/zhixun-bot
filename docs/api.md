# API 说明

Base URL：`http://127.0.0.1:8000/api/v1`
交互式文档：`/docs`（Swagger UI） / `/redoc`

---

## 约定

**错误体**（业务错误统一 200 + 业务码，见后端 5.4 节规范）：

```json
{
  "error": {
    "code": "DEDUP_HIT",
    "message": "该项目已在第 12 期发布过"
  }
}
```

**统一原则**：出参永远是 `api/schemas` 里定义的 Schema，不直接返回 ORM 模型。

---

## 端点一览（第 1 篇已可实现的部分）

| 方法 | 路径 | 说明 | 实现篇目 |
|------|------|------|---------|
| GET | `/health` | 健康检查（无版本前缀） | ✅ 第 1 篇 |
| GET | `/api/v1/projects` | 候选项目列表 | 第 4 篇补数据 |
| POST | `/api/v1/projects/collect` | 手动触发采集 | 第 3 篇 |
| GET | `/api/v1/drafts` | 稿件列表（可按 run_id 过滤） | 第 5 篇补数据 |
| POST | `/api/v1/drafts/review` | 提交人工审校（HITL 放行） | 第 5 篇 |
| POST | `/api/v1/workflow/run` | 触发一次流水线 | ✅ 第 1 篇 |
| GET | `/api/v1/workflow/{run_id}` | 查询运行状态 | 第 5 篇补数据 |
| GET | `/api/v1/scheduler/jobs` | 定时任务列表 | ✅ 第 1 篇 |
| POST | `/api/v1/scheduler/jobs/{id}/toggle` | 启用/停用任务 | 第 5 篇 |

---

## 示例

### 触发一次干跑

```bash
curl -X POST http://127.0.0.1:8000/api/v1/workflow/run \
  -H 'Content-Type: application/json' \
  -d '{"dry_run": true}'
```

```json
{ "run_id": "3f1a...", "status": "accepted", "dry_run": true }
```

### 轮询状态

```bash
curl http://127.0.0.1:8000/api/v1/workflow/3f1a...
```

---

## 类型同步

前端类型由本 OpenAPI 自动生成，**不要手写**（第 1 篇临时手写了一份 `src/types/api.ts` 以保证前端能独立开发）：

```bash
cd apps/frontend && pnpm gen:api
```

第 9 篇会把这条命令接进 CI，一旦后端 Schema 变更而前端未同步，构建直接失败。
