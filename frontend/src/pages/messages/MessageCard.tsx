import { useState, useCallback } from 'react'
import { useUpdateMessage, useMarkMessageSent, type Message } from '../../api/queries/useMessages'
import { useToast } from '../../components/ui/Toast'
import { MessageBodyView } from '../../components/campaign/MessageBodyView'

const EDIT_REASONS = [
  { value: 'too_formal', label: 'Too formal' },
  { value: 'too_casual', label: 'Too casual' },
  { value: 'wrong_tone', label: 'Wrong tone' },
  { value: 'wrong_language', label: 'Wrong language' },
  { value: 'too_long', label: 'Too long' },
  { value: 'too_short', label: 'Too short' },
  { value: 'factually_wrong', label: 'Factually wrong' },
  { value: 'off_topic', label: 'Off topic' },
  { value: 'generic', label: 'Too generic' },
  { value: 'other', label: 'Other' },
]

const REVIEW_BADGE_COLORS: Record<string, string> = {
  draft: 'bg-warning/15 text-warning border-warning/30',
  approved: 'bg-success/15 text-success border-success/30',
  rejected: 'bg-error/15 text-error border-error/30',
  sent: 'bg-[#00B8CF]/15 text-[#00B8CF] border-[#00B8CF]/30',
}

function ReviewBadge({ status }: { status: string }) {
  const colors = REVIEW_BADGE_COLORS[status] ?? 'bg-[#8B92A0]/10 text-text-muted border-[#8B92A0]/20'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 text-xs font-medium rounded border whitespace-nowrap ${colors}`}>
      {status}
    </span>
  )
}

const CHANNEL_LABELS: Record<string, string> = {
  linkedin_connect: 'LI Connect',
  linkedin_message: 'LI Message',
  email: 'Email',
  call_script: 'Call',
}

const ANGLE_LABELS: Record<string, string> = {
  pain: 'Pain',
  opportunity: 'Opportunity',
  social_proof: 'Social Proof',
}

interface MessageCardProps {
  message: Message
  selected?: boolean
  onToggleSelect?: () => void
}

export function MessageCard({ message, selected, onToggleSelect }: MessageCardProps) {
  const { toast } = useToast()
  const mutation = useUpdateMessage()
  const markSentMutation = useMarkMessageSent()
  const [mode, setMode] = useState<'view' | 'edit' | 'reject'>('view')
  const [editBody, setEditBody] = useState(message.body)
  const [editReason, setEditReason] = useState('')
  const [rejectNotes, setRejectNotes] = useState('')

  const handleApprove = useCallback(async () => {
    try {
      await mutation.mutateAsync({
        id: message.id,
        data: { status: 'approved', approved_at: new Date().toISOString() },
      })
      toast('Message approved', 'success')
    } catch {
      toast('Failed to approve', 'error')
    }
  }, [message.id, mutation, toast])

  const bodyChanged = editBody !== message.body

  const handleSaveEdit = useCallback(async () => {
    if (!editBody.trim()) {
      toast('Body cannot be empty', 'error')
      return
    }
    if (bodyChanged && !editReason) {
      toast('Please select an edit reason', 'error')
      return
    }
    const data: Record<string, unknown> = { status: 'approved', approved_at: new Date().toISOString() }
    if (bodyChanged) {
      data.body = editBody
      data.edit_reason = editReason
    }
    try {
      await mutation.mutateAsync({ id: message.id, data })
      toast(bodyChanged ? 'Edited and approved' : 'Approved', 'success')
      setMode('view')
      setEditReason('')
    } catch {
      toast('Failed to save', 'error')
    }
  }, [message.id, editBody, editReason, bodyChanged, mutation, toast])

  const handleReject = useCallback(async () => {
    try {
      await mutation.mutateAsync({
        id: message.id,
        data: { status: 'rejected', review_notes: rejectNotes || null },
      })
      toast('Message rejected', 'info')
      setMode('view')
      setRejectNotes('')
    } catch {
      toast('Failed to reject', 'error')
    }
  }, [message.id, rejectNotes, mutation, toast])

  const handleReset = useCallback(async () => {
    try {
      await mutation.mutateAsync({
        id: message.id,
        data: { status: 'draft', approved_at: null, review_notes: null },
      })
      toast('Reset to draft', 'info')
    } catch {
      toast('Failed to reset', 'error')
    }
  }, [message.id, mutation, toast])

  const handleSendViaLinkedIn = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(message.body)
      toast('Message copied to clipboard', 'success')
    } catch {
      toast('Failed to copy message', 'error')
      return
    }
    if (message.contact.linkedin_url) {
      window.open(message.contact.linkedin_url, '_blank', 'noopener')
    }
    try {
      await markSentMutation.mutateAsync({ id: message.id, channel: 'linkedin' })
      toast('Marked as sent via LinkedIn', 'success')
    } catch {
      toast('Failed to mark as sent', 'error')
    }
  }, [message.id, message.body, message.contact.linkedin_url, markSentMutation, toast])

  const isDraft = message.status === 'draft'
  const isApproved = message.status === 'approved'
  const isRejected = message.status === 'rejected'
  const isLinkedInChannel = message.channel === 'linkedin_connect' || message.channel === 'linkedin_message'
  const hasLinkedInUrl = !!message.contact.linkedin_url

  const opacity = isApproved ? 'opacity-60' : isRejected ? 'opacity-40' : ''
  const borderColor = isApproved
    ? 'border-success/30'
    : isRejected
      ? 'border-error/30'
      : 'border-border-solid'

  return (
    <div className={`rounded-lg border ${borderColor} bg-surface p-4 ${opacity} transition-opacity ${selected ? 'ring-2 ring-accent/40' : ''}`}>
      {/* Card header */}
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        {onToggleSelect && (
          <input
            type="checkbox"
            checked={selected ?? false}
            onChange={onToggleSelect}
            className="w-3.5 h-3.5 rounded border-border-solid accent-accent cursor-pointer"
          />
        )}
        <span className="text-xs font-medium text-text-muted">
          Step {message.sequence_step} · {message.variant}
          {message.variant_angle && (
            <span className="ml-1 text-[10px] text-text-dim">({ANGLE_LABELS[message.variant_angle] ?? message.variant_angle})</span>
          )}
        </span>
        <span className="text-xs px-1.5 py-0.5 rounded bg-surface-alt text-text-muted border border-border-solid">
          {CHANNEL_LABELS[message.channel] ?? message.channel}
        </span>
        <ReviewBadge status={message.status} />
        {message.tone && <span className="text-xs text-text-dim">{message.tone}</span>}
        {message.language && <span className="text-xs text-text-dim">{message.language}</span>}
        {message.generation_cost != null && (
          <span className="text-xs text-text-dim ml-auto">{Math.round(message.generation_cost * 1000)} credits</span>
        )}
      </div>

      {/* Subject (email only) */}
      {message.subject && (
        <div className="text-sm font-medium text-text mb-1">{message.subject}</div>
      )}

      {/* Body */}
      {mode === 'edit' ? (
        <div className="space-y-2">
          <textarea
            value={editBody}
            onChange={(e) => setEditBody(e.target.value)}
            rows={5}
            className="w-full bg-surface-alt border border-border-solid rounded-md px-3 py-2 text-sm text-text resize-y focus:outline-none focus:border-accent"
          />
          {bodyChanged && (
            <select
              value={editReason}
              onChange={(e) => setEditReason(e.target.value)}
              className="w-full px-3 py-1.5 bg-surface-alt border border-border-solid rounded-md text-xs text-text focus:outline-none focus:border-accent"
            >
              <option value="">Edit reason *</option>
              {EDIT_REASONS.map(r => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          )}
          <div className="flex gap-2">
            <button
              onClick={handleSaveEdit}
              disabled={mutation.isPending || (bodyChanged && !editReason)}
              className="px-3 py-1.5 text-xs bg-accent hover:bg-accent-hover text-white rounded-md disabled:opacity-50"
            >
              {bodyChanged ? 'Save & Approve' : 'Approve'}
            </button>
            <button
              onClick={() => { setMode('view'); setEditBody(message.body); setEditReason('') }}
              className="px-3 py-1.5 text-xs text-text-muted hover:text-text"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : mode === 'reject' ? (
        <div className="space-y-2">
          <MessageBodyView body={message.body} minHeight={220} />
          <textarea
            value={rejectNotes}
            onChange={(e) => setRejectNotes(e.target.value)}
            rows={2}
            placeholder="Rejection reason (optional)"
            className="w-full bg-surface-alt border border-border-solid rounded-md px-3 py-2 text-sm text-text resize-y focus:outline-none focus:border-accent"
          />
          <div className="flex gap-2">
            <button
              onClick={handleReject}
              disabled={mutation.isPending}
              className="px-3 py-1.5 text-xs bg-error/20 text-error hover:bg-error/30 rounded-md border border-error/30 disabled:opacity-50"
            >
              Confirm Reject
            </button>
            <button
              onClick={() => { setMode('view'); setRejectNotes('') }}
              className="px-3 py-1.5 text-xs text-text-muted hover:text-text"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <MessageBodyView body={message.body} minHeight={220} />
      )}

      {/* Review notes (shown when approved/rejected) */}
      {mode === 'view' && message.review_notes && (
        <div className="mt-2 text-xs text-text-dim italic">
          Note: {message.review_notes}
        </div>
      )}

      {/* Actions */}
      {mode === 'view' && (
        <div className="flex items-center gap-2 mt-3 pt-2 border-t border-border/50">
          {isDraft && (
            <>
              <button onClick={handleApprove} disabled={mutation.isPending} className="px-2.5 py-1 text-xs text-success hover:bg-success/10 rounded transition-colors">Approve</button>
              <button onClick={() => setMode('edit')} className="px-2.5 py-1 text-xs text-accent-cyan hover:bg-accent/10 rounded transition-colors">Edit</button>
              <button onClick={() => setMode('reject')} className="px-2.5 py-1 text-xs text-error hover:bg-error/10 rounded transition-colors">Reject</button>
            </>
          )}
          {isApproved && isLinkedInChannel && hasLinkedInUrl && (
            <button
              onClick={handleSendViaLinkedIn}
              disabled={markSentMutation.isPending}
              className="px-2.5 py-1 text-xs text-[#0A66C2] hover:bg-[#0A66C2]/10 rounded transition-colors flex items-center gap-1"
            >
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 8V5M8 8V6.5a1.5 1.5 0 10-3 0M4 3.5v.01" />
              </svg>
              {markSentMutation.isPending ? 'Sending...' : 'Send via LinkedIn'}
            </button>
          )}
          {(isApproved || isRejected) && (
            <button onClick={handleReset} disabled={mutation.isPending} className="px-2.5 py-1 text-xs text-text-muted hover:text-text hover:bg-surface-alt rounded transition-colors">Reset to Draft</button>
          )}
        </div>
      )}
    </div>
  )
}
