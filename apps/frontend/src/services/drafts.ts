import { http } from '@/services/http'
import type { Draft, Platform } from '@/types/domain'

/** 稿件与审校相关接口。 */

interface DraftDto {
  id: number
  run_id: string
  platform: string
  title: string
  approved: boolean
  created_at: string
}

function toDraft(dto: DraftDto): Draft {
  return {
    id: dto.id,
    runId: dto.run_id,
    platform: dto.platform as Platform,
    title: dto.title,
    content: '', // 列表接口不返回正文，详情接口再补
    approved: dto.approved,
    createdAt: dto.created_at,
  }
}

export async function fetchDrafts(runId?: string): Promise<Draft[]> {
  const { data } = await http.get<DraftDto[]>('/drafts', { params: { run_id: runId } })
  return data.map(toDraft)
}

export async function submitReview(
  draftIds: number[],
  approve: boolean,
  comment = '',
): Promise<void> {
  await http.post('/drafts/review', { draft_ids: draftIds, approve, comment })
}
