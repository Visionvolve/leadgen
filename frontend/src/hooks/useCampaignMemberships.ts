import { useMemo } from 'react'
import { useQueries, useQueryClient, useMutation } from '@tanstack/react-query'
import { apiFetch } from '../api/client'

interface ContactIdsResponse {
  contact_ids: string[]
}

/**
 * Manages campaign membership for multiple campaigns at once.
 * Returns a Map<campaignId, { memberIds, toggle }> for use in campaign columns.
 */
export function useCampaignMemberships(campaignIds: string[]) {
  const qc = useQueryClient()

  // Fetch contact IDs for each campaign
  const queries = useQueries({
    queries: campaignIds.map((id) => ({
      queryKey: ['campaign-contact-ids', id],
      queryFn: () => apiFetch<ContactIdsResponse>(`/campaigns/${id}/contact-ids`),
      enabled: !!id,
    })),
  })

  // Build membership sets
  const membershipMap = useMemo(() => {
    const map = new Map<string, Set<string>>()
    campaignIds.forEach((id, i) => {
      const data = queries[i]?.data
      map.set(id, new Set(data?.contact_ids ?? []))
    })
    return map
  }, [campaignIds, queries])

  // Add contact to campaign
  const addMutation = useMutation({
    mutationFn: ({ campaignId, contactId }: { campaignId: string; contactId: string }) =>
      apiFetch(`/campaigns/${campaignId}/contacts`, {
        method: 'POST',
        body: { contact_ids: [contactId] },
      }),
    onMutate: async ({ campaignId, contactId }) => {
      await qc.cancelQueries({ queryKey: ['campaign-contact-ids', campaignId] })
      const prev = qc.getQueryData<ContactIdsResponse>(['campaign-contact-ids', campaignId])
      qc.setQueryData<ContactIdsResponse>(['campaign-contact-ids', campaignId], (old) => ({
        contact_ids: [...(old?.contact_ids ?? []), contactId],
      }))
      return { prev, campaignId }
    },
    onError: (_err, _vars, context) => {
      if (context?.prev) {
        qc.setQueryData(['campaign-contact-ids', context.campaignId], context.prev)
      }
    },
    onSettled: (_data, _err, vars) => {
      qc.invalidateQueries({ queryKey: ['campaign-contact-ids', vars.campaignId] })
      qc.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })

  // Remove contact from campaign
  const removeMutation = useMutation({
    mutationFn: ({ campaignId, contactId }: { campaignId: string; contactId: string }) =>
      apiFetch(`/campaigns/${campaignId}/contacts`, {
        method: 'DELETE',
        body: { contact_ids: [contactId] },
      }),
    onMutate: async ({ campaignId, contactId }) => {
      await qc.cancelQueries({ queryKey: ['campaign-contact-ids', campaignId] })
      const prev = qc.getQueryData<ContactIdsResponse>(['campaign-contact-ids', campaignId])
      qc.setQueryData<ContactIdsResponse>(['campaign-contact-ids', campaignId], (old) => ({
        contact_ids: (old?.contact_ids ?? []).filter((id) => id !== contactId),
      }))
      return { prev, campaignId }
    },
    onError: (_err, _vars, context) => {
      if (context?.prev) {
        qc.setQueryData(['campaign-contact-ids', context.campaignId], context.prev)
      }
    },
    onSettled: (_data, _err, vars) => {
      qc.invalidateQueries({ queryKey: ['campaign-contact-ids', vars.campaignId] })
      qc.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })

  const toggle = async (campaignId: string, contactId: string, isMember: boolean) => {
    if (isMember) {
      await removeMutation.mutateAsync({ campaignId, contactId })
    } else {
      await addMutation.mutateAsync({ campaignId, contactId })
    }
  }

  return { membershipMap, toggle }
}
