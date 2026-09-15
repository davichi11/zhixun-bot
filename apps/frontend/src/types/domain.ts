/**
 * 业务领域类型 —— 前端内部使用的模型（与后端 API 类型解耦）。
 *
 * 为什么要分开？
 * API 类型是"传输格式"，会随接口演进；
 * 领域类型是"页面语义"，更稳定。两者之间由 services/ 做一层映射。
 */

export type Platform = 'wechat' | 'zhihu' | 'twitter'

export const PLATFORM_LABEL: Record<Platform, string> = {
  wechat: '公众号',
  zhihu: '知乎',
  twitter: 'Twitter',
}

export interface Candidate {
  id: string
  fullName: string
  url: string
  description: string
  stars: number
  score: number
  reason: string
  selected: boolean
}

export interface Draft {
  id: number
  runId: string
  platform: Platform
  title: string
  content: string
  approved: boolean
  createdAt: string
}

export interface WorkflowRun {
  runId: string
  status: 'running' | 'waiting_human' | 'succeeded' | 'failed'
  dryRun: boolean
  currentStep: number
  steps: WorkflowStep[]
  startedAt: string
}

export interface WorkflowStep {
  index: number
  name: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'waiting_human'
  durationMs?: number
}

export interface ReviewIssue {
  level: 'blocker' | 'major' | 'minor'
  category: 'fact' | 'compliance' | 'format' | 'tone'
  detail: string
  suggestion: string
}
