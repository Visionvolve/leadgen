import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '../../api/client'
import { useUpdateCampaign } from '../../api/queries/useCampaigns'
import { useToast } from '../ui/Toast'

interface InsightSuggestion {
  field: string
  value: unknown
}

interface Insight {
  type: string
  severity: string
  message: string
  suggestion?: InsightSuggestion
}

interface FeedbackInsightsResponse {
  insights: Insight[]
  stats: {
    total_actions: number
    approval_rate: number
    edit_reasons: Record<string, number>
  }
}

function useFeedbackInsights(campaignId: string) {
  return useQuery({
    queryKey: ['feedback-insights', campaignId],
    queryFn: () => apiFetch<FeedbackInsightsResponse>(`/campaigns/${campaignId}/feedback-insights`),
    enabled: !!campaignId,
    staleTime: 60_000,
    retry: false,
  })
}

interface Props {
  campaignId: string
  generationConfig: Record<string, unknown>
}

const SEVERITY_STYLES: Record<string, string> = {
  warning: 'border-warning/30 bg-warning/5',
  info: 'border-accent-cyan/30 bg-accent-cyan/5',
  error: 'border-error/30 bg-error/5',
}

const SEVERITY_ICON_COLOR: Record<string, string> = {
  warning: 'text-warning',
  info: 'text-accent-cyan',
  error: 'text-error',
}

export function FeedbackInsights({ campaignId, generationConfig }: Props) {
  const { data, isError } = useFeedbackInsights(campaignId)
  const updateCampaign = useUpdateCampaign()
  const { toast } = useToast()
  const qc = useQueryClient()

  if (isError || !data || !data.insights || data.insights.length === 0) {
    return null
  }

  const displayedInsights = data.insights.slice(0, 3)

  const handleApply = async (suggestion: InsightSuggestion) => {
    try {
      await updateCampaign.mutateAsync({
        id: campaignId,
        data: {
          generation_config: { ...generationConfig, [suggestion.field]: suggestion.value },
        },
      })
      toast('Suggestion applied', 'success')
      qc.invalidateQueries({ queryKey: ['feedback-insights', campaignId] })
    } catch {
      toast('Failed to apply suggestion', 'error')
    }
  }

  return (
    <div className="space-y-2">
      {displayedInsights.map((insight, idx) => {
        const style = SEVERITY_STYLES[insight.severity] || SEVERITY_STYLES.info
        const iconColor = SEVERITY_ICON_COLOR[insight.severity] || SEVERITY_ICON_COLOR.info

        return (
          <div
            key={idx}
            className={`flex items-start gap-2.5 px-3 py-2.5 rounded-lg border text-sm ${style}`}
          >
            <span className={`flex-shrink-0 mt-0.5 ${iconColor}`}>
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M8 1.5L1.5 13h13L8 1.5z" />
                <path d="M8 6v3M8 11v.01" />
              </svg>
            </span>
            <div className="flex-1 min-w-0 text-xs text-text-muted">
              {insight.message}
            </div>
            {insight.suggestion && (
              <button
                onClick={() => handleApply(insight.suggestion!)}
                disabled={updateCampaign.isPending}
                className="flex-shrink-0 px-2 py-0.5 text-[10px] font-medium rounded border border-accent/30 text-accent bg-accent/10 hover:bg-accent/20 cursor-pointer transition-colors disabled:opacity-50"
              >
                Apply
              </button>
            )}
          </div>
        )
      })}
      {data.stats.total_actions > 0 && (
        <p className="text-[10px] text-text-dim">
          Based on {data.stats.total_actions} review actions ({Math.round(data.stats.approval_rate * 100)}% approval rate)
        </p>
      )}
    </div>
  )
}
