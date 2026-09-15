import { create } from 'zustand'

import type { Platform } from '@/types/domain'

/**
 * 草稿编辑器的本地状态。
 *
 * 为什么不用 TanStack Query？
 * 用户正在输入的正文是"未提交的本地状态"，
 * 只有点"保存"或"提交审校"时才写回服务端。
 */

interface DraftEditorState {
  activeDraftId: number | null
  activePlatform: Platform | null
  content: string
  dirty: boolean
  setActive: (id: number, platform: Platform, content: string) => void
  updateContent: (content: string) => void
  reset: () => void
}

export const useDraftEditorStore = create<DraftEditorState>((set) => ({
  activeDraftId: null,
  activePlatform: null,
  content: '',
  dirty: false,

  setActive: (id, platform, content) =>
    set({ activeDraftId: id, activePlatform: platform, content, dirty: false }),

  updateContent: (content) => set({ content, dirty: true }),

  reset: () => set({ activeDraftId: null, activePlatform: null, content: '', dirty: false }),
}))
