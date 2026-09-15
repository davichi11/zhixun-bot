import { http } from '@/services/http'
import type { JobOut } from '@/types/api'
import type { WorkflowRun } from '@/types/domain'

/** 流水线触发、状态查询与调度管理。 */

interface RunDto {
  run_id: string
  status: string
  dry_run: boolean
}

export async function triggerRun(dryRun = true): Promise<RunDto> {
  const { data } = await http.post<RunDto>('/workflow/run', { dry_run: dryRun })
  return data
}

export async function fetchRunStatus(runId: string): Promise<Partial<WorkflowRun>> {
  const { data } = await http.get<Partial<WorkflowRun>>(`/workflow/${runId}`)
  return data
}

export async function fetchJobs(): Promise<JobOut[]> {
  const { data } = await http.get<JobOut[]>('/scheduler/jobs')
  return data
}

export async function toggleJob(jobId: string, enabled: boolean): Promise<void> {
  await http.post(`/scheduler/jobs/${jobId}/toggle`, null, { params: { enabled } })
}
