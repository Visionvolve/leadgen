import { useState, useCallback, useEffect } from 'react'
import { useUpdateCampaign, type CampaignDetail, type SenderConfig } from '../../../api/queries/useCampaigns'
import { getOAuthConnections, getGmailSendAuthUrl } from '../../../api/queries/useImports'
import type { OAuthConnection } from '../../../api/queries/useImports'
import { useToast } from '../../../components/ui/Toast'
import { SectionDivider } from '../../../components/ui/DetailField'

// ── Defaults & limits ────────────────────────────────────

const DEFAULTS: Required<Omit<SenderConfig, 'from_email' | 'from_name' | 'reply_to'>> = {
  linkedin_daily_connections: 12,
  linkedin_daily_messages: 25,
  linkedin_active_hours: { start: '08:00', end: '18:00' },
  linkedin_delay_range: { min: 60, max: 180 },
}

const RECOMMENDED = {
  linkedin_daily_connections: 15,
  linkedin_daily_messages: 30,
}

// ── Helpers ──────────────────────────────────────────────

function InputField({
  label,
  name,
  value,
  onChange,
  type = 'text',
  placeholder,
  required,
  disabled,
  helperText,
}: {
  label: string
  name: string
  value: string
  onChange: (name: string, value: string) => void
  type?: string
  placeholder?: string
  required?: boolean
  disabled?: boolean
  helperText?: string
}) {
  return (
    <div>
      <label className="text-xs text-text-muted mb-1 block">
        {label}
        {required && <span className="text-error ml-0.5">*</span>}
      </label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(name, e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        className="w-full bg-surface-alt border border-border-solid rounded-md px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent disabled:opacity-50 disabled:cursor-not-allowed"
      />
      {helperText && <p className="text-[11px] text-text-dim mt-1">{helperText}</p>}
    </div>
  )
}

function RangeField({
  label,
  value,
  min,
  max,
  onChange,
  disabled,
  warning,
}: {
  label: string
  value: number
  min: number
  max: number
  onChange: (val: number) => void
  disabled?: boolean
  warning?: boolean
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label className="text-xs text-text-muted">{label}</label>
        <div className="flex items-center gap-1.5">
          {warning && (
            <span className="text-[10px] px-1.5 py-0.5 bg-warning/15 text-warning rounded font-medium">
              Above recommended
            </span>
          )}
          <span className="text-sm font-medium text-text tabular-nums w-8 text-right">{value}</span>
        </div>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        disabled={disabled}
        className="w-full accent-accent h-1.5 bg-surface-alt rounded-full cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
      />
      <div className="flex justify-between text-[10px] text-text-dim mt-0.5">
        <span>{min}</span>
        <span>{max}</span>
      </div>
    </div>
  )
}

// ── Main component ───────────────────────────────────────

interface Props {
  campaign: CampaignDetail
  isEditable: boolean
}

export function SettingsTab({ campaign, isEditable }: Props) {
  const { toast } = useToast()
  const updateCampaign = useUpdateCampaign()

  // Local state mirrors the JSONB sender_config from the campaign
  const [config, setConfig] = useState<SenderConfig>(() => ({
    send_via: 'resend',
    from_email: '',
    from_name: '',
    reply_to: '',
    linkedin_daily_connections: DEFAULTS.linkedin_daily_connections,
    linkedin_daily_messages: DEFAULTS.linkedin_daily_messages,
    linkedin_active_hours: { ...DEFAULTS.linkedin_active_hours },
    linkedin_delay_range: { ...DEFAULTS.linkedin_delay_range },
    ...campaign.sender_config,
  }))

  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  // Gmail OAuth connection state
  const [gmailConnections, setGmailConnections] = useState<OAuthConnection[]>([])
  const [connectingGmail, setConnectingGmail] = useState(false)

  // Load OAuth connections on mount
  useEffect(() => {
    getOAuthConnections()
      .then((connections) => {
        // Filter for active Google connections with gmail.send scope
        const gmail = connections.filter(
          (c) =>
            c.provider === 'google' &&
            c.status === 'active' &&
            c.scopes?.includes('https://www.googleapis.com/auth/gmail.send'),
        )
        setGmailConnections(gmail)
      })
      .catch(() => {
        // Silently fail — user can still use Resend
      })
  }, [])

  // Sync when campaign data changes (e.g. after a refetch)
  useEffect(() => {
    setConfig({
      send_via: 'resend',
      from_email: '',
      from_name: '',
      reply_to: '',
      linkedin_daily_connections: DEFAULTS.linkedin_daily_connections,
      linkedin_daily_messages: DEFAULTS.linkedin_daily_messages,
      linkedin_active_hours: { ...DEFAULTS.linkedin_active_hours },
      linkedin_delay_range: { ...DEFAULTS.linkedin_delay_range },
      ...campaign.sender_config,
    })
    setDirty(false)
  }, [campaign.sender_config])

  // ── Field updaters ──

  const handleTextChange = useCallback((name: string, value: string) => {
    setConfig((prev) => ({ ...prev, [name]: value }))
    setDirty(true)
  }, [])

  const handleSliderChange = useCallback((name: string, value: number) => {
    setConfig((prev) => ({ ...prev, [name]: value }))
    setDirty(true)
  }, [])

  const handleActiveHoursChange = useCallback((field: 'start' | 'end', value: string) => {
    setConfig((prev) => ({
      ...prev,
      linkedin_active_hours: {
        ...(prev.linkedin_active_hours ?? DEFAULTS.linkedin_active_hours),
        [field]: value,
      },
    }))
    setDirty(true)
  }, [])

  const handleDelayChange = useCallback((field: 'min' | 'max', value: string) => {
    const num = parseInt(value, 10)
    if (isNaN(num)) return
    setConfig((prev) => ({
      ...prev,
      linkedin_delay_range: {
        ...(prev.linkedin_delay_range ?? DEFAULTS.linkedin_delay_range),
        [field]: num,
      },
    }))
    setDirty(true)
  }, [])

  // ── Save ──

  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      await updateCampaign.mutateAsync({
        id: campaign.id,
        data: { sender_config: config },
      })
      toast('Sender configuration saved', 'success')
      setDirty(false)
    } catch {
      toast('Failed to save sender configuration', 'error')
    } finally {
      setSaving(false)
    }
  }, [campaign.id, config, updateCampaign, toast])

  // ── Gmail connect ──

  const handleConnectGmail = useCallback(async () => {
    setConnectingGmail(true)
    try {
      const returnUrl = window.location.href
      const resp = await getGmailSendAuthUrl(returnUrl)
      window.location.href = resp.auth_url
    } catch {
      toast('Failed to start Gmail connection', 'error')
      setConnectingGmail(false)
    }
  }, [toast])

  const handleSendViaChange = useCallback((sendVia: 'resend' | 'gmail') => {
    setConfig((prev) => {
      const updated: SenderConfig = { ...prev, send_via: sendVia }
      if (sendVia === 'gmail' && gmailConnections.length > 0) {
        // Auto-select first connection
        updated.oauth_connection_id = gmailConnections[0].id
        updated.from_email = gmailConnections[0].provider_email ?? gmailConnections[0].email
      }
      return updated
    })
    setDirty(true)
  }, [gmailConnections])

  const handleGmailConnectionChange = useCallback((connectionId: string) => {
    const conn = gmailConnections.find((c) => c.id === connectionId)
    setConfig((prev) => ({
      ...prev,
      oauth_connection_id: connectionId,
      from_email: conn?.provider_email ?? conn?.email ?? prev.from_email,
    }))
    setDirty(true)
  }, [gmailConnections])

  // Derived state
  const sendVia = config.send_via ?? 'resend'
  const selectedGmailConnection = gmailConnections.find(
    (c) => c.id === config.oauth_connection_id,
  )

  // ── Warning flags ──

  const connectionsAboveRec =
    (config.linkedin_daily_connections ?? DEFAULTS.linkedin_daily_connections) > RECOMMENDED.linkedin_daily_connections
  const messagesAboveRec =
    (config.linkedin_daily_messages ?? DEFAULTS.linkedin_daily_messages) > RECOMMENDED.linkedin_daily_messages
  const hasLinkedInWarning = connectionsAboveRec || messagesAboveRec

  return (
    <div className="max-w-2xl space-y-6">
      {/* Save bar */}
      {dirty && isEditable && (
        <div className="flex items-center justify-between px-4 py-2.5 bg-accent/10 border border-accent/20 rounded-lg">
          <span className="text-xs text-text-muted">You have unsaved changes</span>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-1.5 text-xs font-medium rounded bg-accent text-white border-none cursor-pointer hover:bg-accent-hover transition-colors disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save Configuration'}
          </button>
        </div>
      )}

      {/* ── Send Via ── */}
      <div>
        <SectionDivider title="Email Delivery Method" />
        <p className="text-xs text-text-dim mb-4">
          Choose how outreach emails are sent
        </p>

        {/* Radio group */}
        <div className="flex gap-4 mb-4">
          <label className={`flex items-center gap-2 px-4 py-3 rounded-lg border cursor-pointer transition-colors ${sendVia === 'gmail' ? 'border-accent bg-accent/5' : 'border-border bg-surface-alt'}`}>
            <input
              type="radio"
              name="send_via"
              value="gmail"
              checked={sendVia === 'gmail'}
              onChange={() => handleSendViaChange('gmail')}
              disabled={!isEditable}
              className="accent-accent"
            />
            <div>
              <div className="text-sm font-medium text-text">Gmail</div>
              <div className="text-[11px] text-text-dim">Send from your real inbox</div>
            </div>
          </label>
          <label className={`flex items-center gap-2 px-4 py-3 rounded-lg border cursor-pointer transition-colors ${sendVia === 'resend' ? 'border-accent bg-accent/5' : 'border-border bg-surface-alt'}`}>
            <input
              type="radio"
              name="send_via"
              value="resend"
              checked={sendVia === 'resend'}
              onChange={() => handleSendViaChange('resend')}
              disabled={!isEditable}
              className="accent-accent"
            />
            <div>
              <div className="text-sm font-medium text-text">Resend</div>
              <div className="text-[11px] text-text-dim">Bulk sending with custom domain</div>
            </div>
          </label>
        </div>

        {/* Gmail-specific settings */}
        {sendVia === 'gmail' && (
          <div className="space-y-4 p-4 bg-surface-alt rounded-lg border border-border">
            {gmailConnections.length > 0 ? (
              <>
                <div>
                  <label className="text-xs text-text-muted mb-1 block">Gmail Account</label>
                  <select
                    value={config.oauth_connection_id ?? ''}
                    onChange={(e) => handleGmailConnectionChange(e.target.value)}
                    disabled={!isEditable}
                    className="w-full bg-surface border border-border-solid rounded-md px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent disabled:opacity-50"
                  >
                    {gmailConnections.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.provider_email ?? c.email}
                      </option>
                    ))}
                  </select>
                </div>
                {selectedGmailConnection && (
                  <div className="flex items-center gap-2 text-xs">
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-success/10 text-success rounded font-medium">
                      Connected
                    </span>
                    <span className="text-text-dim">
                      Emails will appear in your Sent folder
                    </span>
                  </div>
                )}
                <div className="flex items-start gap-2 px-3 py-2 bg-warning/5 border border-warning/15 rounded-lg">
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-warning flex-shrink-0 mt-0.5">
                    <path d="M8 1.5L1 14h14L8 1.5z" />
                    <path d="M8 6v3" />
                    <circle cx="8" cy="11.5" r="0.5" fill="currentColor" />
                  </svg>
                  <p className="text-[11px] text-text-dim">
                    Gmail daily limit: 100 emails. Emails are sent with a 45-second delay between each to protect your sender reputation.
                  </p>
                </div>
              </>
            ) : (
              <div className="text-center py-4">
                <p className="text-sm text-text-muted mb-3">
                  Connect your Gmail account to send emails from your inbox
                </p>
                <button
                  onClick={handleConnectGmail}
                  disabled={connectingGmail}
                  className="px-4 py-2 text-sm font-medium rounded bg-accent text-white border-none cursor-pointer hover:bg-accent-hover transition-colors disabled:opacity-50"
                >
                  {connectingGmail ? 'Connecting...' : 'Connect Gmail Account'}
                </button>
              </div>
            )}

            {/* From Name (optional for Gmail) */}
            <InputField
              label="From Name"
              name="from_name"
              value={config.from_name ?? ''}
              onChange={handleTextChange}
              placeholder="Jane Smith"
              disabled={!isEditable}
              helperText="Optional — defaults to your Gmail display name"
            />
            <InputField
              label="Reply-To Email"
              name="reply_to"
              value={config.reply_to ?? ''}
              onChange={handleTextChange}
              type="email"
              placeholder="replies@company.com"
              disabled={!isEditable}
              helperText="Optional — replies go to your Gmail address if not set"
            />
          </div>
        )}

        {/* Resend-specific settings */}
        {sendVia === 'resend' && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <InputField
              label="From Email"
              name="from_email"
              value={config.from_email ?? ''}
              onChange={handleTextChange}
              type="email"
              placeholder="outreach@company.com"
              required
              disabled={!isEditable}
              helperText="Required for email campaigns"
            />
            <InputField
              label="From Name"
              name="from_name"
              value={config.from_name ?? ''}
              onChange={handleTextChange}
              placeholder="Jane Smith"
              disabled={!isEditable}
            />
            <div className="sm:col-span-2">
              <InputField
                label="Reply-To Email"
                name="reply_to"
                value={config.reply_to ?? ''}
                onChange={handleTextChange}
                type="email"
                placeholder="replies@company.com"
                disabled={!isEditable}
                helperText="Optional — replies go to From Email if not set"
              />
            </div>
          </div>
        )}
      </div>

      {/* ── LinkedIn Safety ── */}
      <div>
        <SectionDivider title="LinkedIn Safety" />
        <p className="text-xs text-text-dim mb-2">
          Conservative defaults to protect your LinkedIn account
        </p>

        {/* Safety warning */}
        {hasLinkedInWarning && (
          <div className="flex items-start gap-2 px-3 py-2.5 mb-4 bg-warning/10 border border-warning/20 rounded-lg">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-warning flex-shrink-0 mt-0.5">
              <path d="M8 1.5L1 14h14L8 1.5z" />
              <path d="M8 6v3" />
              <circle cx="8" cy="11.5" r="0.5" fill="currentColor" />
            </svg>
            <div>
              <p className="text-xs font-medium text-warning">Limits above recommended levels</p>
              <p className="text-[11px] text-text-dim mt-0.5">
                High activity may trigger LinkedIn account restrictions.
                {' '}
                <a
                  href="https://phantombuster.com/blog/guides/linkedin-automation-rate-limits"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-accent-cyan hover:underline"
                >
                  Learn about safe limits
                </a>
              </p>
            </div>
          </div>
        )}

        <div className="space-y-5">
          {/* Daily limits */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            <RangeField
              label="Daily Connection Requests"
              value={config.linkedin_daily_connections ?? DEFAULTS.linkedin_daily_connections}
              min={1}
              max={25}
              onChange={(v) => handleSliderChange('linkedin_daily_connections', v)}
              disabled={!isEditable}
              warning={connectionsAboveRec}
            />
            <RangeField
              label="Daily Messages"
              value={config.linkedin_daily_messages ?? DEFAULTS.linkedin_daily_messages}
              min={1}
              max={50}
              onChange={(v) => handleSliderChange('linkedin_daily_messages', v)}
              disabled={!isEditable}
              warning={messagesAboveRec}
            />
          </div>

          {/* Active hours */}
          <div>
            <label className="text-xs text-text-muted mb-1.5 block">Active Hours</label>
            <div className="flex items-center gap-2">
              <input
                type="time"
                value={config.linkedin_active_hours?.start ?? DEFAULTS.linkedin_active_hours.start}
                onChange={(e) => handleActiveHoursChange('start', e.target.value)}
                disabled={!isEditable}
                className="bg-surface-alt border border-border-solid rounded-md px-2 py-1.5 text-sm text-text focus:outline-none focus:border-accent disabled:opacity-50 disabled:cursor-not-allowed"
              />
              <span className="text-xs text-text-dim">to</span>
              <input
                type="time"
                value={config.linkedin_active_hours?.end ?? DEFAULTS.linkedin_active_hours.end}
                onChange={(e) => handleActiveHoursChange('end', e.target.value)}
                disabled={!isEditable}
                className="bg-surface-alt border border-border-solid rounded-md px-2 py-1.5 text-sm text-text focus:outline-none focus:border-accent disabled:opacity-50 disabled:cursor-not-allowed"
              />
            </div>
            <p className="text-[11px] text-text-dim mt-1">Actions only during these hours (your local time)</p>
          </div>

          {/* Delay between actions */}
          <div>
            <label className="text-xs text-text-muted mb-1.5 block">Delay Between Actions (seconds)</label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                value={config.linkedin_delay_range?.min ?? DEFAULTS.linkedin_delay_range.min}
                onChange={(e) => handleDelayChange('min', e.target.value)}
                min={10}
                max={600}
                disabled={!isEditable}
                className="w-24 bg-surface-alt border border-border-solid rounded-md px-2 py-1.5 text-sm text-text focus:outline-none focus:border-accent disabled:opacity-50 disabled:cursor-not-allowed"
              />
              <span className="text-xs text-text-dim">to</span>
              <input
                type="number"
                value={config.linkedin_delay_range?.max ?? DEFAULTS.linkedin_delay_range.max}
                onChange={(e) => handleDelayChange('max', e.target.value)}
                min={10}
                max={600}
                disabled={!isEditable}
                className="w-24 bg-surface-alt border border-border-solid rounded-md px-2 py-1.5 text-sm text-text focus:outline-none focus:border-accent disabled:opacity-50 disabled:cursor-not-allowed"
              />
              <span className="text-xs text-text-dim">sec</span>
            </div>
            <p className="text-[11px] text-text-dim mt-1">Random delay between min and max to mimic human behavior</p>
          </div>
        </div>
      </div>
    </div>
  )
}
