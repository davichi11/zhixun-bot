import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/**
 * 纯客户端 UI 状态（Zustand）。
 *
 * 判断标准：**这个状态服务端需要知道吗？**
 * - 需要 → 交给 TanStack Query（服务端状态）
 * - 不需要（侧边栏开合、主题）→ 放这里
 */

type Theme = 'light' | 'dark'

interface UiState {
  sidebarCollapsed: boolean
  theme: Theme
  toggleSidebar: () => void
  setTheme: (theme: Theme) => void
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      theme: 'light',
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setTheme: (theme) => set({ theme }),
    }),
    { name: 'zhixun.ui' },
  ),
)
