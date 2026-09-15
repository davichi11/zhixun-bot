import type { ReactNode } from 'react'

import { Sidebar } from '@/components/layout/Sidebar'
import { Topbar } from '@/components/layout/Topbar'
import { cn } from '@/lib/format'
import { useUiStore } from '@/stores/ui.store'

/**
 * 应用外壳：左侧导航 + 顶部栏 + 内容区。
 *
 * 布局保持"薄"：所有页面共用的只有导航与顶栏，
 * 页面自己的工具条放在各自 page 内部。
 */
export function AppLayout({ children }: { children: ReactNode }) {
  const collapsed = useUiStore((s) => s.sidebarCollapsed)

  return (
    <div className="flex h-full bg-slate-50">
      <Sidebar collapsed={collapsed} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <main className={cn('flex-1 overflow-y-auto p-6')}>{children}</main>
      </div>
    </div>
  )
}
