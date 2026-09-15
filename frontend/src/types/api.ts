/**
 * 后端 API 类型。
 *
 * ⚠️ 这个文件最终应由 `pnpm gen:api` 从后端 OpenAPI 自动生成：
 *     openapi-typescript http://127.0.0.1:8000/openapi.json -o src/types/api.ts
 *
 * 第 1 篇先手写一份与后端 `api/schemas` 一致的版本，
 * 保证前端能独立开发；第 9 篇接入 CI 自动生成，彻底消灭类型漂移。
 */

export interface HealthResponse {
  status: string
  app: string
  env: string
  version: string
  harness_enabled: boolean
}

export interface RunRequest {
  dry_run: boolean
  issue_no?: number | null
}

export interface RunResponse {
  run_id: string
  status: string
  dry_run: boolean
}

export interface ProjectOut {
  full_name: string
  url: string
  description: string
  stars: number
  score: number
  reason: string
}

export interface DraftOut {
  id: number
  run_id: string
  platform: string
  title: string
  approved: boolean
  created_at: string
}

export interface ReviewRequest {
  draft_ids: number[]
  approve: boolean
  comment: string
}

export interface JobOut {
  id: string
  name: string
  cron: string
  enabled: boolean
  next_run?: string | null
  meta: Record<string, unknown>
}

/** 统一错误体（对应后端 5.4 节错误处理规范）。 */
export interface ApiErrorBody {
  error: {
    code: string
    message: string
  }
}
