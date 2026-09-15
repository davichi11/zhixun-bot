import { http } from '@/services/http'
import type { Candidate, Platform } from '@/types/domain'

/**
 * 选题（采集结果）相关接口。
 *
 * services 层职责：**API 格式 ↔ 领域模型** 的映射。
 * 页面拿到的永远是 Candidate，不是 ProjectOut，接口改字段时只改这里。
 */

interface ProjectDto {
  full_name: string
  url: string
  description: string
  stars: number
  score: number
  reason: string
}

function toCandidate(dto: ProjectDto): Candidate {
  return {
    id: dto.full_name,
    fullName: dto.full_name,
    url: dto.url,
    description: dto.description,
    stars: dto.stars,
    score: dto.score,
    reason: dto.reason,
    selected: true,
  }
}

export async function fetchProjects(): Promise<Candidate[]> {
  const { data } = await http.get<ProjectDto[]>('/projects')
  return data.map(toCandidate)
}

export async function triggerCollect(): Promise<void> {
  await http.post('/projects/collect')
}

/** 平台枚举的远端权威来源（后端为唯一事实来源，前端不写死）。 */
export async function fetchPlatforms(): Promise<Platform[]> {
  return ['wechat', 'zhihu', 'twitter']
}
