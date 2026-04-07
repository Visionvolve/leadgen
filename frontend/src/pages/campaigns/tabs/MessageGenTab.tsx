import { useCallback, useMemo, useState } from 'react'
import {
  useUpdateCampaign,
  useCampaignTemplates,
  type CampaignDetail,
  type TemplateStep,
} from '../../../api/queries/useCampaigns'
import {
  useCostEstimate,
  useStartGeneration,
  type CostEstimateResponse,
} from '../../../api/queries/useCampaignGeneration'
import { useToast } from '../../../components/ui/Toast'
import { Modal } from '../../../components/ui/Modal'
import { GenerationProgressModal } from '../../../components/campaign/GenerationProgressModal'
import { FeedbackInsights } from '../../../components/campaign/FeedbackInsights'
import { EditableSelect, EditableTextarea, FieldGrid, Field } from '../../../components/ui/DetailField'
import { WarningBanner } from '../../../components/ui/WarningBanner'

const TONE_OPTIONS = [
  { value: 'professional', label: 'Professional' },
  { value: 'friendly', label: 'Friendly' },
  { value: 'casual', label: 'Casual' },
  { value: 'bold', label: 'Bold' },
  { value: 'authoritative', label: 'Authoritative' },
  { value: 'empathetic', label: 'Empathetic' },
]

const PERSONALIZATION_LEVELS = [
  { value: 1, label: 'Name only' },
  { value: 2, label: 'Company' },
  { value: 3, label: 'Context' },
  { value: 4, label: 'Hyperpersonalized' },
]

const CHANNEL_ICONS: Record<string, string> = {
  linkedin_connect: 'LI',
  linkedin_message: 'LI',
  email: 'Em',
  call: 'Ph',
}

interface Props {
  campaign: CampaignDetail
  isEditable: boolean
}

export function MessageGenTab({ campaign, isEditable }: Props) {
  const { toast } = useToast()
  const updateCampaign = useUpdateCampaign()
  const { data: templateData } = useCampaignTemplates()
  const costEstimate = useCostEstimate()
  const startGeneration = useStartGeneration()

  // Cost confirm dialog state
  const [showCostDialog, setShowCostDialog] = useState(false)
  const [costData, setCostData] = useState<CostEstimateResponse | null>(null)
  const [skipUnenriched, setSkipUnenriched] = useState(false)

  // Progress modal state
  const [showProgress, setShowProgress] = useState(false)

  // If campaign is currently generating, show progress modal automatically
  const isGenerating = campaign.status === 'Generating'

  const templates = useMemo(() => templateData?.templates ?? [], [templateData])

  const templateConfig: TemplateStep[] = useMemo(() => {
    return (campaign.template_config || []) as TemplateStep[]
  }, [campaign.template_config])

  const generationConfig = useMemo(() => {
    return (campaign.generation_config || {}) as Record<string, unknown>
  }, [campaign.generation_config])

  const enabledSteps = useMemo(
    () => templateConfig.filter((s) => s.enabled),
    [templateConfig],
  )

  const canGenerate =
    (campaign.status === 'Ready' || campaign.status === 'Draft') &&
    campaign.total_contacts > 0 &&
    enabledSteps.length > 0

  const handleLoadTemplate = useCallback(async (templateId: string) => {
    const tpl = templates.find((t) => t.id === templateId)
    if (!tpl) return
    try {
      await updateCampaign.mutateAsync({
        id: campaign.id,
        data: {
          template_config: tpl.steps,
          generation_config: tpl.default_config,
        },
      })
      toast('Template loaded', 'success')
    } catch {
      toast('Failed to load template', 'error')
    }
  }, [templates, campaign.id, updateCampaign, toast])

  const handleToggleStep = useCallback(async (stepIndex: number) => {
    const newConfig = [...templateConfig]
    newConfig[stepIndex] = { ...newConfig[stepIndex], enabled: !newConfig[stepIndex].enabled }
    try {
      await updateCampaign.mutateAsync({
        id: campaign.id,
        data: { template_config: newConfig },
      })
    } catch {
      toast('Failed to update step', 'error')
    }
  }, [templateConfig, campaign.id, updateCampaign, toast])

  const handleToneChange = useCallback(async (_: string, value: string) => {
    const newConfig = { ...generationConfig, tone: value }
    try {
      await updateCampaign.mutateAsync({
        id: campaign.id,
        data: { generation_config: newConfig },
      })
    } catch {
      toast('Failed to update tone', 'error')
    }
  }, [generationConfig, campaign.id, updateCampaign, toast])

  const handleInstructionsChange = useCallback(async (_: string, value: string) => {
    const newConfig = { ...generationConfig, custom_instructions: value }
    try {
      await updateCampaign.mutateAsync({
        id: campaign.id,
        data: { generation_config: newConfig },
      })
    } catch {
      toast('Failed to update instructions', 'error')
    }
  }, [generationConfig, campaign.id, updateCampaign, toast])

  const handlePersonalizationChange = useCallback(async (level: number) => {
    const newConfig = { ...generationConfig, personalization_level: level }
    try {
      await updateCampaign.mutateAsync({
        id: campaign.id,
        data: { generation_config: newConfig },
      })
    } catch {
      toast('Failed to update personalization level', 'error')
    }
  }, [generationConfig, campaign.id, updateCampaign, toast])

  const handleStepToneOverride = useCallback(async (stepIndex: number, tone: string | null) => {
    const newConfig = [...templateConfig]
    const stepConfig = (newConfig[stepIndex] as TemplateStep & { config?: Record<string, unknown> })
    const existingConfig = stepConfig.config || {}
    newConfig[stepIndex] = {
      ...newConfig[stepIndex],
      config: { ...existingConfig, tone: tone || undefined },
    } as TemplateStep & { config: Record<string, unknown> }
    try {
      await updateCampaign.mutateAsync({
        id: campaign.id,
        data: { template_config: newConfig },
      })
    } catch {
      toast('Failed to update step tone', 'error')
    }
  }, [templateConfig, campaign.id, updateCampaign, toast])

  const handleStepFormalityOverride = useCallback(async (stepIndex: number, formality: string | null) => {
    const newConfig = [...templateConfig]
    const stepConfig = (newConfig[stepIndex] as TemplateStep & { config?: Record<string, unknown> })
    const existingConfig = stepConfig.config || {}
    newConfig[stepIndex] = {
      ...newConfig[stepIndex],
      config: { ...existingConfig, formality: formality || undefined },
    } as TemplateStep & { config: Record<string, unknown> }
    try {
      await updateCampaign.mutateAsync({
        id: campaign.id,
        data: { template_config: newConfig },
      })
    } catch {
      toast('Failed to update step formality', 'error')
    }
  }, [templateConfig, campaign.id, updateCampaign, toast])

  // Track which steps have expanded overrides
  const [expandedStepOverrides, setExpandedStepOverrides] = useState<Set<number>>(new Set())

  // Cost estimate -> confirmation dialog
  const handleEstimateCost = useCallback(async () => {
    try {
      const data = await costEstimate.mutateAsync(campaign.id)
      setCostData(data)
      setSkipUnenriched(false)
      setShowCostDialog(true)
    } catch {
      toast('Failed to estimate cost', 'error')
    }
  }, [campaign.id, costEstimate, toast])

  // Confirm generation
  const handleConfirmGenerate = useCallback(async () => {
    setShowCostDialog(false)
    try {
      await startGeneration.mutateAsync({ campaignId: campaign.id, skipUnenriched })
      setShowProgress(true)
    } catch {
      toast('Failed to start generation', 'error')
    }
  }, [campaign.id, startGeneration, toast, skipUnenriched])

  const gaps = costData?.enrichment_gaps

  return (
    <div className="space-y-4">
      {/* Template loader (draft/ready only) */}
      {isEditable && templates.length > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">Load template:</span>
          {templates.map((t) => (
            <button
              key={t.id}
              onClick={() => handleLoadTemplate(t.id)}
              className="px-2 py-0.5 text-xs rounded border border-border bg-surface text-text-muted hover:text-text hover:border-accent cursor-pointer transition-colors"
            >
              {t.name}
            </button>
          ))}
        </div>
      )}

      {/* Step list */}
      {templateConfig.length > 0 ? (
        <div className="space-y-1.5">
          {templateConfig.map((step, idx) => {
            const stepWithConfig = step as TemplateStep & { config?: Record<string, unknown> }
            const stepTone = (stepWithConfig.config?.tone as string) || ''
            const stepFormality = (stepWithConfig.config?.formality as string) || ''
            const isOverrideExpanded = expandedStepOverrides.has(idx)
            const hasOverrides = !!stepTone || !!stepFormality

            return (
              <div key={idx} className="rounded border transition-colors overflow-hidden"
                style={{ borderColor: step.enabled ? undefined : 'transparent' }}
              >
                <div
                  className={`flex items-center gap-3 px-3 py-2 ${
                    step.enabled
                      ? 'border-border bg-surface'
                      : 'border-border/50 bg-surface/50 opacity-50'
                  }`}
                >
                  {isEditable && (
                    <button
                      onClick={() => handleToggleStep(idx)}
                      className={`w-4 h-4 rounded border flex items-center justify-center text-[10px] cursor-pointer transition-colors ${
                        step.enabled
                          ? 'bg-accent border-accent text-white'
                          : 'bg-transparent border-[#8B92A0]/40 text-transparent'
                      }`}
                    >
                      {step.enabled ? '\u2713' : ''}
                    </button>
                  )}
                  <span className="w-6 h-5 flex items-center justify-center text-[9px] font-bold text-text-muted bg-surface-alt rounded">
                    {CHANNEL_ICONS[step.channel] || '?'}
                  </span>
                  <span className="text-sm text-text flex-1">{step.label}</span>
                  {hasOverrides && (
                    <span className="text-[10px] px-1.5 py-0.5 bg-accent-cyan/10 text-accent-cyan rounded">
                      {[stepTone, stepFormality].filter(Boolean).join(', ')}
                    </span>
                  )}
                  <span className="text-xs text-text-dim">{step.channel.replace('_', ' ')}</span>
                  {step.needs_pdf && (
                    <span className="text-[10px] px-1.5 py-0.5 bg-accent/10 text-accent rounded">PDF</span>
                  )}
                  {isEditable && step.enabled && (
                    <button
                      onClick={() => {
                        const next = new Set(expandedStepOverrides)
                        if (isOverrideExpanded) next.delete(idx)
                        else next.add(idx)
                        setExpandedStepOverrides(next)
                      }}
                      className="text-[10px] text-text-dim hover:text-text cursor-pointer bg-transparent border-none transition-colors"
                      title="Step overrides"
                    >
                      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"
                        className={`transition-transform ${isOverrideExpanded ? 'rotate-180' : ''}`}>
                        <path d="M4 6l4 4 4-4" />
                      </svg>
                    </button>
                  )}
                </div>
                {isOverrideExpanded && isEditable && step.enabled && (
                  <div className="px-3 py-2 bg-surface-alt/50 border-t border-border/50 flex items-center gap-4">
                    <div className="flex items-center gap-2">
                      <label className="text-[10px] text-text-dim whitespace-nowrap">Tone override</label>
                      <select
                        value={stepTone}
                        onChange={(e) => handleStepToneOverride(idx, e.target.value || null)}
                        className="px-1.5 py-1 text-xs rounded border border-border bg-surface-alt text-text focus:outline-none focus:border-accent"
                      >
                        <option value="">Campaign default</option>
                        {TONE_OPTIONS.map((t) => (
                          <option key={t.value} value={t.value}>{t.label}</option>
                        ))}
                      </select>
                    </div>
                    <div className="flex items-center gap-2">
                      <label className="text-[10px] text-text-dim whitespace-nowrap">Formality</label>
                      <div className="flex rounded border border-border overflow-hidden">
                        {[
                          { value: '', label: 'Default' },
                          { value: 'formal', label: 'Formal' },
                          { value: 'informal', label: 'Informal' },
                        ].map((opt) => (
                          <button
                            key={opt.value}
                            onClick={() => handleStepFormalityOverride(idx, opt.value || null)}
                            className={`px-2 py-0.5 text-[10px] transition-colors cursor-pointer border-none ${
                              stepFormality === opt.value || (!stepFormality && opt.value === '')
                                ? 'bg-accent/15 text-accent font-medium'
                                : 'bg-surface-alt text-text-dim hover:text-text'
                            }`}
                          >
                            {opt.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <p className="text-xs text-text-muted">No message steps configured. Load a template above to get started.</p>
      )}

      {/* Generation config (tone + personalization + instructions) */}
      {templateConfig.length > 0 && (
        <div className="space-y-3 mt-4">
          {/* Feedback insights banner */}
          <FeedbackInsights campaignId={campaign.id} generationConfig={campaign.generation_config || {}} />

          {typeof generationConfig.custom_instructions === 'string' &&
            generationConfig.custom_instructions.startsWith('Pre-filled from GTM Strategy') ? (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-accent/5 border border-accent/20">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" className="text-accent-hover flex-shrink-0">
                  <path d="M7 1L9 5H13L10 8l1.5 5L7 10 2.5 13 4 8 1 5h4L7 1z" />
                </svg>
                <span className="text-xs font-medium text-accent-hover">Pre-filled from GTM Strategy</span>
                <span className="text-[10px] text-text-dim">You can edit below</span>
              </div>
            ) : null}
          {isEditable ? (
            <>
              {/* Personalization Level */}
              <div>
                <label className="text-xs text-text-muted mb-1.5 block">Personalization Level</label>
                <div className="flex rounded-lg border border-border-solid overflow-hidden">
                  {PERSONALIZATION_LEVELS.map((level) => {
                    const current = (generationConfig.personalization_level as number) || 4
                    const isSelected = current === level.value
                    return (
                      <button
                        key={level.value}
                        onClick={() => handlePersonalizationChange(level.value)}
                        className={`flex-1 px-2 py-1.5 text-xs transition-colors cursor-pointer border-none border-r border-border last:border-r-0 ${
                          isSelected
                            ? 'bg-accent/15 text-accent font-medium'
                            : 'bg-surface-alt text-text-muted hover:text-text hover:bg-surface-alt/80'
                        }`}
                      >
                        {level.label}
                      </button>
                    )
                  })}
                </div>
                <p className="text-[10px] text-text-dim mt-1">
                  Controls how much recipient context is included in the prompt. Higher levels produce more tailored messages but require enrichment data.
                </p>
              </div>

              <EditableSelect
                label="Tone"
                name="tone"
                value={(generationConfig.tone as string) || 'professional'}
                options={TONE_OPTIONS}
                onChange={handleToneChange}
              />
              <EditableTextarea
                label="Custom Instructions"
                name="custom_instructions"
                value={(generationConfig.custom_instructions as string) || ''}
                onChange={handleInstructionsChange}
                rows={3}
                maxLength={2000}
                placeholder="e.g., Mention our Series A funding. Reference prospect's recent company news. Keep under 100 words."
                helpText="These instructions are appended to every message generation prompt for this campaign."
              />
            </>
          ) : (
            <FieldGrid>
              <Field
                label="Personalization Level"
                value={PERSONALIZATION_LEVELS.find((l) => l.value === ((generationConfig.personalization_level as number) || 4))?.label || 'Context'}
              />
              <Field label="Tone" value={(generationConfig.tone as string) || 'professional'} />
              <Field label="Custom Instructions" value={(generationConfig.custom_instructions as string) || '-'} />
            </FieldGrid>
          )}
        </div>
      )}

      {/* Generate actions */}
      {templateConfig.length > 0 && (
        <div className="flex items-center gap-3 pt-4 border-t border-border">
          {canGenerate && (
            <>
              <button
                onClick={handleEstimateCost}
                disabled={costEstimate.isPending}
                className="px-4 py-2 text-sm font-medium rounded border border-border text-text-muted hover:text-text hover:border-accent-cyan cursor-pointer bg-transparent transition-colors disabled:opacity-50"
              >
                {costEstimate.isPending ? 'Estimating...' : 'Estimate Cost'}
              </button>
              <button
                onClick={handleEstimateCost}
                disabled={startGeneration.isPending || costEstimate.isPending}
                className="px-4 py-2 text-sm font-medium rounded bg-accent text-white border-none cursor-pointer hover:bg-accent-hover transition-colors disabled:opacity-50"
              >
                {startGeneration.isPending ? 'Starting...' : costEstimate.isPending ? 'Estimating...' : 'Estimate & Generate'}
              </button>
            </>
          )}
          {isGenerating && (
            <button
              onClick={() => setShowProgress(true)}
              className="px-4 py-2 text-sm font-medium rounded border border-accent/30 text-accent-hover bg-accent/10 cursor-pointer hover:bg-accent/20 transition-colors"
            >
              View Progress
            </button>
          )}
          {!canGenerate && !isGenerating && campaign.total_contacts === 0 && (
            <p className="text-xs text-text-dim">Add contacts to the campaign before generating messages.</p>
          )}
          {!canGenerate && !isGenerating && campaign.total_contacts > 0 && enabledSteps.length === 0 && (
            <p className="text-xs text-text-dim">Enable at least one message step to generate.</p>
          )}
        </div>
      )}

      {/* Cost confirmation dialog */}
      <Modal
        open={showCostDialog}
        onClose={() => setShowCostDialog(false)}
        title="Confirm Generation"
        actions={
          <>
            <button
              onClick={() => setShowCostDialog(false)}
              className="px-3 py-1.5 text-sm rounded border border-border text-text-muted hover:text-text cursor-pointer bg-transparent transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleConfirmGenerate}
              disabled={startGeneration.isPending}
              className="px-4 py-1.5 text-sm font-medium rounded bg-accent text-white border-none cursor-pointer hover:bg-accent-hover transition-colors disabled:opacity-50"
            >
              {startGeneration.isPending ? 'Starting...' : 'Generate'}
            </button>
          </>
        }
      >
        {costData && (
          <div className="space-y-4">
            <p className="text-sm text-text">
              Generate{' '}
              <span className="font-semibold text-accent-cyan">{costData.total_messages} messages</span>
              {' '}for{' '}
              <span className="font-semibold text-accent-cyan">{costData.total_contacts} contacts</span>?
            </p>

            {/* Enrichment gap warning */}
            {gaps && gaps.unenriched_contacts > 0 && (
              <div className="space-y-2">
                <WarningBanner
                  variant="warning"
                  message={
                    <span>
                      <strong>{gaps.unenriched_contacts}</strong> of {gaps.total_contacts} contacts
                      have not been fully enriched. Messages for these contacts may be lower quality.
                    </span>
                  }
                />
                <label className="flex items-center gap-2 text-xs text-text-muted cursor-pointer">
                  <input
                    type="checkbox"
                    checked={skipUnenriched}
                    onChange={(e) => setSkipUnenriched(e.target.checked)}
                    className="rounded border-border accent-accent"
                  />
                  Skip unenriched contacts ({gaps.enriched_contacts} of {gaps.total_contacts} will be generated)
                </label>
              </div>
            )}

            {/* Step breakdown */}
            {costData.by_step && costData.by_step.length > 0 && (
              <div className="space-y-1">
                {costData.by_step.map((step) => (
                  <div key={step.step} className="flex items-center justify-between text-xs">
                    <span className="text-text-muted">
                      Step {step.step}: {step.label}
                      <span className="text-text-dim ml-1">({step.channel.replace('_', ' ')})</span>
                    </span>
                    <span className="text-text-dim">{step.count} msgs</span>
                  </div>
                ))}
              </div>
            )}

            {/* Estimated cost */}
            <div className="flex items-center justify-between px-4 py-3 bg-surface-alt rounded-lg border border-border">
              <span className="text-sm text-text-muted">Estimated cost</span>
              <span className="text-lg font-semibold text-accent-cyan">
                {Math.round(costData.estimated_cost * 1000)} credits
              </span>
            </div>
          </div>
        )}
      </Modal>

      {/* Generation progress modal */}
      <GenerationProgressModal
        campaignId={campaign.id}
        isOpen={showProgress || isGenerating}
        onClose={() => setShowProgress(false)}
      />
    </div>
  )
}
