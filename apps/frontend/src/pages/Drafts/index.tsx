import { EmptyState, PageHeader } from '@/components/layout/PageHeader'
import { useDrafts } from '@/hooks/use-drafts'
import { formatRelativeTime } from '@/lib/format'
import { PLATFORM_LABEL, type Platform } from '@/types/domain'

/**
 * 草稿面板 —— 一稿多版（公众号 / 知乎 / Twitter）。
 *
 * 同一个 run 下的三个平台版本并排展示，
 * 方便对比"同一份素材在不同平台该怎么长"。
 */
export default function Drafts() {
  const { data: drafts, isLoading } = useDrafts()

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="草稿" description="同一份素材的多平台版本" />

      {isLoading ? (
        <EmptyState title="加载中…" />
      ) : !drafts || drafts.length === 0 ? (
        <EmptyState title="还没有草稿" hint="流水线跑到「改写」步骤后，这里会出现多平台版本" />
      ) : (
        <div className="grid grid-cols-3 gap-4">
          {drafts.map((d) => (
            <article key={d.id} className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                  {PLATFORM_LABEL[d.platform as Platform] ?? d.platform}
                </span>
                <span className="text-xs text-slate-400">
                  {formatRelativeTime(d.createdAt)}
                </span>
              </div>
              <h3 className="text-sm font-medium text-slate-800">{d.title}</h3>
              <p className="mt-2 line-clamp-6 text-xs text-slate-500">{d.content}</p>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
