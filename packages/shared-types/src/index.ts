/**
 * 前后端共享类型。
 *
 * 定位：**跨应用复用的纯类型与常量**，不含任何运行时代码之外的逻辑。
 * 例如将来 SDK / CLI / 浏览器插件也要用平台枚举，就放这里。
 *
 * ⚠️ 与 `apps/frontend/src/types/api.ts` 的区别：
 * - `types/api.ts` 是**从后端 OpenAPI 自动生成的**（单向前端消费）
 * - 本包是**手写的、跨应用共享的稳定契约**（多方复用）
 *
 * 第 1 篇只放平台枚举；第 6 篇接入 MCP 后会加入 MCP 工具描述类型。
 */

/** 发布平台。 */
export type Platform = 'wechat' | 'zhihu' | 'twitter'

export const PLATFORMS: readonly Platform[] = ['wechat', 'zhihu', 'twitter'] as const

export const PLATFORM_LABEL: Record<Platform, string> = {
  wechat: '公众号',
  zhihu: '知乎',
  twitter: 'Twitter',
}

/** 流水线步骤（与后端 workflows/steps 保持一致）。 */
export type StepKey =
  | 'collect'
  | 'filter'
  | 'summarize'
  | 'rewrite'
  | 'review'
  | 'publish'

export const STEP_LABEL: Record<StepKey, string> = {
  collect: '采集',
  filter: '筛选',
  summarize: '摘要',
  rewrite: '改写',
  review: '审校',
  publish: '发布',
}
