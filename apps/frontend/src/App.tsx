import { Outlet } from 'react-router-dom'

import { AppLayout } from '@/components/layout/AppLayout'

/**
 * 应用根组件。
 * 只负责"壳"：侧边栏 + 顶栏 + 内容区（Outlet）。
 * 具体的页面逻辑都在 pages/ 下，保持根组件足够薄。
 */
export default function App() {
  return (
    <AppLayout>
      <Outlet />
    </AppLayout>
  )
}
