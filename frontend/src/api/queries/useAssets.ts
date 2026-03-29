import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiUpload } from '../client'

export interface Asset {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  campaign_id: string | null
  metadata: Record<string, unknown>
  created_at: string
}

interface AssetsResponse {
  assets: Asset[]
}

interface DownloadResponse {
  url: string
}

export function useAssets(campaignId?: string | null) {
  return useQuery({
    queryKey: ['assets', campaignId ?? 'all'],
    queryFn: () => {
      const params: Record<string, string> = {}
      if (campaignId) params.campaign_id = campaignId
      return apiFetch<AssetsResponse>('/assets', { params })
    },
  })
}

export function useUploadAsset() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ file, campaignId }: { file: File; campaignId?: string }) => {
      const formData = new FormData()
      formData.append('file', file)
      if (campaignId) formData.append('campaign_id', campaignId)
      return apiUpload<Asset>('/assets/upload', formData)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['assets'] })
    },
  })
}

export function useDeleteAsset() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (assetId: string) =>
      apiFetch<{ ok: boolean }>(`/assets/${assetId}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['assets'] })
    },
  })
}

export function useAssetDownloadUrl(assetId: string | null) {
  return useQuery({
    queryKey: ['asset-download', assetId],
    queryFn: () => apiFetch<DownloadResponse>(`/assets/${assetId}/download`),
    enabled: !!assetId,
  })
}
