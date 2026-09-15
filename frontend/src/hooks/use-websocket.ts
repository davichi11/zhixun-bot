import { useEffect, useRef, useState } from 'react'

/**
 * 实时任务进度订阅。
 *
 * 第 1 篇：用轮询实现（简单、够用）；
 * 第 8 篇：换成真 WebSocket，实现步骤级实时进度与 HITL 唤醒推送。
 */

export type WsStatus = 'connecting' | 'open' | 'closed'

export interface ProgressMessage {
  runId: string
  stepIndex: number
  stepName: string
  status: string
}

export function useRunProgress(runId: string | null) {
  const [messages, setMessages] = useState<ProgressMessage[]>([])
  const [status, setStatus] = useState<WsStatus>('closed')
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    if (!runId) return

    setStatus('connecting')

    // TODO(第 8 篇): 替换为 WebSocket / SSE
    const poll = async () => {
      try {
        const { fetchRunStatus } = await import('@/services/workflow')
        const data = await fetchRunStatus(runId)
        setStatus('open')
        setMessages((prev) => [
          ...prev,
          {
            runId,
            stepIndex: -1,
            stepName: 'poll',
            status: String(data.status ?? 'unknown'),
          },
        ])
      } catch {
        setStatus('closed')
      }
    }

    void poll()
    timerRef.current = window.setInterval(poll, 5000)

    return () => {
      if (timerRef.current !== null) window.clearInterval(timerRef.current)
      setStatus('closed')
    }
  }, [runId])

  return { messages, status }
}
