import { RefreshCw } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/layout/PageHeader'
import { useProjects, useTriggerCollect } from '@/hooks/use-projects'
import { formatNumber } from '@/lib/format'

/**
 * 选题面板 —— 展示采集 + 筛选后的候选项目。
 *
 * 交互：可以看到每个项目的评分与理由（分析师的可解释输出），
 * 并手动勾选/剔除，让"人"对 AI 的判断有最终否决权。
 */
export default function Projects() {
  const { data: projects, isLoading } = useProjects()
  const collect = useTriggerCollect()

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="选题"
        description="本期采集到的候选项目，按综合评分排序"
        actions={
          <button
            type="button"
            onClick={() => collect.mutate()}
            disabled={collect.isPending}
            className="flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
          >
            <RefreshCw className={collect.isPending ? 'size-3.5 animate-spin' : 'size-3.5'} />
            重新采集
          </button>
        }
      />

      {isLoading ? (
        <EmptyState title="加载中…" />
      ) : !projects || projects.length === 0 ? (
        <EmptyState
          title="还没有候选项目"
          hint="第 3 篇接入 GitHub 采集工具后，这里会出现项目列表"
        />
      ) : (
        <ul className="space-y-2">
          {projects.map((p) => (
            <li key={p.id} className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <a
                    href={p.url}
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium text-brand-700 hover:underline"
                  >
                    {p.fullName}
                  </a>
                  <p className="mt-1 line-clamp-2 text-sm text-slate-600">{p.description}</p>
                  <p className="mt-1 text-xs text-slate-400">{p.reason}</p>
                </div>
                <div className="shrink-0 text-right">
                  <p className="text-lg font-semibold text-slate-800">{p.score.toFixed(1)}</p>
                  <p className="text-xs text-slate-400">⭐ {formatNumber(p.stars)}</p>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
