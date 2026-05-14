import { useState, useMemo, useCallback, useEffect } from 'react'
import { FilterBar, type FilterConfig } from '../ui/FilterBar'
import { SelectionActionBar } from '../ui/SelectionActionBar'
import { useCampaignMessages, useBatchAction, type Message } from '../../api/queries/useCampaignMessages'
import { useBatchUpdateMessages } from '../../api/queries/useMessages'
import { useToast } from '../ui/Toast'
import { REVIEW_STATUS_DISPLAY, filterOptions } from '../../lib/display'
import { MessageBodyView } from './MessageBodyView'

// ── Constants ──────────────────────────────────────────

const CHANNEL_OPTIONS = [
  { value: 'linkedin_connect', label: 'LI Connect' },
  { value: 'linkedin_message', label: 'LI Message' },
  { value: 'email', label: 'Email' },
  { value: 'call_script', label: 'Call Script' },
]

const STEP_OPTIONS = [
  { value: '1', label: 'Step 1' },
  { value: '2', label: 'Step 2' },
  { value: '3', label: 'Step 3' },
]

const CHANNEL_LABELS: Record<string, string> = {
  email: 'Email',
  linkedin_connect: 'LinkedIn',
  linkedin_message: 'LinkedIn',
  call_script: 'Call',
}

const CHANNEL_BADGE_COLORS: Record<string, string> = {
  email: 'bg-[#00B8CF]/15 text-[#00B8CF] border-[#00B8CF]/30',
  linkedin_connect: 'bg-accent/15 text-accent-hover border-accent/30',
  linkedin_message: 'bg-accent/15 text-accent-hover border-accent/30',
  call_script: 'bg-warning/15 text-warning border-warning/30',
}

const STATUS_BADGE_COLORS: Record<string, string> = {
  draft: 'bg-[#8B92A0]/10 text-text-muted border-[#8B92A0]/20',
  approved: 'bg-success/15 text-success border-success/30',
  rejected: 'bg-error/15 text-error border-error/30',
  sent: 'bg-[#00B8CF]/15 text-[#00B8CF] border-[#00B8CF]/30',
  delivered: 'bg-[#2ecc71]/15 text-[#2ecc71] border-[#2ecc71]/30',
  replied: 'bg-[#2ecc71]/15 text-[#2ecc71] border-[#2ecc71]/30',
}

type SortField = 'contact' | 'channel' | 'step' | 'status' | 'score'
type SortDir = 'asc' | 'desc'

// ── Props ──────────────────────────────────────────────

interface Props {
  campaignId: string
  onNavigate: (type: 'company' | 'contact', id: string) => void
}

// ── Component ──────────────────────────────────────────

export function CampaignMessagesGrid({ campaignId, onNavigate }: Props) {
  const { toast } = useToast()

  // Filter state
  const [status, setStatus] = useState('')
  const [channel, setChannel] = useState('')
  const [step, setStep] = useState('')
  const [search, setSearch] = useState('')

  // Sort state
  const [sortField, setSortField] = useState<SortField>('contact')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  // Selection state
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  // Expanded row
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Queries
  const { data, isLoading, isRefetching } = useCampaignMessages(campaignId, {
    status: status || undefined,
    channel: channel || undefined,
  })

  const batchAction = useBatchAction()
  const batchUpdate = useBatchUpdateMessages()

  // Client-side filtering (step + search are applied locally since the API
  // may not support all filter combinations)
  const filteredMessages = useMemo(() => {
    if (!data?.messages) return []
    let msgs = data.messages

    if (step) {
      const stepNum = parseInt(step, 10)
      msgs = msgs.filter((m) => m.sequence_step === stepNum)
    }

    if (search) {
      const q = search.toLowerCase()
      msgs = msgs.filter((m) =>
        m.contact.full_name.toLowerCase().includes(q) ||
        m.body.toLowerCase().includes(q) ||
        (m.subject && m.subject.toLowerCase().includes(q)),
      )
    }

    return msgs
  }, [data, step, search])

  // Sorted messages
  const sortedMessages = useMemo(() => {
    const sorted = [...filteredMessages]
    sorted.sort((a, b) => {
      let cmp = 0
      switch (sortField) {
        case 'contact':
          cmp = (a.contact.full_name || '').localeCompare(b.contact.full_name || '')
          break
        case 'channel':
          cmp = a.channel.localeCompare(b.channel)
          break
        case 'step':
          cmp = a.sequence_step - b.sequence_step
          break
        case 'status':
          cmp = a.status.localeCompare(b.status)
          break
        case 'score':
          cmp = (a.contact.contact_score ?? 0) - (b.contact.contact_score ?? 0)
          break
      }
      return sortDir === 'desc' ? -cmp : cmp
    })
    return sorted
  }, [filteredMessages, sortField, sortDir])

  // Handle sort click
  const handleSort = useCallback((field: SortField) => {
    if (field === sortField) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortDir('asc')
    }
  }, [sortField])

  // Filter change handler
  const handleFilterChange = useCallback((key: string, value: string) => {
    // Clear selection when filters change
    setSelectedIds(new Set())
    switch (key) {
      case 'status': setStatus(value); break
      case 'channel': setChannel(value); break
      case 'step': setStep(value); break
      case 'search': setSearch(value); break
    }
  }, [])

  // Selection: toggle single
  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }, [])

  // Selection: toggle all visible
  const toggleSelectAll = useCallback(() => {
    setSelectedIds((prev) => {
      const allVisible = sortedMessages.map((m) => m.id)
      const allSelected = allVisible.every((id) => prev.has(id))
      if (allSelected) {
        return new Set()
      }
      return new Set(allVisible)
    })
  }, [sortedMessages])

  // Cmd/Ctrl+A to select all visible
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'a') {
        // Only intercept if we're not in an input
        const tag = (e.target as HTMLElement)?.tagName
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
        e.preventDefault()
        const allVisible = sortedMessages.map((m) => m.id)
        setSelectedIds(new Set(allVisible))
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [sortedMessages])

  // Inline approve single message
  const handleApprove = useCallback(async (msg: Message) => {
    try {
      await batchUpdate.mutateAsync({
        ids: [msg.id],
        fields: { status: 'approved', approved_at: new Date().toISOString() },
      })
      toast('Message approved', 'success')
    } catch {
      toast('Failed to approve message', 'error')
    }
  }, [batchUpdate, toast])

  // Inline reject single message
  const handleReject = useCallback(async (msg: Message) => {
    try {
      await batchUpdate.mutateAsync({
        ids: [msg.id],
        fields: { status: 'rejected' },
      })
      toast('Message rejected', 'success')
    } catch {
      toast('Failed to reject message', 'error')
    }
  }, [batchUpdate, toast])

  // Bulk approve
  const handleBulkApprove = useCallback(async () => {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) return
    try {
      await batchAction.mutateAsync({
        campaignId,
        messageIds: ids,
        action: 'approve',
      })
      toast(`${ids.length} message(s) approved`, 'success')
      setSelectedIds(new Set())
    } catch {
      toast('Bulk approve failed', 'error')
    }
  }, [selectedIds, campaignId, batchAction, toast])

  // Bulk reject
  const handleBulkReject = useCallback(async () => {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) return
    try {
      await batchAction.mutateAsync({
        campaignId,
        messageIds: ids,
        action: 'reject',
      })
      toast(`${ids.length} message(s) rejected`, 'success')
      setSelectedIds(new Set())
    } catch {
      toast('Bulk reject failed', 'error')
    }
  }, [selectedIds, campaignId, batchAction, toast])

  // Filter bar config
  const filterConfigs: FilterConfig[] = useMemo(() => [
    { key: 'status', label: 'Status', type: 'select' as const, options: filterOptions(REVIEW_STATUS_DISPLAY) },
    { key: 'channel', label: 'Channel', type: 'select' as const, options: CHANNEL_OPTIONS },
    { key: 'step', label: 'Step', type: 'select' as const, options: STEP_OPTIONS },
    { key: 'search', label: 'Messages', type: 'search' as const, placeholder: 'Search contact or body...' },
  ], [])

  // Header checkbox state
  const allVisibleSelected = sortedMessages.length > 0 &&
    sortedMessages.every((m) => selectedIds.has(m.id))
  const someSelected = selectedIds.size > 0

  // Sort indicator (inline helper, not a component)
  const sortIcon = (field: SortField) => {
    if (sortField !== field) return null
    return (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" className={sortDir === 'desc' ? 'rotate-180' : ''}>
        <path d="M6 3l3 4H3z" />
      </svg>
    )
  }

  // Loading state
  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="w-8 h-8 border-2 border-border border-t-accent rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="flex flex-col min-h-0">
      {/* Filter bar */}
      <FilterBar
        filters={filterConfigs}
        values={{ status, channel, step, search }}
        onChange={handleFilterChange}
        total={sortedMessages.length}
      />

      {/* Summary stats */}
      {data?.messages && (
        <div className="flex items-center gap-4 text-xs text-text-muted mb-3">
          <span>{sortedMessages.length} message{sortedMessages.length !== 1 ? 's' : ''}</span>
          <span>{sortedMessages.filter((m) => m.status === 'draft').length} draft</span>
          <span>{sortedMessages.filter((m) => m.status === 'approved').length} approved</span>
          <span>{sortedMessages.filter((m) => m.status === 'rejected').length} rejected</span>
        </div>
      )}

      {/* Table */}
      <div className="flex-1 min-h-0 overflow-auto border border-border-solid rounded-lg bg-surface">
        <table className="w-full text-sm border-collapse" style={{ minWidth: 800 }}>
          <thead className="sticky top-0 z-10 bg-surface-alt">
            <tr>
              {/* Checkbox header */}
              <th className="w-10 px-2 py-2.5 border-b border-border-solid text-center">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  ref={(el) => {
                    if (el) el.indeterminate = someSelected && !allVisibleSelected
                  }}
                  onChange={toggleSelectAll}
                  aria-label="Select all"
                  className="cursor-pointer w-4 h-4 accent-accent"
                />
              </th>
              {/* Contact */}
              <th
                onClick={() => handleSort('contact')}
                className="text-left text-xs font-medium text-text-muted px-3 py-2.5 border-b border-border-solid whitespace-nowrap cursor-pointer hover:text-text select-none"
                style={{ minWidth: '160px' }}
              >
                <span className="flex items-center gap-1">Contact {sortIcon('contact')}</span>
              </th>
              {/* Channel */}
              <th
                onClick={() => handleSort('channel')}
                className="text-left text-xs font-medium text-text-muted px-3 py-2.5 border-b border-border-solid whitespace-nowrap cursor-pointer hover:text-text select-none"
                style={{ width: '100px' }}
              >
                <span className="flex items-center gap-1">Channel {sortIcon('channel')}</span>
              </th>
              {/* Step */}
              <th
                onClick={() => handleSort('step')}
                className="text-left text-xs font-medium text-text-muted px-3 py-2.5 border-b border-border-solid whitespace-nowrap cursor-pointer hover:text-text select-none"
                style={{ width: '60px' }}
              >
                <span className="flex items-center gap-1">Step {sortIcon('step')}</span>
              </th>
              {/* Status */}
              <th
                onClick={() => handleSort('status')}
                className="text-left text-xs font-medium text-text-muted px-3 py-2.5 border-b border-border-solid whitespace-nowrap cursor-pointer hover:text-text select-none"
                style={{ width: '100px' }}
              >
                <span className="flex items-center gap-1">Status {sortIcon('status')}</span>
              </th>
              {/* Body preview */}
              <th className="text-left text-xs font-medium text-text-muted px-3 py-2.5 border-b border-border-solid whitespace-nowrap">
                Body
              </th>
              {/* Actions */}
              <th className="text-right text-xs font-medium text-text-muted px-3 py-2.5 border-b border-border-solid whitespace-nowrap" style={{ width: '100px' }}>
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedMessages.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-12 text-center text-text-dim text-sm">
                  {isLoading || isRefetching ? 'Loading...' : 'No messages match your filters.'}
                </td>
              </tr>
            ) : (
              sortedMessages.map((msg) => {
                const isSelected = selectedIds.has(msg.id)
                const isExpanded = expandedId === msg.id
                const isDraft = msg.status === 'draft'
                const channelLabel = CHANNEL_LABELS[msg.channel] ?? msg.channel
                const channelColors = CHANNEL_BADGE_COLORS[msg.channel] ?? CHANNEL_BADGE_COLORS.email
                const statusColors = STATUS_BADGE_COLORS[msg.status] ?? STATUS_BADGE_COLORS.draft
                const statusLabel = msg.status.charAt(0).toUpperCase() + msg.status.slice(1)

                return (
                  <tr
                    key={msg.id}
                    className={`border-b border-border/30 ${isSelected ? 'bg-accent/5' : ''} hover:bg-surface-alt/30 cursor-pointer`}
                  >
                    {/* Checkbox */}
                    <td className="w-10 px-2 py-2.5 text-center">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={(e) => {
                          e.stopPropagation()
                          toggleSelect(msg.id)
                        }}
                        onClick={(e) => e.stopPropagation()}
                        aria-label={`Select message for ${msg.contact.full_name}`}
                        className="cursor-pointer w-4 h-4 accent-accent"
                      />
                    </td>

                    {/* Contact */}
                    <td
                      className="px-3 py-2.5"
                      onClick={() => setExpandedId(isExpanded ? null : msg.id)}
                    >
                      <div className="flex flex-col min-w-0">
                        <button
                          className="text-sm text-text hover:text-accent-cyan transition-colors truncate text-left bg-transparent border-none cursor-pointer p-0"
                          onClick={(e) => {
                            e.stopPropagation()
                            if (msg.contact.id) onNavigate('contact', msg.contact.id)
                          }}
                        >
                          {msg.contact.full_name}
                        </button>
                        {msg.company?.name && (
                          <button
                            className="text-xs text-text-dim hover:text-accent-cyan transition-colors truncate text-left bg-transparent border-none cursor-pointer p-0"
                            onClick={(e) => {
                              e.stopPropagation()
                              if (msg.company?.id) onNavigate('company', msg.company.id)
                            }}
                          >
                            {msg.company.name}
                          </button>
                        )}
                      </div>
                    </td>

                    {/* Channel badge */}
                    <td
                      className="px-3 py-2.5"
                      onClick={() => setExpandedId(isExpanded ? null : msg.id)}
                    >
                      <span className={`inline-flex items-center px-2 py-0.5 text-xs font-medium rounded border whitespace-nowrap ${channelColors}`}>
                        {channelLabel}
                      </span>
                    </td>

                    {/* Step */}
                    <td
                      className="px-3 py-2.5 text-text-muted text-center"
                      onClick={() => setExpandedId(isExpanded ? null : msg.id)}
                    >
                      {msg.sequence_step}
                    </td>

                    {/* Status badge */}
                    <td
                      className="px-3 py-2.5"
                      onClick={() => setExpandedId(isExpanded ? null : msg.id)}
                    >
                      <span className={`inline-flex items-center px-2 py-0.5 text-xs font-medium rounded border whitespace-nowrap ${statusColors}`}>
                        {statusLabel}
                      </span>
                    </td>

                    {/* Body preview */}
                    <td
                      className="px-3 py-2.5 max-w-[300px]"
                      onClick={() => setExpandedId(isExpanded ? null : msg.id)}
                    >
                      {isExpanded ? (
                        <div className="text-sm text-text py-1 space-y-2">
                          {msg.subject && (
                            <div className="text-xs text-text-muted">
                              <span className="font-medium">Subject:</span> {msg.subject}
                            </div>
                          )}
                          <MessageBodyView body={msg.body} minHeight={200} />
                        </div>
                      ) : (
                        <div className="line-clamp-2">
                          <MessageBodyView body={msg.body} compact />
                        </div>
                      )}
                    </td>

                    {/* Actions */}
                    <td className="px-3 py-2.5 text-right">
                      <div className="flex items-center justify-end gap-1">
                        {isDraft && (
                          <>
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                handleApprove(msg)
                              }}
                              disabled={batchUpdate.isPending}
                              className="p-1.5 rounded text-success hover:bg-success/10 transition-colors bg-transparent border-none cursor-pointer disabled:opacity-50"
                              title="Approve"
                              aria-label="Approve message"
                            >
                              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M2.5 7.5l3 3 6-6" />
                              </svg>
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                handleReject(msg)
                              }}
                              disabled={batchUpdate.isPending}
                              className="p-1.5 rounded text-error hover:bg-error/10 transition-colors bg-transparent border-none cursor-pointer disabled:opacity-50"
                              title="Reject"
                              aria-label="Reject message"
                            >
                              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" />
                              </svg>
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>

        {(isLoading || isRefetching) && sortedMessages.length > 0 && (
          <div className="flex items-center justify-center py-3">
            <div className="w-5 h-5 border-2 border-border border-t-accent rounded-full animate-spin" />
            <span className="ml-2 text-sm text-text-muted">Refreshing...</span>
          </div>
        )}
      </div>

      {/* Bulk action bar */}
      <SelectionActionBar
        count={selectedIds.size}
        actions={[
          {
            label: 'Approve All',
            icon: (
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M2.5 7.5l3 3 6-6" />
              </svg>
            ),
            onClick: handleBulkApprove,
            loading: batchAction.isPending,
          },
          {
            label: 'Reject All',
            icon: (
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" />
              </svg>
            ),
            onClick: handleBulkReject,
            loading: batchAction.isPending,
          },
        ]}
        onDeselectAll={() => setSelectedIds(new Set())}
      />
    </div>
  )
}
