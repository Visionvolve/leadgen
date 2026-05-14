import { useMemo, useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { FilterBar, type FilterConfig } from '../../../components/ui/FilterBar'
import { useMessages, useBatchUpdateMessages, type Message, type MessageFilters } from '../../../api/queries/useMessages'
import { apiDownload } from '../../../api/client'
import { useToast } from '../../../components/ui/Toast'
import { EmptyState } from '../../../components/ui/EmptyState'
import { ConfirmDialog } from '../../../components/ui/ConfirmDialog'
import { ContactGroup } from '../../messages/ContactGroup'
import { CampaignMessagesGrid } from '../../../components/campaign/CampaignMessagesGrid'
import { MessageReviewQueue } from '../../../components/campaign/MessageReviewQueue'
import { PreviewModal } from '../../../components/campaign/PreviewModal'
import { REVIEW_STATUS_DISPLAY, filterOptions } from '../../../lib/display'

interface ContactMessages {
  contactId: string
  contactName: string
  contactTitle: string | null
  contactScore: number | null
  contactIcp: string | null
  linkedinUrl: string | null
  companyId: string | null
  companyName: string | null
  companyTier: string | null
  messages: Message[]
}

const CHANNEL_OPTIONS = [
  { value: 'linkedin_connect', label: 'LI Connect' },
  { value: 'linkedin_message', label: 'LI Message' },
  { value: 'email', label: 'Email' },
  { value: 'call_script', label: 'Call Script' },
]

type ViewMode = 'grid' | 'grouped'

const VIEW_STORAGE_KEY = 'campaign-messages-view'

interface Props {
  campaignId: string
  onNavigate: (type: 'company' | 'contact', id: string) => void
}

export function MessagesTab({ campaignId, onNavigate }: Props) {
  const { toast } = useToast()
  const navigate = useNavigate()

  // Review queue overlay state
  const [showReviewQueue, setShowReviewQueue] = useState(false)
  const [showBulkApproveConfirm, setShowBulkApproveConfirm] = useState(false)

  // Preview modal state
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewContactId, setPreviewContactId] = useState<string | null>(null)

  const openBulkPreview = useCallback(() => {
    setPreviewContactId(null)
    setPreviewOpen(true)
  }, [])

  const openContactPreview = useCallback((contactId: string | null) => {
    setPreviewContactId(contactId)
    setPreviewOpen(true)
  }, [])

  // Persist view preference in localStorage
  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    try {
      const stored = localStorage.getItem(VIEW_STORAGE_KEY)
      if (stored === 'grid' || stored === 'grouped') return stored
    } catch { /* ignore */ }
    return 'grouped'
  })

  const handleViewChange = useCallback((mode: ViewMode) => {
    setViewMode(mode)
    try { localStorage.setItem(VIEW_STORAGE_KEY, mode) } catch { /* ignore */ }
  }, [])

  const [status, setStatus] = useState('draft')
  const [channel, setChannel] = useState('')

  const filters: MessageFilters = useMemo(() => ({
    campaign_id: campaignId,
    status: status || undefined,
    channel: channel || undefined,
  }), [campaignId, status, channel])

  const { data, isLoading, refetch, isRefetching } = useMessages(filters)
  const batchMutation = useBatchUpdateMessages()

  // Auto-load on mount
  useEffect(() => { refetch() }, [refetch])

  // Group messages by contact (for grouped view)
  const groups: ContactMessages[] = useMemo(() => {
    if (!data?.messages) return []
    const map = new Map<string, ContactMessages>()
    for (const m of data.messages) {
      const cid = m.contact.id ?? 'unknown'
      let group = map.get(cid)
      if (!group) {
        group = {
          contactId: cid,
          contactName: m.contact.full_name || 'Unknown',
          contactTitle: m.contact.job_title,
          contactScore: m.contact.contact_score,
          contactIcp: m.contact.icp_fit,
          linkedinUrl: m.contact.linkedin_url,
          companyId: m.company?.id ?? null,
          companyName: m.company?.name ?? null,
          companyTier: m.company?.tier ?? null,
          messages: [],
        }
        map.set(cid, group)
      }
      group.messages.push(m)
    }
    return Array.from(map.values()).sort(
      (a, b) => (b.contactScore ?? 0) - (a.contactScore ?? 0)
    )
  }, [data])

  const totalMessages = data?.messages.length ?? 0
  const totalContacts = groups.length
  const draftCount = data?.messages.filter((m) => m.status === 'draft').length ?? 0

  // Bulk approve all visible draft A variants
  const allDraftAIds = useMemo(
    () => (data?.messages ?? [])
      .filter((m) => m.status === 'draft' && m.variant === 'A')
      .map((m) => m.id),
    [data],
  )

  const handleBulkApprove = useCallback(() => {
    if (allDraftAIds.length === 0) {
      toast('No draft A variants to approve', 'info')
      return
    }
    setShowBulkApproveConfirm(true)
  }, [allDraftAIds, toast])

  const executeBulkApprove = useCallback(async () => {
    setShowBulkApproveConfirm(false)
    try {
      await batchMutation.mutateAsync({
        ids: allDraftAIds,
        fields: { status: 'approved', approved_at: new Date().toISOString() },
      })
      toast(`${allDraftAIds.length} messages approved`, 'success')
    } catch {
      toast('Bulk approve failed', 'error')
    }
  }, [allDraftAIds, batchMutation, toast])

  const handleFilterChange = useCallback((key: string, value: string) => {
    switch (key) {
      case 'status': setStatus(value); break
      case 'channel': setChannel(value); break
    }
  }, [])

  const [isExporting, setIsExporting] = useState(false)
  const handleExportCsv = useCallback(async () => {
    setIsExporting(true)
    try {
      await apiDownload(`/campaigns/${campaignId}/messages/export-csv`, { status: 'approved' })
      toast('CSV exported', 'success')
    } catch {
      toast('Export failed', 'error')
    } finally {
      setIsExporting(false)
    }
  }, [campaignId, toast])

  const filterConfigs: FilterConfig[] = useMemo(() => [
    { key: 'status', label: 'Status', type: 'select' as const, options: filterOptions(REVIEW_STATUS_DISPLAY) },
    { key: 'channel', label: 'Channel', type: 'select' as const, options: CHANNEL_OPTIONS },
  ], [])

  // ---- Grid view ----
  if (viewMode === 'grid') {
    return (
      <div className="flex flex-col min-h-0 -mx-6 -mt-5">
        {/* View toggle + action buttons */}
        <div className="flex items-center gap-2 mb-3 px-6 pt-1">
          <ViewToggle mode={viewMode} onChange={handleViewChange} />
          <div className="flex items-center gap-2 ml-auto">
            <button
              data-testid="messages-preview-button"
              onClick={openBulkPreview}
              className="px-3 py-1.5 text-xs bg-surface border border-border text-text rounded-md hover:bg-surface-alt transition-colors"
              title="Preview a rendered message for any contact in this campaign"
            >
              Preview
            </button>
            {draftCount > 0 && (
              <>
                <button
                  onClick={() => setShowReviewQueue(true)}
                  className="px-3 py-1.5 text-xs bg-accent hover:bg-accent-hover text-white rounded-md transition-colors font-medium"
                >
                  Review Queue ({draftCount})
                </button>
                <button
                  onClick={() => navigate(`review?status=draft`)}
                  className="px-3 py-1.5 text-xs bg-surface border border-border text-text rounded-md hover:bg-surface-alt transition-colors font-medium"
                >
                  Review Page
                </button>
              </>
            )}
            <button
              onClick={handleExportCsv}
              disabled={isExporting || totalMessages === 0}
              className="px-3 py-1.5 text-xs bg-surface border border-border text-text rounded-md hover:bg-surface-alt disabled:opacity-50 transition-colors"
              title="Export approved messages as CSV"
            >
              {isExporting ? 'Exporting...' : 'Export CSV'}
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0 px-6 pb-4">
          <CampaignMessagesGrid campaignId={campaignId} onNavigate={onNavigate} />
        </div>

        {showReviewQueue && (
          <MessageReviewQueue
            campaignId={campaignId}
            initialFilter="draft"
            onClose={() => setShowReviewQueue(false)}
          />
        )}

        <PreviewModal
          open={previewOpen}
          onClose={() => setPreviewOpen(false)}
          campaignId={campaignId}
          initialContactId={previewContactId}
        />
      </div>
    )
  }

  // ---- Grouped view (original) ----
  return (
    <div className="flex flex-col min-h-0 -mx-6 -mt-5">
      <FilterBar
        filters={filterConfigs}
        values={{ status, channel }}
        onChange={handleFilterChange}
        action={
          <div className="flex items-center gap-2 ml-auto">
            <ViewToggle mode={viewMode} onChange={handleViewChange} />
            <button
              data-testid="messages-preview-button"
              onClick={openBulkPreview}
              className="px-3 py-1.5 text-xs bg-surface border border-border text-text rounded-md hover:bg-surface-alt transition-colors"
              title="Preview a rendered message for any contact in this campaign"
            >
              Preview
            </button>
            {draftCount > 0 && (
              <>
                <button
                  onClick={() => setShowReviewQueue(true)}
                  className="px-3 py-1.5 text-xs bg-accent hover:bg-accent-hover text-white rounded-md transition-colors font-medium"
                >
                  Review Queue ({draftCount})
                </button>
                <button
                  onClick={() => navigate(`review?status=draft`)}
                  className="px-3 py-1.5 text-xs bg-surface border border-border text-text rounded-md hover:bg-surface-alt transition-colors font-medium"
                >
                  Review Page
                </button>
              </>
            )}
            <button
              onClick={() => refetch()}
              disabled={isLoading || isRefetching}
              className="px-3 py-1.5 text-xs bg-surface border border-border text-text rounded-md hover:bg-surface-alt disabled:opacity-50 transition-colors"
            >
              {isLoading || isRefetching ? 'Loading...' : 'Refresh'}
            </button>
            {allDraftAIds.length > 0 && (
              <button
                onClick={handleBulkApprove}
                disabled={batchMutation.isPending}
                className="px-3 py-1.5 text-xs bg-success/10 text-success border border-success/30 rounded-md hover:bg-success/20 transition-colors disabled:opacity-50"
              >
                Approve All A ({allDraftAIds.length})
              </button>
            )}
            <button
              onClick={handleExportCsv}
              disabled={isExporting || totalMessages === 0}
              className="px-3 py-1.5 text-xs bg-surface border border-border text-text rounded-md hover:bg-surface-alt disabled:opacity-50 transition-colors"
              title="Export approved messages as CSV"
            >
              {isExporting ? 'Exporting...' : 'Export CSV'}
            </button>
          </div>
        }
      />

      {totalMessages > 0 && (
        <div className="flex items-center gap-4 text-xs text-text-muted mb-3 px-6 pt-1">
          <span>{totalContacts} contact{totalContacts !== 1 ? 's' : ''}</span>
          <span>{totalMessages} message{totalMessages !== 1 ? 's' : ''}</span>
          <span>{draftCount} draft{draftCount !== 1 ? 's' : ''}</span>
        </div>
      )}

      <div className="flex-1 overflow-y-auto space-y-4 min-h-0 px-6 pb-4">
        {isLoading && !data ? (
          <div className="flex items-center justify-center py-12">
            <div className="w-8 h-8 border-2 border-border border-t-accent rounded-full animate-spin" />
          </div>
        ) : groups.length === 0 ? (
          <EmptyState
            icon={
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            }
            title="No messages yet"
            description={status || channel ? 'No messages match your filters. Try adjusting your filters.' : 'Generate messages from the Message Gen tab to get started.'}
          />
        ) : (
          groups.map((g) => (
            <ContactGroup
              key={g.contactId}
              contactName={g.contactName}
              contactTitle={g.contactTitle}
              contactScore={g.contactScore}
              contactIcp={g.contactIcp}
              linkedinUrl={g.linkedinUrl}
              companyName={g.companyName}
              companyTier={g.companyTier}
              messages={g.messages}
              onContactClick={g.contactId !== 'unknown' ? () => onNavigate('contact', g.contactId) : undefined}
              onCompanyClick={g.companyId ? () => onNavigate('company', g.companyId!) : undefined}
              onPreview={g.contactId !== 'unknown' ? () => openContactPreview(g.contactId) : undefined}
              campaignId={campaignId}
              onRequestSendTest={g.contactId !== 'unknown' ? () => openContactPreview(g.contactId) : undefined}
            />
          ))
        )}
      </div>

      {showReviewQueue && (
        <MessageReviewQueue
          campaignId={campaignId}
          initialFilter="draft"
          onClose={() => setShowReviewQueue(false)}
        />
      )}

      <ConfirmDialog
        open={showBulkApproveConfirm}
        title="Bulk approve messages"
        message={`Approve ${allDraftAIds.length} variant A message(s)? This will mark them as ready for outreach.`}
        confirmLabel="Approve All"
        onConfirm={executeBulkApprove}
        onCancel={() => setShowBulkApproveConfirm(false)}
      />

      <PreviewModal
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        campaignId={campaignId}
        initialContactId={previewContactId}
      />
    </div>
  )
}

// ── View toggle component ──────────────────────────────

function ViewToggle({ mode, onChange }: { mode: ViewMode; onChange: (m: ViewMode) => void }) {
  return (
    <div className="flex items-center border border-border-solid rounded-md overflow-hidden">
      <button
        onClick={() => onChange('grid')}
        className={`p-1.5 transition-colors border-none cursor-pointer ${
          mode === 'grid'
            ? 'bg-accent/15 text-accent-hover'
            : 'bg-surface-alt text-text-muted hover:text-text'
        }`}
        title="Grid view"
        aria-label="Grid view"
        aria-pressed={mode === 'grid'}
      >
        {/* Table/grid icon */}
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M2 4h12M2 8h12M2 12h12" />
          <path d="M6 2v12" />
        </svg>
      </button>
      <button
        onClick={() => onChange('grouped')}
        className={`p-1.5 transition-colors border-none cursor-pointer ${
          mode === 'grouped'
            ? 'bg-accent/15 text-accent-hover'
            : 'bg-surface-alt text-text-muted hover:text-text'
        }`}
        title="Grouped view"
        aria-label="Grouped view"
        aria-pressed={mode === 'grouped'}
      >
        {/* Card/grouped icon */}
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="2" y="2" width="5" height="5" rx="1" />
          <rect x="9" y="2" width="5" height="5" rx="1" />
          <rect x="2" y="9" width="5" height="5" rx="1" />
          <rect x="9" y="9" width="5" height="5" rx="1" />
        </svg>
      </button>
    </div>
  )
}
