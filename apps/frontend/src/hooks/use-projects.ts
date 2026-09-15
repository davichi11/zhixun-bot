import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { fetchProjects, triggerCollect } from '@/services/projects'

/** 选题面板数据。 */

export const projectsQueryKey = ['projects'] as const

export function useProjects() {
  return useQuery({
    queryKey: projectsQueryKey,
    queryFn: fetchProjects,
  })
}

export function useTriggerCollect() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: triggerCollect,
    onSuccess: () => {
      // 采集是异步的，先失效再让页面轮询（第 3 篇会改成 WebSocket 推送）
      void queryClient.invalidateQueries({ queryKey: projectsQueryKey })
    },
  })
}
