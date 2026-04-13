import { useState, useMemo } from 'react'
import { useCampaigns, useCreateCampaign } from '../../api/queries/useCampaigns'
import { useMutation } from '@tanstack/react-query'
import { apiFetch } from '../../api/client'
import { Modal } from './Modal'

/* ── Types ──────────────────────────────────────────────── */

interface ConflictItem {
  type: string
  contact_id: string
  contact_name: string
  detail: string
  severity: 'error' | 'warning' | 'info'
}

interface ConflictCheckResult {
  total_contacts: number
  clean: number
  with_warnings: number
  with_errors: number
  conflicts: ConflictItem[]
  message: string
}

interface AddToCampaignModalProps {
  selectedCount: number
  selectedIds: string[]
  onConfirm: (campaignId: string) => void
  onClose: () => void
  isLoading?: boolean
}

/* ── Hooks ──────────────────────────────────────────────── */

function useConflictCheck() {
  return useMutation({
    mutationFn: ({ campaignId, contactIds }: { campaignId: string; contactIds: string[] }) =>
      apiFetch<ConflictCheckResult>(`/campaigns/${campaignId}/conflict-check`, {
        method: 'POST',
        body: { contact_ids: contactIds },
      }),
  })
}

/* ── Component ──────────────────────────────────────────── */

export function AddToCampaignModal({
  selectedCount,
  selectedIds,
  onConfirm,
  onClose,
  isLoading,
}: AddToCampaignModalProps) {
  const { data: campaignsData } = useCampaigns()
  const createCampaign = useCreateCampaign()
  const conflictCheck = useConflictCheck()

  const [mode, setMode] = useState<'existing' | 'new'>('existing')
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(null)
  const [campaignSearch, setCampaignSearch] = useState('')
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [conflictResult, setConflictResult] = useState<ConflictCheckResult | null>(null)

  const campaigns = useMemo(() => {
    const all = campaignsData?.campaigns ?? []
    const s = (c: { status: string }) => c.status.toLowerCase()
    const assignable = all.filter((c) => s(c) === 'draft' || s(c) === 'ready')
    const q = campaignSearch.toLowerCase()
    if (!q) return assignable
    return assignable.filter((c) => c.name.toLowerCase().includes(q))
  }, [campaignsData, campaignSearch])

  const canSubmit = mode === 'existing'
    ? !!selectedCampaignId
    : newName.trim().length > 0

  const handleCheckConflicts = async () => {
    const targetId = mode === 'existing' ? selectedCampaignId : null
    if (!targetId) return
    const result = await conflictCheck.mutateAsync({
      campaignId: targetId,
      contactIds: selectedIds,
    })
    setConflictResult(result)
  }

  const handleSubmit = async () => {
    if (mode === 'new') {
      try {
        const result = await createCampaign.mutateAsync({
          name: newName.trim(),
          description: newDescription.trim() || undefined,
        })
        onConfirm(result.id)
      } catch {
        // Error handled by mutation
      }
    } else if (selectedCampaignId) {
      onConfirm(selectedCampaignId)
    }
  }

  const submitting = isLoading || createCampaign.isPending

  return (
    <Modal
      open
      onClose={onClose}
      title={`Add ${selectedCount} Contact${selectedCount !== 1 ? 's' : ''} to Campaign`}
      actions={
        <>
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-xs text-text-muted hover:text-text bg-transparent border border-border-solid rounded-lg cursor-pointer transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit || submitting}
            className="px-4 py-1.5 text-xs font-medium rounded-lg bg-accent text-white border-none cursor-pointer hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? 'Adding...' : 'Add to Campaign'}
          </button>
        </>
      }
    >
      {/* Mode selector */}
      <div className="flex gap-2 mb-4">
        <button
          type="button"
          onClick={() => { setMode('existing'); setConflictResult(null) }}
          className={`flex-1 py-2 text-xs font-medium rounded-lg border cursor-pointer transition-colors ${
            mode === 'existing'
              ? 'bg-accent/10 border-accent text-accent'
              : 'bg-transparent border-border-solid text-text-muted hover:text-text'
          }`}
        >
          Existing Campaign
        </button>
        <button
          type="button"
          onClick={() => { setMode('new'); setSelectedCampaignId(null); setConflictResult(null) }}
          className={`flex-1 py-2 text-xs font-medium rounded-lg border cursor-pointer transition-colors ${
            mode === 'new'
              ? 'bg-accent/10 border-accent text-accent'
              : 'bg-transparent border-border-solid text-text-muted hover:text-text'
          }`}
        >
          New Campaign
        </button>
      </div>

      {mode === 'existing' ? (
        <>
          {/* Campaign search */}
          <input
            type="text"
            value={campaignSearch}
            onChange={(e) => setCampaignSearch(e.target.value)}
            placeholder="Search campaigns..."
            className="w-full px-3 py-1.5 mb-2 text-xs bg-surface-alt border border-border-solid rounded-md text-text placeholder:text-text-dim outline-none focus:border-accent"
          />

          {/* Campaign list */}
          <div className="max-h-[200px] overflow-auto mb-3">
            {campaigns.map((c) => (
              <label
                key={c.id}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
                  selectedCampaignId === c.id ? 'bg-accent/10' : 'hover:bg-surface-alt'
                }`}
              >
                <input
                  type="radio"
                  name="campaign"
                  checked={selectedCampaignId === c.id}
                  onChange={() => { setSelectedCampaignId(c.id); setConflictResult(null) }}
                  className="w-4 h-4 accent-accent cursor-pointer"
                />
                <div className="flex-1 min-w-0">
                  <span className="text-sm text-text block truncate">{c.name}</span>
                  <span className="text-[11px] text-text-muted">
                    {c.status} &middot; {c.total_contacts} contacts
                  </span>
                </div>
              </label>
            ))}
            {campaigns.length === 0 && (
              <p className="text-xs text-text-dim text-center py-4">
                {campaignSearch ? 'No campaigns match your search.' : 'No draft/ready campaigns available.'}
              </p>
            )}
          </div>
        </>
      ) : (
        /* New campaign form */
        <div className="space-y-3 mb-3">
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">Campaign Name</label>
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="e.g., DACH Manufacturing Q1"
              className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text placeholder:text-text-dim outline-none focus:border-accent"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">Description (optional)</label>
            <input
              type="text"
              value={newDescription}
              onChange={(e) => setNewDescription(e.target.value)}
              placeholder="Campaign objective..."
              className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text placeholder:text-text-dim outline-none focus:border-accent"
            />
          </div>
        </div>
      )}

      {/* Enrichment readiness preview */}
      <EnrichmentPreview count={selectedCount} />

      {/* Conflict check section */}
      {mode === 'existing' && selectedCampaignId && (
        <div className="mt-3 pt-3 border-t border-border-solid">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-text-muted">Conflict Check</span>
            <button
              type="button"
              onClick={handleCheckConflicts}
              disabled={conflictCheck.isPending}
              className="text-[11px] px-2 py-1 rounded bg-surface-alt border border-border-solid text-text-muted hover:text-text hover:border-accent cursor-pointer transition-colors disabled:opacity-50"
            >
              {conflictCheck.isPending ? (
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 border-2 border-border border-t-accent rounded-full animate-spin" />
                  Checking...
                </span>
              ) : (
                'Check for Conflicts'
              )}
            </button>
          </div>

          {conflictResult && <ConflictResults result={conflictResult} />}
        </div>
      )}

      {/* Errors */}
      {createCampaign.isError && (
        <p className="text-xs text-error mt-2">
          {createCampaign.error?.message ?? 'Failed to create campaign'}
        </p>
      )}
    </Modal>
  )
}

/* ── Enrichment preview ─────────────────────────────────── */

function EnrichmentPreview({ count }: { count: number }) {
  return (
    <div className="bg-surface-alt rounded-lg px-3 py-2">
      <div className="flex items-center gap-2 text-xs text-text-muted">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="7" cy="7" r="5.5" />
          <path d="M7 4v3l2 1" />
        </svg>
        <span>
          {count} contact{count !== 1 ? 's' : ''} selected
        </span>
      </div>
    </div>
  )
}

/* ── Conflict results display ───────────────────────────── */

function ConflictResults({ result }: { result: ConflictCheckResult }) {
  const [expanded, setExpanded] = useState(false)

  const hasIssues = result.with_warnings > 0 || result.with_errors > 0

  return (
    <div className="space-y-1.5">
      {/* Summary */}
      <div className={`flex items-center gap-2 text-xs px-2 py-1.5 rounded ${
        result.with_errors > 0 ? 'bg-error/10 text-error' :
        result.with_warnings > 0 ? 'bg-warning/10 text-warning' :
        'bg-success/10 text-success'
      }`}>
        {result.with_errors > 0 ? (
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="7" cy="7" r="5.5" /><path d="M7 4v3M7 9v.5" />
          </svg>
        ) : result.with_warnings > 0 ? (
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M7 2L1 12h12L7 2z" /><path d="M7 6v2.5M7 10v.5" />
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="7" cy="7" r="5.5" /><path d="M4.5 7l2 2 3-4" />
          </svg>
        )}
        <span>{result.message}</span>
      </div>

      {/* Detail toggle */}
      {hasIssues && result.conflicts.length > 0 && (
        <>
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="text-[11px] text-text-muted hover:text-text bg-transparent border-none cursor-pointer p-0 transition-colors"
          >
            {expanded ? 'Hide details' : `Show ${result.conflicts.length} issue${result.conflicts.length !== 1 ? 's' : ''}`}
          </button>
          {expanded && (
            <div className="max-h-[150px] overflow-auto space-y-1">
              {result.conflicts.map((c, i) => (
                <div key={i} className="flex items-start gap-2 text-[11px] px-2 py-1 rounded bg-surface-alt">
                  <span className={`flex-shrink-0 mt-0.5 w-1.5 h-1.5 rounded-full ${
                    c.severity === 'error' ? 'bg-error' : c.severity === 'warning' ? 'bg-warning' : 'bg-accent-cyan'
                  }`} />
                  <div className="min-w-0">
                    <span className="text-text font-medium">{c.contact_name}</span>
                    <span className="text-text-dim ml-1">{c.detail}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
