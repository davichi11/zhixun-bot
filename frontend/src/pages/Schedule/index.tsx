import { EmptyState, PageHeader } from '@/components/layout/PageHeader'
import { fetchJobs } from '@/services/workflow'
import { useQuery } from '@tanstack/react-query'

/**
 * 调度面板 —— 管理定时任务。
 *
 * 这里是"让流水线自己跑"的开关：
 * 打开「每周周报」后，即使不开电脑，服务器也会按时产出。
 */
export default function Schedule() {
  const { data: jobs, isLoading } = useQuery({ queryKey: ['jobs'], queryFn: fetchJobs })

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="调度" description="定时自动生成，让流水线自己跑起来" />

      {isLoading ? (
        <EmptyState title="加载中…" />
      ) : (
        <ul className="space-y-2">
          {(jobs ?? []).map((job) => (
            <li
              key={job.id}
              className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-4 py-3"
            >
              <div>
                <p className="text-sm font-medium text-slate-800">{job.name}</p>
                <p className="mt-0.5 font-mono text-xs text-slate-400">{job.cron}</p>
              </div>
              <span
                className={
                  job.enabled
                    ? 'rounded bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700'
                    : 'rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500'
                }
              >
                {job.enabled ? '已启用' : '已停用'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
