import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/**
 * 认证状态。
 *
 * 第 1 篇：单用户本地部署，只保留一个极简的 token 位（方便将来加登录）；
 * 第 9 篇：如需多用户，换成后端签发的 JWT + 刷新逻辑。
 */

interface AuthState {
  token: string | null
  operator: string
  login: (token: string, operator: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      operator: '本机用户',
      login: (token, operator) => set({ token, operator }),
      logout: () => set({ token: null }),
    }),
    { name: 'zhixun.auth' },
  ),
)
