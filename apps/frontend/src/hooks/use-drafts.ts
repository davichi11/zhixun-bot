import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { fetchDrafts, submitReview } from '@/services/drafts'

/** 草稿与审校数据。 */

export const draftsQueryKey = (runId?: string) => ['drafts', runId ?? 'latest'] as const

export function useDrafts(runId?: string) {
  return useQuery({
    queryKey: draftsQueryKey(runId),
    queryFn: () => fetchDrafts(runId),
  })
}

export function useSubmitReview(runId?: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      draftIds,
      approve,
      comment,
    }: {
      draftIds: number[]
      approve: boolean
      comment?: string
    }) => submitReview(draftIds, approve, comment),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: draftsQueryKey(runId) })
    },
  })
}
