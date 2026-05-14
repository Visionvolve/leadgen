import { useEffect, useMemo, useRef, useState } from 'react'
import {
  useCampaign,
  useCampaignContacts,
  useSetTemplateBody,
  type CampaignContactItem,
} from '../../api/queries/useCampaigns'
import { useMessages, type Message } from '../../api/queries/useMessages'
import { useGeneratePreview, useSendTestEmail } from '../../api/queries/usePreview'
import { useAuth } from '../../hooks/useAuth'
import { useToast } from '../ui/Toast'
import { ApiError } from '../../api/client'

interface StepDetailDrawerProps {
  open: boolean
  onClose: () => void
  campaignId: string
  /** Position of the step being edited (defaults to 1 — the email step). */
  stepPosition?: number
}

const MAX_DEFAULT_CONTACTS = 5

/**
 * Right-side drawer for authoring a campaign step's email template.
 *
 *   ┌──────────────────────────────────────────────────┐
 *   │ Template editor (left)        │ Live preview     │
 *   │ - Subject                     │ - Contact picker │
 *   │ - From name / from email      │ - Subject        │
 *   │ - Body HTML                   │ - Iframe body    │
 *   │ - Body text fallback          │                  │
 *   ├───────────────────────────────┴──────────────────┤
 *   │ [Send test to me]    [Generate for all N]        │
 *   └──────────────────────────────────────────────────┘
 *
 * Save / Generate both call `set-template-body` which writes the body
 * verbatim onto every Message in the campaign and updates
 * `template_config[0].config` for round-trip readability.
 *
 * Send Test prefers an existing Message for the picked contact. If none
 * exists yet (or the editor values differ from what's stored), it first
 * persists the editor values via `set-template-body`, then sends.
 */
export function StepDetailDrawer({
  open,
  onClose,
  campaignId,
  stepPosition = 1,
}: StepDetailDrawerProps) {
  const { user } = useAuth()
  const { toast } = useToast()
  const drawerRef = useRef<HTMLDivElement>(null)

  // Data
  const { data: campaign } = useCampaign(open ? campaignId : null)
  const { data: contactsData } = useCampaignContacts(open ? campaignId : null)
  const { data: messagesData, refetch: refetchMessages } = useMessages({
    campaign_id: campaignId,
  })
  const previewMutation = useGeneratePreview()
  const sendTestMutation = useSendTestEmail()
  const setTemplateBody = useSetTemplateBody()

  // Pull the current values from template_config[0].config + sender_config
  // to seed the editor fields. Falls back to empty strings.
  // We cast through `unknown` because the backend serialises
  // `template_config` items as flexible dicts (sometimes carrying a
  // `config` blob with subject/body_html) while the frontend
  // `TemplateStep` interface is the narrower legacy shape.
  const seed = useMemo(() => {
    const tplRaw = (campaign?.template_config ?? []) as unknown
    const tpl = (Array.isArray(tplRaw) ? tplRaw : []) as Array<Record<string, unknown>>
    const first = (tpl[0] ?? {}) as Record<string, unknown>
    const cfg = (first.config as Record<string, unknown> | undefined) ?? {}
    const sender = (campaign?.sender_config ?? {}) as unknown as Record<string, unknown>
    return {
      subject: String(cfg.subject ?? first.subject ?? ''),
      body_html: String(cfg.body_html ?? ''),
      body_text: String(cfg.body_text ?? ''),
      from_name: String(sender.from_name ?? ''),
      from_email: String(sender.from_email ?? ''),
    }
  }, [campaign])

  // Editor state — initialized from `seed` whenever the drawer (re)opens
  // or the campaign data refetches with new values.
  const [subject, setSubject] = useState('')
  const [bodyHtml, setBodyHtml] = useState('')
  const [bodyText, setBodyText] = useState('')
  const [fromName, setFromName] = useState('')
  const [fromEmail, setFromEmail] = useState('')

  useEffect(() => {
    if (!open) return
    setSubject(seed.subject)
    setBodyHtml(seed.body_html)
    setBodyText(seed.body_text)
    setFromName(seed.from_name)
    setFromEmail(seed.from_email)
  }, [open, seed.subject, seed.body_html, seed.body_text, seed.from_name, seed.from_email])

  // Preview contact picker — first 5 alphabetically
  const pickerOptions = useMemo<CampaignContactItem[]>(() => {
    const all = contactsData?.contacts ?? []
    return [...all]
      .sort((a, b) => (a.full_name || '').localeCompare(b.full_name || ''))
      .slice(0, MAX_DEFAULT_CONTACTS)
  }, [contactsData])

  const [selectedContactId, setSelectedContactId] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setSelectedContactId(null)
      previewMutation.reset()
      sendTestMutation.reset()
      return
    }
    if (pickerOptions.length > 0 && pickerOptions[0]) {
      setSelectedContactId((current) => current ?? pickerOptions[0]!.contact_id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, pickerOptions.length])

  // Re-fetch the rendered preview whenever the picked contact changes.
  // (We do NOT live-render the editor's HTML — preview always reflects
  // the saved campaign template. Save first to see edits in the preview.)
  useEffect(() => {
    if (!open || !selectedContactId) return
    previewMutation.mutate({ campaignId, contactId: selectedContactId, stepPosition })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, selectedContactId, campaignId, stepPosition])

  // Pipe preview body into the iframe
  const iframeRef = useRef<HTMLIFrameElement>(null)
  useEffect(() => {
    const iframe = iframeRef.current
    if (!iframe) return
    const doc = iframe.contentDocument
    if (!doc) return
    const body = previewMutation.data?.body ?? ''
    const html = body
      ? `<!doctype html><html><head><meta charset="utf-8"><style>
          body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                 font-size: 14px; color: #222; padding: 16px; line-height: 1.55; margin: 0; }
          a { color: #2563eb; }
          pre, code { white-space: pre-wrap; word-break: break-word; }
          img { max-width: 100%; }
          table { max-width: 100%; }
        </style></head><body>${body}</body></html>`
      : ''
    doc.open()
    doc.write(html)
    doc.close()
  }, [previewMutation.data])

  // Close on Escape + lock body scroll
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handler)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  // ── Field validation ─────────────────────────────────
  const trimmedSubject = subject.trim()
  const trimmedBodyHtml = bodyHtml.trim()
  const trimmedFromEmail = fromEmail.trim()
  const fromEmailValid = !trimmedFromEmail || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedFromEmail)

  const hasChanges =
    subject !== seed.subject ||
    bodyHtml !== seed.body_html ||
    bodyText !== seed.body_text ||
    fromName !== seed.from_name ||
    fromEmail !== seed.from_email

  const canSave =
    !!trimmedSubject &&
    !!trimmedBodyHtml &&
    !!trimmedFromEmail &&
    fromEmailValid &&
    hasChanges

  const canGenerate =
    !!trimmedSubject && !!trimmedBodyHtml && !!trimmedFromEmail && fromEmailValid

  // ── Save (writes the editor → campaign + all messages) ───
  const persistEditor = async () => {
    return setTemplateBody.mutateAsync({
      campaignId,
      data: {
        subject: trimmedSubject,
        body_html: bodyHtml,
        body_text: bodyText || undefined,
        from_name: fromName.trim() || undefined,
        from_email: trimmedFromEmail,
      },
    })
  }

  const handleSave = async () => {
    if (!canSave) return
    try {
      await persistEditor()
      toast('Template saved', 'success')
      // Re-fetch the preview so the iframe reflects the new template.
      if (selectedContactId) {
        previewMutation.mutate({ campaignId, contactId: selectedContactId, stepPosition })
      }
      refetchMessages()
    } catch {
      toast('Failed to save template', 'error')
    }
  }

  // ── Generate (= save, with a different success message + close) ──
  const handleGenerate = async () => {
    if (!canGenerate) return
    try {
      const result = await persistEditor()
      const total =
        (result?.messages_created ?? 0) + (result?.messages_updated ?? 0)
      toast(
        `Generated ${total || (campaign?.total_contacts ?? 0)} messages — see Messages tab to review`,
        'success',
      )
      refetchMessages()
      onClose()
    } catch {
      toast('Failed to generate messages', 'error')
    }
  }

  // ── Send test ────────────────────────────────────────
  const [sendOk, setSendOk] = useState<{ to: string } | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setSendOk(null)
      setSendError(null)
    }
  }, [open])

  const messageForSelected: Message | null = useMemo(() => {
    if (!selectedContactId || !messagesData?.messages) return null
    const candidates = messagesData.messages.filter(
      (m) => m.contact.id === selectedContactId,
    )
    if (candidates.length === 0) return null
    const a = candidates.find((m) => (m.variant || '').toUpperCase() === 'A')
    return a ?? candidates[0] ?? null
  }, [selectedContactId, messagesData])

  const handleSendTest = async () => {
    if (!selectedContactId || !canGenerate) return
    setSendOk(null)
    setSendError(null)
    try {
      // If the editor has unsaved changes, persist them first so the test
      // reflects what the user is currently editing.
      let msgId = messageForSelected?.id ?? null
      if (hasChanges || !msgId) {
        await persistEditor()
        // After persistEditor, useMessages will refetch via cache
        // invalidation; explicitly refetch and pick a fresh message.
        const fresh = await refetchMessages()
        const list = fresh.data?.messages ?? []
        const candidates = list.filter((m) => m.contact.id === selectedContactId)
        const a = candidates.find((m) => (m.variant || '').toUpperCase() === 'A')
        msgId = a?.id ?? candidates[0]?.id ?? null
      }
      if (!msgId) {
        setSendError('No message available for this contact.')
        return
      }
      const res = await sendTestMutation.mutateAsync({ campaignId, messageId: msgId })
      setSendOk({ to: res.sent_to })
    } catch (err) {
      if (err instanceof ApiError) {
        setSendError(err.message || `Request failed (${err.status})`)
      } else {
        setSendError('Failed to send test email')
      }
    }
  }

  if (!open) return null

  const totalContacts = campaign?.total_contacts ?? 0

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Step template editor"
    >
      <div
        ref={drawerRef}
        data-testid="step-detail-drawer"
        className="w-full max-w-5xl h-full bg-surface border-l border-border-solid shadow-2xl shadow-black/40 flex flex-col"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-solid flex-shrink-0">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-wide text-text-muted">
              Step {stepPosition}
            </div>
            <h2 className="text-lg font-semibold font-title text-text truncate">
              Email template
            </h2>
          </div>
          <button
            onClick={onClose}
            className="ml-4 flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-md text-text-muted hover:text-text hover:bg-surface-alt transition-colors"
            aria-label="Close"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 4l8 8M12 4l-8 8" />
            </svg>
          </button>
        </div>

        {/* Body — two columns */}
        <div className="flex-1 overflow-y-auto">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 px-6 py-5">
            {/* ── Left: editor form ─────────────────────── */}
            <div className="space-y-4">
              <div>
                <div className="text-[10px] uppercase tracking-wide text-text-muted mb-1">
                  Channel
                </div>
                <div className="px-3 py-2 text-sm rounded border border-border bg-surface-alt/30 text-text-muted">
                  Email
                </div>
              </div>

              <div>
                <label
                  htmlFor="step-subject"
                  className="text-[10px] uppercase tracking-wide text-text-muted mb-1 block"
                >
                  Subject
                </label>
                <input
                  id="step-subject"
                  data-testid="step-subject-input"
                  type="text"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  className="w-full px-3 py-2 text-sm rounded border border-border bg-surface text-text focus:outline-none focus:border-accent"
                  placeholder="e.g. You're invited — AI Transformers Meetup"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label
                    htmlFor="step-from-name"
                    className="text-[10px] uppercase tracking-wide text-text-muted mb-1 block"
                  >
                    From name
                  </label>
                  <input
                    id="step-from-name"
                    data-testid="step-from-name-input"
                    type="text"
                    value={fromName}
                    onChange={(e) => setFromName(e.target.value)}
                    className="w-full px-3 py-2 text-sm rounded border border-border bg-surface text-text focus:outline-none focus:border-accent"
                    placeholder="Michal Lichko"
                  />
                </div>
                <div>
                  <label
                    htmlFor="step-from-email"
                    className="text-[10px] uppercase tracking-wide text-text-muted mb-1 block"
                  >
                    From email
                  </label>
                  <input
                    id="step-from-email"
                    data-testid="step-from-email-input"
                    type="email"
                    value={fromEmail}
                    onChange={(e) => setFromEmail(e.target.value)}
                    className={`w-full px-3 py-2 text-sm rounded border bg-surface text-text focus:outline-none focus:border-accent ${
                      fromEmailValid ? 'border-border' : 'border-error'
                    }`}
                    placeholder="hello@visionvolve.ai"
                  />
                  {!fromEmailValid && (
                    <p className="text-[10px] text-error mt-0.5">Enter a valid email address.</p>
                  )}
                </div>
              </div>

              <div>
                <label
                  htmlFor="step-body-html"
                  className="text-[10px] uppercase tracking-wide text-text-muted mb-1 block"
                >
                  Body HTML
                </label>
                <textarea
                  id="step-body-html"
                  data-testid="step-body-html-input"
                  value={bodyHtml}
                  onChange={(e) => setBodyHtml(e.target.value)}
                  rows={12}
                  spellCheck={false}
                  className="w-full px-3 py-2 text-xs rounded border border-border bg-surface text-text focus:outline-none focus:border-accent font-mono resize-y"
                  placeholder="<p>Hi {{first_name}},</p>..."
                />
                <p className="text-[10px] text-text-dim mt-1">
                  Placeholders: <code>{'{{first_name}}'}</code>, <code>{'{{vocative_name}}'}</code>,{' '}
                  <code>{'{{unsubscribe_url}}'}</code> — substituted per-recipient at send time.
                </p>
              </div>

              <div>
                <label
                  htmlFor="step-body-text"
                  className="text-[10px] uppercase tracking-wide text-text-muted mb-1 block"
                >
                  Body text fallback (optional)
                </label>
                <textarea
                  id="step-body-text"
                  data-testid="step-body-text-input"
                  value={bodyText}
                  onChange={(e) => setBodyText(e.target.value)}
                  rows={6}
                  className="w-full px-3 py-2 text-xs rounded border border-border bg-surface text-text focus:outline-none focus:border-accent font-mono resize-y"
                  placeholder="Plain-text version for clients that don't render HTML."
                />
              </div>

              <button
                type="button"
                data-testid="step-save-button"
                onClick={handleSave}
                disabled={!canSave || setTemplateBody.isPending}
                className="px-3 py-1.5 text-xs rounded bg-surface border border-border text-text hover:bg-surface-alt transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {setTemplateBody.isPending ? 'Saving…' : hasChanges ? 'Save changes' : 'Saved'}
              </button>
            </div>

            {/* ── Right: live preview ────────────────────── */}
            <div className="space-y-3">
              <div className="text-[10px] uppercase tracking-wide text-text-muted">
                Live preview
              </div>

              <div className="flex items-center gap-2">
                <label
                  htmlFor="step-preview-contact"
                  className="text-xs text-text-muted shrink-0"
                >
                  Render for:
                </label>
                <select
                  id="step-preview-contact"
                  data-testid="step-preview-contact-picker"
                  value={selectedContactId ?? ''}
                  onChange={(e) => setSelectedContactId(e.target.value || null)}
                  disabled={pickerOptions.length === 0}
                  className="flex-1 min-w-0 px-2 py-1.5 text-xs rounded border border-border bg-surface text-text focus:outline-none focus:border-accent disabled:opacity-50"
                >
                  {pickerOptions.length === 0 && (
                    <option value="">No contacts in this campaign</option>
                  )}
                  {pickerOptions.map((c) => (
                    <option key={c.contact_id} value={c.contact_id}>
                      {c.full_name}
                      {c.job_title ? ` — ${c.job_title}` : ''}
                      {c.company_name ? ` (${c.company_name})` : ''}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <div className="text-[10px] uppercase tracking-wide text-text-muted mb-1">
                  Subject preview
                </div>
                <div
                  data-testid="step-preview-subject"
                  className="px-3 py-2 text-sm rounded border border-border bg-surface-alt/30 text-text break-words min-h-[2.25rem]"
                >
                  {previewMutation.isPending ? (
                    <span className="inline-block w-2/3 h-3 bg-border-solid/40 rounded animate-pulse" />
                  ) : (
                    previewMutation.data?.subject || (
                      <span className="text-text-dim italic">(no subject)</span>
                    )
                  )}
                </div>
              </div>

              <div>
                <div className="text-[10px] uppercase tracking-wide text-text-muted mb-1">
                  Rendered body
                </div>
                <div className="relative rounded border border-border bg-white overflow-hidden">
                  {previewMutation.isPending && (
                    <div className="absolute inset-0 flex items-center justify-center bg-surface-alt/80 z-10">
                      <div className="space-y-2 w-3/4">
                        <div className="h-3 w-full bg-border-solid/40 rounded animate-pulse" />
                        <div className="h-3 w-5/6 bg-border-solid/40 rounded animate-pulse" />
                        <div className="h-3 w-4/6 bg-border-solid/40 rounded animate-pulse" />
                      </div>
                    </div>
                  )}
                  {previewMutation.isError && !previewMutation.isPending && (
                    <div className="p-4 text-xs text-error">
                      {previewMutation.error instanceof Error
                        ? previewMutation.error.message
                        : 'Preview failed'}
                    </div>
                  )}
                  <iframe
                    ref={iframeRef}
                    data-testid="step-preview-iframe"
                    title="Rendered email preview"
                    sandbox=""
                    className="w-full bg-white"
                    style={{ minHeight: 360, height: 420 }}
                  />
                </div>
              </div>

              {hasChanges && (
                <p className="text-[10px] text-warning">
                  Preview reflects the saved template. Save your edits to see them rendered.
                </p>
              )}
            </div>
          </div>
        </div>

        {/* Bottom action bar */}
        <div className="flex-shrink-0 border-t border-border-solid bg-surface/95 px-6 py-3">
          {sendOk && (
            <div
              data-testid="step-send-test-success"
              className="mb-2 text-xs px-3 py-2 rounded bg-success/10 text-success border border-success/30"
            >
              Test email sent to {sendOk.to}. Check your inbox in ~30s.
            </div>
          )}
          {sendError && (
            <div
              data-testid="step-send-test-error"
              className="mb-2 text-xs px-3 py-2 rounded bg-error/10 text-error border border-error/30 whitespace-pre-wrap"
            >
              {sendError}
            </div>
          )}
          <div className="flex items-center justify-end gap-2 flex-wrap">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-xs bg-transparent text-text-muted border border-border rounded hover:text-text transition-colors"
            >
              Close
            </button>
            <button
              type="button"
              data-testid="step-send-test-button"
              onClick={handleSendTest}
              disabled={
                !selectedContactId ||
                !canGenerate ||
                sendTestMutation.isPending ||
                setTemplateBody.isPending
              }
              title={`Send a test to ${user?.email ?? 'you'}`}
              className="px-3 py-1.5 text-xs bg-accent hover:bg-accent-hover text-white rounded transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {sendTestMutation.isPending ? 'Sending…' : 'Send test to me'}
            </button>
            <button
              type="button"
              data-testid="step-generate-button"
              onClick={handleGenerate}
              disabled={!canGenerate || setTemplateBody.isPending}
              className="px-3 py-1.5 text-xs bg-success hover:bg-success/90 text-white rounded transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {setTemplateBody.isPending
                ? 'Generating…'
                : `Generate messages for all ${totalContacts}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
