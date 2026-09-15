import { Workflow } from 'lucide-react'

import { cn } from '@/lib/format'
import type { WorkflowStep } from '@/types/domain'

/**
 * 流水线可视化（DAG / 步骤条）。
 *
 * 让"黑盒 Agent"变得可见：每一步的状态、耗时、卡在哪一步一目了然。
 * 这也是 Harness 可观测性的前端入口（第 4、7 篇会不断强化）。
 */

const STATUS_STYLE: Record<WorkflowStep['status'], string> = {
  pending: 'bg-slate-100 text-slate-500',
  running: 'bg-brand-100 text-brand-700',
  done: 'bg-emerald-100 text-emerald-700',
  failed: 'bg-red-100 text-red-700',
  waiting_human: 'bg-amber-100 text-amber-700',
}

const STATUS_LABEL: Record<WorkflowStep['status'], string> = {
  pending: '待执行',
  running: '进行中',
  done: '已完成',
  failed: '失败',
  waiting_human: '等待人工',
}

export function WorkflowSteps({ steps }: { steps: WorkflowStep[] }) {
  if (steps.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 bg-white text-slate-400">
        <Workflow className="size-6" />
        <p className="text-sm">还没有运行记录</p>
      </div>
    )
  }

  return (
    <ol className="space-y-2">
      {steps.map((step) => (
        <li
          key={step.index}
          className="flex items-center justify-between rounded-md border border-slate-200 bg-white px-3 py-2"
        >
          <div className="flex items-center gap-2">
            <span className="grid size-5 place-items-center rounded-full bg-slate-100 text-xs text-slate-500">
              {step.index + 1}
            </span>
            <span className="text-sm text-slate-700">{step.name}</span>
          </div>
          <span className={cn('rounded px-2 py-0.5 text-xs', STATUS_STYLE[step.status])}>
            {STATUS_LABEL[step.status]}
          </span>
        </li>
      ))}
    </ol>
  )
}
