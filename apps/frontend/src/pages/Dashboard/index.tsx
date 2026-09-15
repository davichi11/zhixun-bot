import { PageHeader } from '@/components/layout/PageHeader'
import { WorkflowSteps } from '@/components/workflow'

/**
 * 仪表盘 —— 一眼看清"系统现在怎么样"。
 *
 * 三块信息：
 * 1. 最近一次运行的状态（步骤条）
 * 2. 关键指标（本期候选数 / 待审稿件 / 累计发布）
 * 3. 成本与 Token 消耗（第 8 篇接真实数据）
 */
export default function Dashboard() {
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="仪表盘" description="本周报流水线的整体运行情况" />

      <section className="mb-6 grid grid-cols-3 gap-4">
        {[
          { label: '本期候选项目', value: '—' },
          { label: '待审稿件', value: '—' },
          { label: '累计发布', value: '—' },
        ].map((item) => (
          <div key={item.label} className="rounded-lg border border-slate-200 bg-white p-4">
            <p className="text-xs text-slate-500">{item.label}</p>
            <p className="mt-1 text-2xl font-semibold text-slate-800">{item.value}</p>
          </div>
        ))}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-3 text-sm font-medium text-slate-700">最近一次运行</h2>
        <WorkflowSteps steps={[]} />
      </section>
    </div>
  )
}
