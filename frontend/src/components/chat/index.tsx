import { MessageSquare } from 'lucide-react'

/**
 * 与 Agent 交互的对话面板（占位）。
 *
 * 用途：当 Agent 需要人补充信息时（例如审校追问、选题讨论），
 * 通过这个面板与它对话，而不是去翻日志。
 *
 * TODO(第 5 篇): 接入 Agno AgentOS 的会话接口，支持流式输出与工具调用可视化。
 */
export function ChatPanel() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 bg-white text-slate-400">
      <MessageSquare className="size-6" />
      <p className="text-sm">Agent 对话面板（第 5 篇实现）</p>
    </div>
  )
}
