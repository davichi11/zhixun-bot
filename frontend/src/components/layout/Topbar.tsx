import { PanelLeftClose, PanelLeftOpen, Play } from 'lucide-react'

import { useAuthStore } from '@/stores/auth.store'
import { useUiStore } from '@/stores/ui.store'

/** 顶部栏：折叠侧边栏 + 触发流水线 + 当前操作人。 */
export function Topbar() {
  const { collapsed, toggleSidebar } = useUiStore()
  const operator = useAuthStore((s) => s.operator)

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4">
      <button
        type="button"
        onClick={toggleSidebar}
        className="rounded-md p-2 text-slate-500 hover:bg-slate-100"
        aria-label="折叠侧边栏"
      >
        {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
      </button>

      <div className="flex items-center gap-3">
        <button
          type="button"
          className="flex items-center gap-1.5 rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700"
          // TODO(第 5 篇): 打开"新建一期"抽屉，选择 dry-run 与信源
        >
          <Play className="size-3.5" />
          生成一期
        </button>
        <span className="text-sm text-slate-500">{operator}</span>
      </div>
    </header>
  )
}
