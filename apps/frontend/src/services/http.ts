import axios, { AxiosError } from 'axios'

import type { ApiErrorBody } from '@/types/api'

/**
 * 全局 HTTP 客户端。
 *
 * 约定：
 * - baseURL 走 `/api/v1`（开发态由 Vite 代理到后端，避免跨域）
 * - 统一把后端的 `{ error: { code, message } }` 转成可读的 Error.message
 * - 业务代码里**不要**再写 try/catch 判断 res.code，交给 TanStack Query 的 onError
 */
export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api/v1',
  timeout: 60_000, // Agent 流水线调用较慢，超时给宽一些
  headers: { 'Content-Type': 'application/json' },
})

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorBody>) => {
    const body = error.response?.data
    const message = body?.error?.message ?? error.message ?? '请求失败'
    const code = body?.error?.code ?? String(error.response?.status ?? 'NETWORK_ERROR')
    return Promise.reject(new ApiError(message, code))
  },
)

/** 带业务码的错误类型。 */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly code: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}
