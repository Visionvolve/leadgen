import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { apiFetch } from '../client'

interface ContactIdsResponse {
  contact_ids: string[]
}

/**
 * Tracks which contacts belong to a campaign.
 * Provides O(1) membership lookup via Set and optimistic toggle.
 */
export function useCampaignMembership(campaignId: string | null) {
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['campaign-contact-ids', campaignId],
    queryFn: () => apiFetch<ContactIdsResponse>(`/campaigns/${campaignId}/contact-ids`),
    enabled: !!campaignId,
  })

  const memberIds = new Set(data?.contact_ids ?? [])

  const addMutation = useMutation({
    mutationFn: (contactId: string) =>
      apiFetch(`/campaigns/${campaignId}/contacts`, {
        method: 'POST',
        body: { contact_ids: [contactId] },
      }),
    onMutate: async (contactId) => {
      await qc.cancelQueries({ queryKey: ['campaign-contact-ids', campaignId] })
      const prev = qc.getQueryData<ContactIdsResponse>(['campaign-contact-ids', campaignId])
      qc.setQueryData<ContactIdsResponse>(['campaign-contact-ids', campaignId], (old) => ({
        contact_ids: [...(old?.contact_ids ?? []), contactId],
      }))
      return { prev }
    },
    onError: (_err, _contactId, context) => {
      if (context?.prev) {
        qc.setQueryData(['campaign-contact-ids', campaignId], context.prev)
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['campaign-contact-ids', campaignId] })
      qc.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })

  const removeMutation = useMutation({
    mutationFn: (contactId: string) =>
      apiFetch(`/campaigns/${campaignId}/contacts`, {
        method: 'DELETE',
        body: { contact_ids: [contactId] },
      }),
    onMutate: async (contactId) => {
      await qc.cancelQueries({ queryKey: ['campaign-contact-ids', campaignId] })
      const prev = qc.getQueryData<ContactIdsResponse>(['campaign-contact-ids', campaignId])
      qc.setQueryData<ContactIdsResponse>(['campaign-contact-ids', campaignId], (old) => ({
        contact_ids: (old?.contact_ids ?? []).filter((id) => id !== contactId),
      }))
      return { prev }
    },
    onError: (_err, _contactId, context) => {
      if (context?.prev) {
        qc.setQueryData(['campaign-contact-ids', campaignId], context.prev)
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['campaign-contact-ids', campaignId] })
      qc.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })

  const toggle = async (contactId: string, isMember: boolean) => {
    if (isMember) {
      await removeMutation.mutateAsync(contactId)
    } else {
      await addMutation.mutateAsync(contactId)
    }
  }

  return {
    memberIds,
    isLoading,
    toggle,
    isToggling: addMutation.isPending || removeMutation.isPending,
  }
}
