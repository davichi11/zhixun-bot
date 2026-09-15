import { Check, X } from 'lucide-react'
import { useState } from 'react'

import { EmptyState, PageHeader } from '@/components/layout/PageHeader'
import { useDrafts, useSubmitReview } from '@/hooks/use-drafts'
import { countWords } from '@/lib/format'
import { PLATFORM_LABEL, type Platform } from '@/types/domain'

/**
 * 审校面板 —— 全项目唯一的 Human-in-the-Loop 节点。
 *
 * 为什么必须有这一页？
 * Agent 再强也不该直接面对公众发布。人工在这里做三件事：
 * 1. 事实与合规的最终把关（AI 的审校只是第一道）
 * 2. 决定"这期到底发不发"
 * 3. 把修改意见沉淀回去（第 7 篇会把它转成护栏规则）
 */
export default function Review() {
  const { data: drafts, isLoading } = useDrafts()
  const submit = useSubmitReview()
  const [comment, setComment] = useState('')

  const pending = (drafts ?? []).filter((d) => !d.approved)

  const decide = (approve: boolean) => {
    if (pending.length === 0) return
    submit.mutate({ draftIds: pending.map((d) => d.id), approve, comment })
  }

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="审校"
        description="人工终审 —— 通过后才会进入发布队列"
        actions={
          <>
            <button
              type="button"
              onClick={() => decide(false)}
              className="flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
            >
              <X className="size-3.5" />
              打回
            </button>
            <button
              type="button"
              onClick={() => decide(true)}
              className="flex items-center gap-1.5 rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700"
            >
              <Check className="size-3.5" />
              通过并提交
            </button>
          </>
        }
      />

      {isLoading ? (
        <EmptyState title="加载中…" />
      ) : pending.length === 0 ? (
        <EmptyState title="没有待审稿件" hint="流水线的审校步骤会在这里挂起等待你" />
      ) : (
        <div className="space-y-4">
          {pending.map((d) => (
            <article key={d.id} className="rounded-lg border border-slate-200 bg-white p-5">
              <header className="mb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                    {PLATFORM_LABEL[d.platform as Platform] ?? d.platform}
                  </span>
                  <h3 className="text-sm font-medium text-slate-800">{d.title}</h3>
                </div>
                <span className="text-xs text-slate-400">{countWords(d.content)} 字</span>
              </header>
              <div className="prose-zh whitespace-pre-wrap">{d.content}</div>
            </article>
          ))}

          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="审校意见（会作为修改反馈回传给 Agent）"
            className="h-24 w-full resize-none rounded-lg border border-slate-300 p-3 text-sm outline-none focus:border-brand-500"
          />
        </div>
      )}
    </div>
  )
}
