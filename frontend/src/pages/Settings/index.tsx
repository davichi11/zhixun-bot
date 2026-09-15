import { PageHeader } from '@/components/layout/PageHeader'

/**
 * 配置页 —— 暴露那些"改了要重启"的关键参数。
 *
 * 这里刻意只读展示：真正的配置源仍是后端 `.env`，
 * 前端不提供在线改 Key 的能力（安全考虑）。
 * 第 9 篇会改成"后端下发只读配置 + 少量可热更新开关"。
 */
export default function Settings() {
  const items = [
    { label: 'LLM 供应商', value: 'openai（在 .env 中配置）' },
    { label: '去重相似度阈值', value: '0.85' },
    { label: 'RAG 召回条数', value: '5' },
    { label: 'Harness 护栏', value: '开启' },
    { label: '上下文卸载阈值', value: '85%' },
  ]

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="配置" description="当前生效的关键参数（只读，改动请编辑后端 .env）" />

      <dl className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
        {items.map((item) => (
          <div key={item.label} className="flex items-center justify-between px-4 py-3">
            <dt className="text-sm text-slate-600">{item.label}</dt>
            <dd className="text-sm text-slate-800">{item.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
