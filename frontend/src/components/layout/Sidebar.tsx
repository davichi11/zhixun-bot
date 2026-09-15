import {
  CalendarClock,
  FileText,
  LayoutDashboard,
  Radar,
  Settings,
  ShieldCheck,
} from 'lucide-react'
import { NavLink } from 'react-router-dom'

import { cn } from '@/lib/format'

/** 侧边导航 —— 与第一篇 4.3 节的六个页面一一对应。 */

const NAV_ITEMS = [
  { to: '/dashboard', label: '仪表盘', icon: LayoutDashboard },
  { to: '/projects', label: '选题', icon: Radar },
  { to: '/drafts', label: '草稿', icon: FileText },
  { to: '/review', label: '审校', icon: ShieldCheck },
  { to: '/schedule', label: '调度', icon: CalendarClock },
  { to: '/settings', label: '配置', icon: Settings },
] as const

export function Sidebar({ collapsed }: { collapsed: boolean }) {
  return (
    <aside
      className={cn(
        'flex flex-col border-r border-slate-200 bg-white transition-[width] duration-200',
        collapsed ? 'w-16' : 'w-56',
      )}
    >
      <div className="flex h-14 items-center gap-2 border-b border-slate-100 px-4">
        <span className="grid size-7 place-items-center rounded-md bg-brand-600 text-sm font-bold text-white">
          智
        </span>
        {!collapsed && <span className="text-sm font-semibold text-slate-800">智讯助手</span>}
      </div>

      <nav className="flex-1 space-y-1 p-2">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                isActive
                  ? 'bg-brand-50 font-medium text-brand-700'
                  : 'text-slate-600 hover:bg-slate-50',
              )
            }
          >
            <Icon className="size-4 shrink-0" />
            {!collapsed && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>

      {!collapsed && (
        <div className="border-t border-slate-100 p-3 text-xs text-slate-400">
          v0.1.0 · M0 骨架
        </div>
      )}
    </aside>
  )
}
