import { useState, useCallback, useRef } from 'react'
import { PreviewModal } from '../../../components/campaign/PreviewModal'
import {
  useCampaignSteps,
  useAddCampaignStep,
  useUpdateCampaignStep,
  useDeleteCampaignStep,
  useReorderCampaignSteps,
  usePopulateFromTemplate,
  useAiDesignSteps,
  useConfirmAiDesign,
  useFeedbackSummary,
  useSequence,
  useUpdateSequenceStep,
  type CampaignStep,
  type ExampleMessage,
  type StepConfig,
  type StepCondition,
  type ExecutionStatus,
  type AiDesignProposedStep,
  type FeedbackSummary,
} from '../../../api/queries/useCampaignSteps'
import { useCampaignTemplates } from '../../../api/queries/useCampaigns'
import { useAssets, useUploadAsset, type Asset } from '../../../api/queries/useAssets'
import { useToast } from '../../../components/ui/Toast'
import { SectionDivider } from '../../../components/ui/DetailField'

// ── Constants ────────────────────────────────────────────

const CHANNEL_OPTIONS = [
  { value: 'linkedin_connect', label: 'LinkedIn Connect' },
  { value: 'linkedin_message', label: 'LinkedIn Message' },
  { value: 'email', label: 'Email' },
  { value: 'call', label: 'Call Script' },
]

const CHANNEL_MAX_LENGTH: Record<string, number> = {
  linkedin_connect: 300,
  linkedin_message: 1900,
  email: 5000,
  call: 2000,
}

const CHANNEL_ICONS: Record<string, string> = {
  linkedin_connect: 'LI',
  linkedin_message: 'LI',
  email: 'Em',
  call: 'Ph',
}

const TONE_OPTIONS = [
  { value: 'professional', label: 'Professional' },
  { value: 'friendly', label: 'Friendly' },
  { value: 'casual', label: 'Casual' },
  { value: 'bold', label: 'Bold' },
  { value: 'authoritative', label: 'Authoritative' },
  { value: 'empathetic', label: 'Empathetic' },
]

const CONDITION_OPTIONS: { value: StepCondition; label: string }[] = [
  { value: 'always', label: 'Always' },
  { value: 'no_response', label: 'No Response' },
  { value: 'opened_not_replied', label: 'Opened, Not Replied' },
]

const EXECUTION_STATUS_STYLES: Record<ExecutionStatus, { color: string; label: string }> = {
  pending: { color: 'bg-[#8B92A0]/15 text-[#8B92A0] border-[#8B92A0]/30', label: 'Pending' },
  active: { color: 'bg-[#00B8CF]/15 text-[#00B8CF] border-[#00B8CF]/30', label: 'Active' },
  completed: { color: 'bg-success/15 text-success border-success/30', label: 'Completed' },
  skipped: { color: 'bg-warning/15 text-warning border-warning/30', label: 'Skipped' },
}

// ── Props ────────────────────────────────────────────────

interface Props {
  campaignId: string
  isEditable: boolean
}

// ── StepsTab ─────────────────────────────────────────────

export function StepsTab({ campaignId, isEditable }: Props) {
  const { toast } = useToast()
  const { data, isLoading } = useCampaignSteps(campaignId)
  const { data: templateData } = useCampaignTemplates()
  const addStep = useAddCampaignStep()
  const updateStep = useUpdateCampaignStep()
  const deleteStep = useDeleteCampaignStep()
  const reorderSteps = useReorderCampaignSteps()
  const populateFromTemplate = usePopulateFromTemplate()
  const aiDesign = useAiDesignSteps()
  const confirmAiDesign = useConfirmAiDesign()
  const { data: feedbackData } = useFeedbackSummary(campaignId)

  // Sequence data
  const { data: sequenceData } = useSequence(campaignId)
  const updateSequenceStep = useUpdateSequenceStep()

  const steps = data?.steps ?? []
  const sequenceSteps = sequenceData?.steps ?? []
  const templates = templateData?.templates ?? []

  // View toggle: 'editor' (existing) or 'sequence' (timeline)
  const [view, setView] = useState<'editor' | 'sequence'>('editor')
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewStepPosition, setPreviewStepPosition] = useState<number>(1)

  // Track which step card is expanded for config editing
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Template dropdown
  const [selectedTemplateId, setSelectedTemplateId] = useState('')

  // AI design state
  const [aiGoal, setAiGoal] = useState('')
  const [aiChannelPref, setAiChannelPref] = useState('')
  const [aiNumSteps, setAiNumSteps] = useState<number | ''>('')
  const [aiProposal, setAiProposal] = useState<{ steps: AiDesignProposedStep[]; reasoning: string } | null>(null)
  const [editedProposal, setEditedProposal] = useState<AiDesignProposedStep[]>([])
  const [showAiDesigner, setShowAiDesigner] = useState(false)

  const toggleExpand = useCallback((id: string) => {
    setExpandedId((prev) => (prev === id ? null : id))
  }, [])

  // ── Add step ──

  const handleAddStep = useCallback(async () => {
    try {
      const result = await addStep.mutateAsync({
        campaignId,
        data: {
          channel: 'linkedin_message',
          day_offset: 0,
          label: `Step ${steps.length + 1}`,
          config: { max_length: CHANNEL_MAX_LENGTH.linkedin_message, tone: 'professional', language: 'en' },
        },
      })
      setExpandedId(result.id)
      toast('Step added', 'success')
    } catch {
      toast('Failed to add step', 'error')
    }
  }, [campaignId, steps.length, addStep, toast])

  // ── Delete step ──

  const handleDelete = useCallback(async (stepId: string) => {
    try {
      await deleteStep.mutateAsync({ campaignId, stepId })
      if (expandedId === stepId) setExpandedId(null)
      toast('Step deleted', 'success')
    } catch {
      toast('Failed to delete step', 'error')
    }
  }, [campaignId, deleteStep, expandedId, toast])

  // ── Reorder ──

  const handleMoveUp = useCallback(async (index: number) => {
    if (index === 0) return
    const newOrder = steps.map((s) => s.id)
    ;[newOrder[index - 1], newOrder[index]] = [newOrder[index], newOrder[index - 1]]
    try {
      await reorderSteps.mutateAsync({ campaignId, order: newOrder })
    } catch {
      toast('Failed to reorder', 'error')
    }
  }, [campaignId, steps, reorderSteps, toast])

  const handleMoveDown = useCallback(async (index: number) => {
    if (index === steps.length - 1) return
    const newOrder = steps.map((s) => s.id)
    ;[newOrder[index], newOrder[index + 1]] = [newOrder[index + 1], newOrder[index]]
    try {
      await reorderSteps.mutateAsync({ campaignId, order: newOrder })
    } catch {
      toast('Failed to reorder', 'error')
    }
  }, [campaignId, steps, reorderSteps, toast])

  // ── Update step field ──

  const handleUpdateField = useCallback(async (
    step: CampaignStep,
    field: 'channel' | 'day_offset' | 'label' | 'config',
    value: unknown,
  ) => {
    try {
      await updateStep.mutateAsync({
        campaignId,
        stepId: step.id,
        data: { [field]: value },
      })
    } catch {
      toast('Failed to update step', 'error')
    }
  }, [campaignId, updateStep, toast])

  // ── Populate from template ──

  const handlePopulateFromTemplate = useCallback(async () => {
    if (!selectedTemplateId) return
    try {
      await populateFromTemplate.mutateAsync({ campaignId, templateId: selectedTemplateId })
      setSelectedTemplateId('')
      toast('Steps populated from template', 'success')
    } catch {
      toast('Failed to populate from template', 'error')
    }
  }, [campaignId, selectedTemplateId, populateFromTemplate, toast])

  // ── AI Design ──

  const handleAiDesign = useCallback(async () => {
    if (!aiGoal.trim()) return
    try {
      const result = await aiDesign.mutateAsync({
        campaignId,
        goal: aiGoal.trim(),
        channel_preference: aiChannelPref || undefined,
        num_steps: aiNumSteps || undefined,
      })
      setAiProposal(result)
      setEditedProposal(result.steps.map((s) => ({ ...s, config: { ...s.config } })))
    } catch {
      toast('AI design failed', 'error')
    }
  }, [campaignId, aiGoal, aiChannelPref, aiNumSteps, aiDesign, toast])

  const handleAiConfirm = useCallback(async () => {
    if (!editedProposal.length) return
    try {
      await confirmAiDesign.mutateAsync({ campaignId, steps: editedProposal })
      setAiProposal(null)
      setEditedProposal([])
      setShowAiDesigner(false)
      setAiGoal('')
      setAiChannelPref('')
      setAiNumSteps('')
      toast('Steps saved from AI design', 'success')
    } catch {
      toast('Failed to save steps', 'error')
    }
  }, [campaignId, editedProposal, confirmAiDesign, toast])

  const handleAiCancel = useCallback(() => {
    setAiProposal(null)
    setEditedProposal([])
  }, [])

  const handleEditProposedStep = useCallback((index: number, field: string, value: unknown) => {
    setEditedProposal((prev) =>
      prev.map((s, i) => {
        if (i !== index) return s
        if (field === 'config') return { ...s, config: value as StepConfig }
        return { ...s, [field]: value }
      }),
    )
  }, [])

  // ── Sequence step updates ──

  const handleUpdateSequenceStep = useCallback(async (
    stepNumber: number,
    data: { condition?: StepCondition; execution_status?: ExecutionStatus; day_offset?: number },
  ) => {
    try {
      await updateSequenceStep.mutateAsync({ campaignId, stepNumber, data })
    } catch {
      toast('Failed to update step', 'error')
    }
  }, [campaignId, updateSequenceStep, toast])

  const handleExecuteNow = useCallback(async (stepNumber: number) => {
    try {
      await updateSequenceStep.mutateAsync({
        campaignId,
        stepNumber,
        data: { execution_status: 'active' },
      })
      toast('Step activated', 'success')
    } catch {
      toast('Failed to activate step', 'error')
    }
  }, [campaignId, updateSequenceStep, toast])

  // ── Loading ──

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="w-6 h-6 border-2 border-border border-t-accent rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="max-w-2xl space-y-4">
      {/* View toggle + Preview action */}
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1 p-0.5 bg-surface-alt/50 rounded-md w-fit">
          <button
            onClick={() => setView('editor')}
            className={`px-3 py-1 text-xs font-medium rounded transition-colors border-none cursor-pointer ${
              view === 'editor'
                ? 'bg-surface text-text shadow-sm'
                : 'bg-transparent text-text-muted hover:text-text'
            }`}
          >
            Editor
          </button>
          <button
            onClick={() => setView('sequence')}
            className={`px-3 py-1 text-xs font-medium rounded transition-colors border-none cursor-pointer ${
              view === 'sequence'
                ? 'bg-surface text-text shadow-sm'
                : 'bg-transparent text-text-muted hover:text-text'
            }`}
          >
            Sequence
          </button>
        </div>
        {steps.length > 0 && (
          <button
            data-testid="steps-preview-button"
            onClick={() => {
              setPreviewStepPosition(steps[0]?.position ?? 1)
              setPreviewOpen(true)
            }}
            className="ml-auto px-3 py-1.5 text-xs bg-surface border border-border text-text rounded-md hover:bg-surface-alt transition-colors flex items-center gap-1.5"
            title="Preview the first step rendered for a sample contact"
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M1.5 8s2.5-5 6.5-5 6.5 5 6.5 5-2.5 5-6.5 5-6.5-5-6.5-5z" />
              <circle cx="8" cy="8" r="2" />
            </svg>
            Preview
          </button>
        )}
      </div>

      {/* Sequence Timeline View */}
      {view === 'sequence' && (
        <SequenceTimeline
          steps={sequenceSteps.length > 0 ? sequenceSteps : steps}
          onUpdateStep={handleUpdateSequenceStep}
          onExecuteNow={handleExecuteNow}
          isUpdating={updateSequenceStep.isPending}
        />
      )}

      {/* Editor View */}
      {view === 'editor' && <>
      {/* From template */}
      {isEditable && templates.length > 0 && (
        <div className="flex items-center gap-2">
          <select
            value={selectedTemplateId}
            onChange={(e) => setSelectedTemplateId(e.target.value)}
            className="px-2 py-1.5 text-xs rounded border border-border bg-surface text-text focus:outline-none focus:border-accent"
          >
            <option value="">Load from template...</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
          <button
            onClick={handlePopulateFromTemplate}
            disabled={!selectedTemplateId || populateFromTemplate.isPending}
            className="px-3 py-1.5 text-xs font-medium rounded border border-border text-text-muted hover:text-text hover:border-accent cursor-pointer bg-transparent transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {populateFromTemplate.isPending ? 'Loading...' : 'Apply'}
          </button>
          {steps.length > 0 && (
            <span className="text-[10px] text-warning">Replaces all existing steps</span>
          )}
        </div>
      )}

      {/* AI Step Designer */}
      {isEditable && (
        <div className="space-y-3">
          {!showAiDesigner ? (
            <button
              onClick={() => setShowAiDesigner(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded border border-border text-text-muted hover:text-text hover:border-accent cursor-pointer bg-transparent transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M7 1v4M5 3h4M2 7l2.5 1M9.5 8L12 7M4.5 11.5L6 9M8 9l1.5 2.5" />
              </svg>
              Let AI design steps
            </button>
          ) : (
            <div className="border border-accent/30 rounded-lg p-4 bg-surface-alt/20 space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold text-text">AI Step Designer</h4>
                <button
                  onClick={() => { setShowAiDesigner(false); handleAiCancel() }}
                  className="text-[10px] text-text-dim hover:text-text bg-transparent border-none cursor-pointer transition-colors"
                >
                  Close
                </button>
              </div>

              {!aiProposal ? (
                <>
                  {/* Goal input */}
                  <div>
                    <label className="text-xs text-text-muted mb-1 block">Describe your outreach goal</label>
                    <textarea
                      value={aiGoal}
                      onChange={(e) => setAiGoal(e.target.value)}
                      rows={2}
                      placeholder="e.g., 3-step LinkedIn outreach for SaaS CTOs, warm intro then value pitch"
                      className="w-full px-2 py-1.5 text-sm rounded border border-border bg-surface text-text focus:outline-none focus:border-accent resize-none"
                    />
                  </div>

                  {/* Options row */}
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs text-text-muted mb-1 block">Channel preference</label>
                      <select
                        value={aiChannelPref}
                        onChange={(e) => setAiChannelPref(e.target.value)}
                        className="w-full px-2 py-1.5 text-xs rounded border border-border bg-surface text-text focus:outline-none focus:border-accent"
                      >
                        <option value="">Any</option>
                        {CHANNEL_OPTIONS.map((c) => (
                          <option key={c.value} value={c.value}>{c.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="text-xs text-text-muted mb-1 block">Number of steps</label>
                      <input
                        type="number"
                        min={1}
                        max={10}
                        value={aiNumSteps}
                        onChange={(e) => setAiNumSteps(e.target.value ? parseInt(e.target.value, 10) : '')}
                        placeholder="Auto"
                        className="w-full px-2 py-1.5 text-xs rounded border border-border bg-surface text-text focus:outline-none focus:border-accent"
                      />
                    </div>
                  </div>

                  {/* Design button */}
                  <button
                    onClick={handleAiDesign}
                    disabled={!aiGoal.trim() || aiDesign.isPending}
                    className="px-4 py-2 text-xs font-medium rounded bg-accent text-white hover:bg-accent/90 cursor-pointer border-none transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                  >
                    {aiDesign.isPending ? (
                      <>
                        <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        Designing...
                      </>
                    ) : (
                      'Design Steps'
                    )}
                  </button>

                  {steps.length > 0 && (
                    <p className="text-[10px] text-warning">This will replace all existing steps when confirmed.</p>
                  )}
                </>
              ) : (
                /* Proposal preview */
                <div className="space-y-3">
                  {/* Reasoning */}
                  <div className="px-3 py-2 rounded bg-surface-alt/50 border border-border/50">
                    <p className="text-xs text-text-muted italic">{aiProposal.reasoning}</p>
                  </div>

                  {/* Proposed steps */}
                  <div className="space-y-2">
                    {editedProposal.map((step, idx) => (
                      <div key={idx} className="border border-border rounded-lg bg-surface p-3 space-y-2">
                        <div className="flex items-center gap-2">
                          <span className="w-5 h-5 flex items-center justify-center text-[10px] font-bold text-text-muted bg-surface-alt rounded flex-shrink-0">
                            {idx + 1}
                          </span>
                          <input
                            type="text"
                            value={step.label}
                            onChange={(e) => handleEditProposedStep(idx, 'label', e.target.value)}
                            className="flex-1 px-2 py-1 text-sm rounded border border-border bg-surface-alt text-text focus:outline-none focus:border-accent"
                          />
                          <span className="text-[10px] text-text-dim flex-shrink-0">Day {step.day_offset}</span>
                        </div>
                        <div className="grid grid-cols-3 gap-2">
                          <div>
                            <label className="text-[10px] text-text-dim mb-0.5 block">Channel</label>
                            <select
                              value={step.channel}
                              onChange={(e) => handleEditProposedStep(idx, 'channel', e.target.value)}
                              className="w-full px-1.5 py-1 text-xs rounded border border-border bg-surface-alt text-text focus:outline-none focus:border-accent"
                            >
                              {CHANNEL_OPTIONS.map((c) => (
                                <option key={c.value} value={c.value}>{c.label}</option>
                              ))}
                            </select>
                          </div>
                          <div>
                            <label className="text-[10px] text-text-dim mb-0.5 block">Day offset</label>
                            <input
                              type="number"
                              min={0}
                              value={step.day_offset}
                              onChange={(e) => handleEditProposedStep(idx, 'day_offset', parseInt(e.target.value, 10) || 0)}
                              className="w-full px-1.5 py-1 text-xs rounded border border-border bg-surface-alt text-text focus:outline-none focus:border-accent"
                            />
                          </div>
                          <div>
                            <label className="text-[10px] text-text-dim mb-0.5 block">Tone</label>
                            <select
                              value={step.config.tone ?? 'informal'}
                              onChange={(e) => handleEditProposedStep(idx, 'config', { ...step.config, tone: e.target.value })}
                              className="w-full px-1.5 py-1 text-xs rounded border border-border bg-surface-alt text-text focus:outline-none focus:border-accent"
                            >
                              <option value="formal">Formal</option>
                              <option value="informal">Informal</option>
                            </select>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Action buttons */}
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleAiConfirm}
                      disabled={confirmAiDesign.isPending}
                      className="px-4 py-2 text-xs font-medium rounded bg-accent text-white hover:bg-accent/90 cursor-pointer border-none transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    >
                      {confirmAiDesign.isPending ? (
                        <>
                          <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                          Saving...
                        </>
                      ) : (
                        'Accept & Save'
                      )}
                    </button>
                    <button
                      onClick={handleAiCancel}
                      className="px-4 py-2 text-xs font-medium rounded border border-border text-text-muted hover:text-text hover:border-accent cursor-pointer bg-transparent transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={() => { handleAiCancel(); }}
                      className="px-4 py-2 text-xs font-medium rounded border border-border text-text-muted hover:text-text hover:border-accent cursor-pointer bg-transparent transition-colors ml-auto"
                    >
                      Redesign
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Step cards */}
      {steps.length > 0 ? (
        <div className="space-y-2">
          {steps.map((step, idx) => (
            <StepCard
              key={step.id}
              step={step}
              index={idx}
              total={steps.length}
              isEditable={isEditable}
              isExpanded={expandedId === step.id}
              feedbackSummary={feedbackData ?? null}
              onToggleExpand={() => toggleExpand(step.id)}
              onMoveUp={() => handleMoveUp(idx)}
              onMoveDown={() => handleMoveDown(idx)}
              onDelete={() => handleDelete(step.id)}
              onUpdateField={(field, value) => handleUpdateField(step, field, value)}
            />
          ))}
        </div>
      ) : (
        <p className="text-xs text-text-muted py-4">
          No steps configured. Add steps manually or load from a template.
        </p>
      )}

      {/* Add step button */}
      {isEditable && (
        <button
          onClick={handleAddStep}
          disabled={addStep.isPending}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded border border-dashed border-border text-text-muted hover:text-text hover:border-accent cursor-pointer bg-transparent transition-colors disabled:opacity-50 w-full justify-center"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M7 3v8M3 7h8" />
          </svg>
          {addStep.isPending ? 'Adding...' : 'Add Step'}
        </button>
      )}
      </>}

      <PreviewModal
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        campaignId={campaignId}
        stepPosition={previewStepPosition}
      />
    </div>
  )
}

// ── SequenceTimeline ─────────────────────────────────────

interface SequenceTimelineProps {
  steps: CampaignStep[]
  onUpdateStep: (stepNumber: number, data: { condition?: StepCondition; execution_status?: ExecutionStatus; day_offset?: number }) => void
  onExecuteNow: (stepNumber: number) => void
  isUpdating: boolean
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function SequenceTimeline({ steps, onUpdateStep, onExecuteNow, isUpdating }: SequenceTimelineProps) {
  if (steps.length === 0) {
    return (
      <p className="text-xs text-text-muted py-4">
        No steps configured. Switch to Editor to add steps.
      </p>
    )
  }

  return (
    <div className="space-y-0">
      {steps.map((step, idx) => {
        const channelLabel = CHANNEL_OPTIONS.find((c) => c.value === step.channel)?.label ?? step.channel
        const status = step.execution_status ?? 'pending'
        const statusStyle = EXECUTION_STATUS_STYLES[status] ?? EXECUTION_STATUS_STYLES.pending
        const condition = step.condition ?? 'always'
        const conditionLabel = CONDITION_OPTIONS.find((c) => c.value === condition)?.label ?? condition
        const isFirst = idx === 0
        const isLast = idx === steps.length - 1

        // Day gap to next step
        const nextStep = !isLast ? steps[idx + 1] : null
        const dayGap = nextStep ? nextStep.day_offset - step.day_offset : 0

        return (
          <div key={step.id}>
            {/* Step row */}
            <div className="flex items-start gap-3 group">
              {/* Timeline track */}
              <div className="flex flex-col items-center w-6 flex-shrink-0">
                {/* Connector line above (hidden for first) */}
                <div className={`w-px h-3 ${isFirst ? 'bg-transparent' : status === 'completed' ? 'bg-success/40' : 'bg-border'}`} />
                {/* Node dot */}
                <div className={`w-3 h-3 rounded-full border-2 flex-shrink-0 ${
                  status === 'completed' ? 'bg-success border-success' :
                  status === 'active' ? 'bg-[#00B8CF] border-[#00B8CF] animate-pulse' :
                  status === 'skipped' ? 'bg-warning/50 border-warning' :
                  'bg-surface border-[#8B92A0]'
                }`} />
                {/* Connector line below (hidden for last) */}
                {!isLast && (
                  <div className={`w-px flex-1 min-h-[12px] ${status === 'completed' ? 'bg-success/40' : 'border-l border-dashed border-border'}`} />
                )}
              </div>

              {/* Step content card */}
              <div className="flex-1 border border-border rounded-lg bg-surface px-3 py-2.5 mb-1">
                {/* Top row: label, channel, day, badges */}
                <div className="flex items-center gap-2 flex-wrap">
                  {/* Position */}
                  <span className="w-5 h-5 flex items-center justify-center text-[10px] font-bold text-text-muted bg-surface-alt rounded flex-shrink-0">
                    {step.position}
                  </span>

                  {/* Channel icon */}
                  <span className="text-[9px] font-bold text-text-dim bg-surface-alt px-1.5 py-0.5 rounded flex-shrink-0">
                    {CHANNEL_ICONS[step.channel] || '?'}
                  </span>

                  {/* Label */}
                  <span className="text-sm text-text font-medium truncate">
                    {step.label || channelLabel}
                  </span>

                  {/* Spacer */}
                  <div className="flex-1" />

                  {/* Day offset badge */}
                  <span className="text-[10px] text-text-dim bg-surface-alt px-1.5 py-0.5 rounded flex-shrink-0">
                    Day {step.day_offset}
                  </span>

                  {/* Condition badge */}
                  <span className="text-[10px] text-text-muted bg-surface-alt/80 px-1.5 py-0.5 rounded border border-border/50 flex-shrink-0">
                    {conditionLabel}
                  </span>

                  {/* Execution status badge */}
                  <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded border flex-shrink-0 ${statusStyle.color}`}>
                    {statusStyle.label}
                  </span>
                </div>

                {/* Bottom row: timestamps + controls */}
                <div className="flex items-center gap-3 mt-1.5">
                  {/* Timestamps */}
                  {step.started_at && (
                    <span className="text-[10px] text-text-dim" title="Started">
                      Started: {formatTimestamp(step.started_at)}
                    </span>
                  )}
                  {step.completed_at && (
                    <span className="text-[10px] text-text-dim" title="Completed">
                      Completed: {formatTimestamp(step.completed_at)}
                    </span>
                  )}

                  <div className="flex-1" />

                  {/* Condition selector */}
                  <select
                    value={condition}
                    onChange={(e) => onUpdateStep(step.position, { condition: e.target.value as StepCondition })}
                    className="px-1.5 py-0.5 text-[10px] rounded border border-border bg-surface-alt text-text focus:outline-none focus:border-accent"
                  >
                    {CONDITION_OPTIONS.map((c) => (
                      <option key={c.value} value={c.value}>{c.label}</option>
                    ))}
                  </select>

                  {/* Day offset control */}
                  <div className="flex items-center gap-1">
                    <label className="text-[10px] text-text-dim">Day:</label>
                    <input
                      type="number"
                      min={0}
                      value={step.day_offset}
                      onChange={(e) => onUpdateStep(step.position, { day_offset: parseInt(e.target.value, 10) || 0 })}
                      className="w-12 px-1 py-0.5 text-[10px] rounded border border-border bg-surface-alt text-text focus:outline-none focus:border-accent text-center"
                    />
                  </div>

                  {/* Execute now button for pending steps */}
                  {status === 'pending' && (
                    <button
                      onClick={() => onExecuteNow(step.position)}
                      disabled={isUpdating}
                      className="px-2 py-0.5 text-[10px] font-medium rounded bg-[#00B8CF]/15 text-[#00B8CF] border border-[#00B8CF]/30 hover:bg-[#00B8CF]/25 cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Execute Now
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* Day gap connector label */}
            {!isLast && dayGap > 0 && (
              <div className="flex items-center gap-3 py-0.5">
                <div className="w-6 flex items-center justify-center flex-shrink-0">
                  <div className={`w-px h-4 ${status === 'completed' ? 'bg-success/40' : 'border-l border-dashed border-border'}`} />
                </div>
                <span className="text-[10px] text-text-dim italic">
                  {dayGap} day{dayGap !== 1 ? 's' : ''} wait
                </span>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── StepCard ─────────────────────────────────────────────

interface StepCardProps {
  step: CampaignStep
  index: number
  total: number
  isEditable: boolean
  isExpanded: boolean
  feedbackSummary: FeedbackSummary | null
  onToggleExpand: () => void
  onMoveUp: () => void
  onMoveDown: () => void
  onDelete: () => void
  onUpdateField: (field: 'channel' | 'day_offset' | 'label' | 'config', value: unknown) => void
}

function StepCard({
  step,
  index,
  total,
  isEditable,
  isExpanded,
  feedbackSummary,
  onToggleExpand,
  onMoveUp,
  onMoveDown,
  onDelete,
  onUpdateField,
}: StepCardProps) {
  const config = step.config || {}
  const maxLength = config.max_length ?? CHANNEL_MAX_LENGTH[step.channel] ?? 1900
  const channelLabel = CHANNEL_OPTIONS.find((c) => c.value === step.channel)?.label ?? step.channel

  // Feedback stats for this step
  const stepFeedback = feedbackSummary?.per_step?.[step.id] ?? null
  const approvalRate = stepFeedback?.approval_rate ?? null
  const approvalColor =
    approvalRate === null
      ? ''
      : approvalRate > 75
        ? 'text-success bg-success/10 border-success/30'
        : approvalRate >= 50
          ? 'text-warning bg-warning/10 border-warning/30'
          : 'text-error bg-error/10 border-error/30'

  // Top edit reason for this step (from global top_edit_reasons as we don't have per-step reasons)
  const topEditReason = feedbackSummary?.top_edit_reasons?.[0]?.[0] ?? null

  // Config summary line
  const summaryParts: string[] = []
  if (config.tone) summaryParts.push(config.tone)
  if (config.language && config.language !== 'en') summaryParts.push(config.language)
  if (config.max_length) summaryParts.push(`${config.max_length} chars`)
  if (config.example_messages?.length) summaryParts.push(`${config.example_messages.length} example(s)`)

  return (
    <div className="border border-border rounded-lg bg-surface overflow-hidden">
      {/* Collapsed header */}
      <div
        className="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-surface-alt/50 transition-colors"
        onClick={onToggleExpand}
      >
        {/* Position badge */}
        <span className="w-6 h-6 flex items-center justify-center text-[10px] font-bold text-text-muted bg-surface-alt rounded-md flex-shrink-0">
          {step.position}
        </span>

        {/* Channel icon */}
        <span className="w-6 h-5 flex items-center justify-center text-[9px] font-bold text-text-muted bg-surface-alt rounded flex-shrink-0">
          {CHANNEL_ICONS[step.channel] || '?'}
        </span>

        {/* Label */}
        <span className="text-sm text-text flex-1 truncate">
          {step.label || channelLabel}
        </span>

        {/* Day offset */}
        <span className="text-xs text-text-dim flex-shrink-0">
          Day {step.day_offset}
        </span>

        {/* Config summary */}
        {summaryParts.length > 0 && (
          <span className="text-[10px] text-text-dim flex-shrink-0 hidden sm:inline">
            {summaryParts.join(' / ')}
          </span>
        )}

        {/* Approval rate badge */}
        {approvalRate !== null && (
          <span
            className={`text-[10px] font-medium px-1.5 py-0.5 rounded border flex-shrink-0 ${approvalColor}`}
            title={topEditReason ? `Top edit reason: ${topEditReason}` : `Approval rate: ${approvalRate}%`}
          >
            {approvalRate}%
          </span>
        )}

        {/* Reorder arrows */}
        {isEditable && (
          <div className="flex flex-col gap-0.5 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={onMoveUp}
              disabled={index === 0}
              className="w-5 h-3.5 flex items-center justify-center text-text-dim hover:text-text disabled:opacity-30 bg-transparent border-none cursor-pointer disabled:cursor-not-allowed p-0 transition-colors"
              title="Move up"
            >
              <svg width="10" height="6" viewBox="0 0 10 6" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M1 5l4-4 4 4" />
              </svg>
            </button>
            <button
              onClick={onMoveDown}
              disabled={index === total - 1}
              className="w-5 h-3.5 flex items-center justify-center text-text-dim hover:text-text disabled:opacity-30 bg-transparent border-none cursor-pointer disabled:cursor-not-allowed p-0 transition-colors"
              title="Move down"
            >
              <svg width="10" height="6" viewBox="0 0 10 6" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M1 1l4 4 4-4" />
              </svg>
            </button>
          </div>
        )}

        {/* Expand indicator */}
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className={`text-text-dim flex-shrink-0 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
        >
          <path d="M3 4.5l3 3 3-3" />
        </svg>
      </div>

      {/* Expanded config editor */}
      {isExpanded && (
        <div className="px-4 py-4 border-t border-border space-y-4">
          {/* Basic fields */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {/* Channel */}
            <div>
              <label className="text-xs text-text-muted mb-1 block">Channel</label>
              <select
                value={step.channel}
                onChange={(e) => {
                  const ch = e.target.value
                  onUpdateField('channel', ch)
                  // Reset max_length to channel default
                  const newConfig = { ...config, max_length: CHANNEL_MAX_LENGTH[ch] ?? 1900 }
                  onUpdateField('config', newConfig)
                }}
                disabled={!isEditable}
                className="w-full px-2 py-1.5 text-sm rounded border border-border bg-surface-alt text-text focus:outline-none focus:border-accent disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {CHANNEL_OPTIONS.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            </div>

            {/* Day offset */}
            <div>
              <label className="text-xs text-text-muted mb-1 block">Day Offset</label>
              <input
                type="number"
                min={0}
                value={step.day_offset}
                onChange={(e) => onUpdateField('day_offset', parseInt(e.target.value, 10) || 0)}
                disabled={!isEditable}
                className="w-full px-2 py-1.5 text-sm rounded border border-border bg-surface-alt text-text focus:outline-none focus:border-accent disabled:opacity-50 disabled:cursor-not-allowed"
              />
            </div>

            {/* Label */}
            <div>
              <label className="text-xs text-text-muted mb-1 block">Label</label>
              <input
                type="text"
                value={step.label}
                onChange={(e) => onUpdateField('label', e.target.value)}
                disabled={!isEditable}
                placeholder="e.g., Introduction"
                className="w-full px-2 py-1.5 text-sm rounded border border-border bg-surface-alt text-text focus:outline-none focus:border-accent disabled:opacity-50 disabled:cursor-not-allowed"
              />
            </div>
          </div>

          <SectionDivider title="Generation Config" />

          {/* Max length slider */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-text-muted">Max Length</label>
              <span className="text-sm font-medium text-text tabular-nums">{maxLength} chars</span>
            </div>
            <input
              type="range"
              min={50}
              max={CHANNEL_MAX_LENGTH[step.channel] ?? 5000}
              step={50}
              value={maxLength}
              onChange={(e) => {
                const newConfig = { ...config, max_length: parseInt(e.target.value, 10) }
                onUpdateField('config', newConfig)
              }}
              disabled={!isEditable}
              className="w-full accent-accent h-1.5 bg-surface-alt rounded-full cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            />
            <div className="flex justify-between text-[10px] text-text-dim mt-0.5">
              <span>50</span>
              <span>{CHANNEL_MAX_LENGTH[step.channel] ?? 5000}</span>
            </div>
          </div>

          {/* Tone and Language */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-text-muted mb-1 block">Tone</label>
              <select
                value={config.tone ?? 'professional'}
                onChange={(e) => {
                  const newConfig = { ...config, tone: e.target.value }
                  onUpdateField('config', newConfig)
                }}
                disabled={!isEditable}
                className="w-full px-2 py-1.5 text-sm rounded border border-border bg-surface-alt text-text focus:outline-none focus:border-accent disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {TONE_OPTIONS.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-text-muted mb-1 block">Language</label>
              <input
                type="text"
                value={config.language ?? 'en'}
                onChange={(e) => {
                  const newConfig = { ...config, language: e.target.value }
                  onUpdateField('config', newConfig)
                }}
                disabled={!isEditable}
                placeholder="en"
                className="w-full px-2 py-1.5 text-sm rounded border border-border bg-surface-alt text-text focus:outline-none focus:border-accent disabled:opacity-50 disabled:cursor-not-allowed"
              />
            </div>
          </div>

          {/* Custom instructions */}
          <div>
            <label className="text-xs text-text-muted mb-1 block">Custom Instructions</label>
            <textarea
              value={config.custom_instructions ?? ''}
              onChange={(e) => {
                const newConfig = { ...config, custom_instructions: e.target.value }
                onUpdateField('config', newConfig)
              }}
              disabled={!isEditable}
              rows={2}
              placeholder="e.g., Reference their recent Series A. Keep it under 3 sentences."
              className="w-full px-2 py-1.5 text-sm rounded border border-border bg-surface-alt text-text focus:outline-none focus:border-accent disabled:opacity-50 disabled:cursor-not-allowed resize-none"
            />
          </div>

          {/* Example messages */}
          <ExampleMessagesEditor
            examples={config.example_messages ?? []}
            isEditable={isEditable}
            onChange={(examples) => {
              const newConfig = { ...config, example_messages: examples }
              onUpdateField('config', newConfig)
            }}
          />

          {/* Assets */}
          <StepAssetsEditor
            config={config}
            campaignId={step.campaign_id}
            isEditable={isEditable}
            onUpdateConfig={(newConfig) => onUpdateField('config', newConfig)}
          />

          {/* Delete */}
          {isEditable && (
            <div className="flex justify-end pt-2 border-t border-border">
              <button
                onClick={onDelete}
                className="px-3 py-1.5 text-xs text-error hover:text-error/80 bg-transparent border border-error/20 hover:border-error/40 rounded cursor-pointer transition-colors"
              >
                Delete Step
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── ExampleMessagesEditor ────────────────────────────────

interface ExampleMessagesEditorProps {
  examples: ExampleMessage[]
  isEditable: boolean
  onChange: (examples: ExampleMessage[]) => void
}

function ExampleMessagesEditor({ examples, isEditable, onChange }: ExampleMessagesEditorProps) {
  const handleAdd = () => {
    onChange([...examples, { body: '', note: '' }])
  }

  const handleRemove = (index: number) => {
    onChange(examples.filter((_, i) => i !== index))
  }

  const handleChange = (index: number, field: 'body' | 'note', value: string) => {
    const updated = examples.map((ex, i) => (i === index ? { ...ex, [field]: value } : ex))
    onChange(updated)
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <label className="text-xs text-text-muted">Example Messages</label>
        {isEditable && (
          <button
            onClick={handleAdd}
            className="text-[10px] text-accent-cyan hover:text-accent-cyan/80 bg-transparent border-none cursor-pointer transition-colors"
          >
            + Add example
          </button>
        )}
      </div>
      {examples.length > 0 ? (
        <div className="space-y-3">
          {examples.map((ex, idx) => (
            <div key={idx} className="border border-border/50 rounded-md p-2.5 bg-surface-alt/30">
              <div className="flex items-start justify-between gap-2 mb-1.5">
                <span className="text-[10px] text-text-dim font-medium">Example {idx + 1}</span>
                {isEditable && (
                  <button
                    onClick={() => handleRemove(idx)}
                    className="text-[10px] text-error/60 hover:text-error bg-transparent border-none cursor-pointer transition-colors p-0"
                  >
                    Remove
                  </button>
                )}
              </div>
              <textarea
                value={ex.body}
                onChange={(e) => handleChange(idx, 'body', e.target.value)}
                disabled={!isEditable}
                rows={3}
                placeholder="Paste an example message..."
                className="w-full px-2 py-1.5 text-xs rounded border border-border bg-surface text-text focus:outline-none focus:border-accent disabled:opacity-50 disabled:cursor-not-allowed resize-none mb-1.5"
              />
              <input
                type="text"
                value={ex.note ?? ''}
                onChange={(e) => handleChange(idx, 'note', e.target.value)}
                disabled={!isEditable}
                placeholder="Note (e.g., good opening hook)"
                className="w-full px-2 py-1 text-[11px] rounded border border-border bg-surface text-text-muted focus:outline-none focus:border-accent disabled:opacity-50 disabled:cursor-not-allowed"
              />
            </div>
          ))}
        </div>
      ) : (
        <p className="text-[11px] text-text-dim">No examples yet. Add examples to guide the AI tone and style.</p>
      )}
    </div>
  )
}

// ── Helpers: file type labels & size formatting ──────────

function fileTypeLabel(contentType: string): string {
  if (contentType === 'application/pdf') return 'PDF'
  if (contentType.startsWith('image/')) return 'IMG'
  if (contentType.startsWith('text/')) return 'TXT'
  if (contentType.includes('spreadsheet') || contentType.includes('csv')) return 'CSV'
  if (contentType.includes('word') || contentType.includes('document')) return 'DOC'
  return 'FILE'
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ── StepAssetsEditor ─────────────────────────────────────

interface StepAssetsEditorProps {
  config: StepConfig
  campaignId: string
  isEditable: boolean
  onUpdateConfig: (config: StepConfig) => void
}

function StepAssetsEditor({ config, campaignId, isEditable, onUpdateConfig }: StepAssetsEditorProps) {
  const { toast } = useToast()
  const { data: assetsData } = useAssets()
  const uploadAsset = useUploadAsset()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [showPicker, setShowPicker] = useState(false)

  const attachedIds = config.asset_ids ?? []
  const assetMode = config.asset_mode ?? {}
  const allAssets = assetsData?.assets ?? []

  // Assets currently attached to this step
  const attachedAssets = allAssets.filter((a) => attachedIds.includes(a.id))

  // Assets available to add (tenant library minus already attached)
  const availableAssets = allAssets.filter((a) => !attachedIds.includes(a.id))

  const updateAssetConfig = (newIds: string[], newMode: Record<string, 'attach' | 'reference'>) => {
    onUpdateConfig({ ...config, asset_ids: newIds, asset_mode: newMode })
  }

  const handleUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const asset = await uploadAsset.mutateAsync({ file, campaignId })
      const newIds = [...attachedIds, asset.id]
      const newMode = { ...assetMode, [asset.id]: 'attach' as const }
      updateAssetConfig(newIds, newMode)
      toast(`Uploaded ${asset.filename}`, 'success')
    } catch {
      toast('Upload failed', 'error')
    }
    // Reset input so the same file can be re-selected
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [uploadAsset, campaignId, attachedIds, assetMode, toast, config, onUpdateConfig])

  const handleAddExisting = useCallback((asset: Asset) => {
    const newIds = [...attachedIds, asset.id]
    const newMode = { ...assetMode, [asset.id]: 'attach' as const }
    updateAssetConfig(newIds, newMode)
    setShowPicker(false)
  }, [attachedIds, assetMode, config, onUpdateConfig])

  const handleRemove = useCallback((assetId: string) => {
    const newIds = attachedIds.filter((id) => id !== assetId)
    const newMode = { ...assetMode }
    delete newMode[assetId]
    updateAssetConfig(newIds, newMode)
  }, [attachedIds, assetMode, config, onUpdateConfig])

  const handleToggleMode = useCallback((assetId: string) => {
    const current = assetMode[assetId] ?? 'attach'
    const next = current === 'attach' ? 'reference' : 'attach'
    const newMode: Record<string, 'attach' | 'reference'> = { ...assetMode, [assetId]: next }
    updateAssetConfig(attachedIds, newMode)
  }, [attachedIds, assetMode, config, onUpdateConfig])

  return (
    <div>
      <SectionDivider title="Assets" />
      <div className="flex items-center justify-between mb-2">
        <label className="text-xs text-text-muted">Attached Files</label>
        {isEditable && (
          <div className="flex items-center gap-2">
            {availableAssets.length > 0 && (
              <button
                onClick={() => setShowPicker((v) => !v)}
                className="text-[10px] text-accent-cyan hover:text-accent-cyan/80 bg-transparent border-none cursor-pointer transition-colors"
              >
                + Add existing
              </button>
            )}
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadAsset.isPending}
              className="text-[10px] text-accent-cyan hover:text-accent-cyan/80 bg-transparent border-none cursor-pointer transition-colors disabled:opacity-50"
            >
              {uploadAsset.isPending ? 'Uploading...' : '+ Upload file'}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              onChange={handleUpload}
              className="hidden"
            />
          </div>
        )}
      </div>

      {/* Existing asset picker dropdown */}
      {showPicker && availableAssets.length > 0 && (
        <div className="border border-border rounded-md bg-surface-alt/50 p-2 mb-3 max-h-40 overflow-y-auto">
          {availableAssets.map((asset) => (
            <button
              key={asset.id}
              onClick={() => handleAddExisting(asset)}
              className="w-full flex items-center gap-2 px-2 py-1.5 text-left text-xs text-text hover:bg-surface-alt rounded transition-colors bg-transparent border-none cursor-pointer"
            >
              <span className="text-[9px] font-bold text-text-dim bg-surface-alt px-1.5 py-0.5 rounded flex-shrink-0">
                {fileTypeLabel(asset.content_type)}
              </span>
              <span className="truncate flex-1">{asset.filename}</span>
              <span className="text-text-dim flex-shrink-0">{formatFileSize(asset.size_bytes)}</span>
            </button>
          ))}
        </div>
      )}

      {/* Attached assets list */}
      {attachedAssets.length > 0 ? (
        <div className="space-y-1.5">
          {attachedAssets.map((asset) => {
            const mode = assetMode[asset.id] ?? 'attach'
            return (
              <div key={asset.id} className="flex items-center gap-2 px-2.5 py-2 border border-border/50 rounded-md bg-surface-alt/30">
                {/* Type badge */}
                <span className="text-[9px] font-bold text-text-dim bg-surface-alt px-1.5 py-0.5 rounded flex-shrink-0">
                  {fileTypeLabel(asset.content_type)}
                </span>

                {/* Filename + size */}
                <span className="text-xs text-text truncate flex-1">{asset.filename}</span>
                <span className="text-[10px] text-text-dim flex-shrink-0">{formatFileSize(asset.size_bytes)}</span>

                {/* Mode toggle */}
                {isEditable && (
                  <button
                    onClick={() => handleToggleMode(asset.id)}
                    title={mode === 'attach' ? 'Attached to message' : 'Referenced only'}
                    className={`text-[10px] px-2 py-0.5 rounded border bg-transparent cursor-pointer transition-colors flex-shrink-0 ${
                      mode === 'attach'
                        ? 'border-accent/40 text-accent'
                        : 'border-border text-text-dim'
                    }`}
                  >
                    {mode === 'attach' ? 'Attach' : 'Reference'}
                  </button>
                )}

                {/* Remove */}
                {isEditable && (
                  <button
                    onClick={() => handleRemove(asset.id)}
                    className="text-[10px] text-error/60 hover:text-error bg-transparent border-none cursor-pointer transition-colors p-0 flex-shrink-0"
                    title="Remove from step"
                  >
                    &times;
                  </button>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <p className="text-[11px] text-text-dim">No files attached. Upload or add existing assets.</p>
      )}
    </div>
  )
}
