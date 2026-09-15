import { createBrowserRouter, Navigate } from 'react-router-dom'

import App from '@/App'
import Dashboard from '@/pages/Dashboard'
import Drafts from '@/pages/Drafts'
import Projects from '@/pages/Projects'
import Review from '@/pages/Review'
import Schedule from '@/pages/Schedule'
import Settings from '@/pages/Settings'

/**
 * 路由表。
 * 六个页面一一对应第一篇 4.3 节定义的四个核心面板 + 仪表盘 + 配置。
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: 'dashboard', element: <Dashboard /> },
      { path: 'projects', element: <Projects /> },
      { path: 'drafts', element: <Drafts /> },
      { path: 'review', element: <Review /> },
      { path: 'schedule', element: <Schedule /> },
      { path: 'settings', element: <Settings /> },
    ],
  },
])
