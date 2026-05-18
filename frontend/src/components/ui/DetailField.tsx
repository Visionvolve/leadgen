import { useState, useCallback, useEffect, useRef, type ReactNode } from 'react'
import { Badge } from './Badge'
import { SourceTooltip, type SourceInfo } from './SourceTooltip'

export type { SourceInfo } from './SourceTooltip'

/* ---- CopyButton: inline copy-to-clipboard with feedback ---- */

export function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Fallback for older browsers / non-HTTPS
      const ta = document.createElement('textarea')
      ta.value = value
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }
  }, [value])

  return (
    <button
      type="button"
      onClick={handleCopy}
      data-testid="copy-button"
      className="inline-flex items-center justify-center w-5 h-5 ml-1.5 rounded text-text-dim hover:text-accent-cyan hover:bg-accent-cyan/10 transition-colors opacity-0 group-hover/field:opacity-100 focus:opacity-100 shrink-0"
      aria-label={copied ? 'Copied' : 'Copy to clipboard'}
      title={copied ? 'Copied!' : 'Copy'}
    >
      {copied ? (
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M13 4L6 11L3 8" />
        </svg>
      ) : (
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <rect x="5" y="5" width="9" height="9" rx="1.5" />
          <path d="M11 5V3.5A1.5 1.5 0 009.5 2h-6A1.5 1.5 0 002 3.5v6A1.5 1.5 0 003.5 11H5" />
        </svg>
      )}
    </button>
  )
}

/* ---- FieldGrid: 2-column responsive layout ---- */

export function FieldGrid({ children, cols }: { children: ReactNode; cols?: 2 | 3 }) {
  const gridClass = cols === 3
    ? 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-3'
    : 'grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3'
  return <div className={gridClass}>{children}</div>
}

/* ---- Field: read-only label + value ---- */

interface FieldProps {
  label: string
  value: string | number | boolean | null | undefined
  className?: string
  source?: SourceInfo
}

export function Field({ label, value, className = '', source }: FieldProps) {
  const isEmpty = value === null || value === undefined || value === ''
  const display = isEmpty
    ? '-'
    : typeof value === 'boolean'
      ? value ? 'Yes' : 'No'
      : String(value)

  const copyValue = isEmpty ? null : String(value)

  return (
    <div className={`group/field ${className}`}>
      <dt className="text-xs text-text-muted mb-0.5">{label}{source && <SourceTooltip source={source} />}</dt>
      <dd className="text-sm text-text flex items-start">
        <span className="min-w-0">{display}</span>
        {copyValue && <CopyButton value={copyValue} />}
      </dd>
    </div>
  )
}

/* ---- FieldLink: value rendered as a link ---- */

interface FieldLinkProps {
  label: string
  value: string | null | undefined
  href: string | null | undefined
}

export function FieldLink({ label, value, href }: FieldLinkProps) {
  const displayText = value || href || null
  const copyValue = displayText && displayText !== '-' ? displayText : null

  return (
    <div className="group/field">
      <dt className="text-xs text-text-muted mb-0.5">{label}</dt>
      <dd className="text-sm flex items-start">
        {href ? (
          <a href={href} target="_blank" rel="noopener noreferrer" className="text-accent-cyan hover:underline min-w-0">
            {value || href}
          </a>
        ) : (
          <span className="text-text min-w-0">{value || '-'}</span>
        )}
        {copyValue && <CopyButton value={copyValue} />}
      </dd>
    </div>
  )
}

/* ---- FieldBadge: value rendered as a Badge ---- */

interface FieldBadgeProps {
  label: string
  value: string | null | undefined
  variant: 'status' | 'tier' | 'icp' | 'msgStatus'
}

export function FieldBadge({ label, value, variant }: FieldBadgeProps) {
  return (
    <div>
      <dt className="text-xs text-text-muted mb-0.5">{label}</dt>
      <dd className="text-sm">
        {value ? <Badge variant={variant} value={value} /> : <span className="text-text-dim">-</span>}
      </dd>
    </div>
  )
}

/* ---- EditableSelect ---- */

interface EditableSelectProps {
  label: string
  name: string
  value: string | null | undefined
  options: { value: string; label: string }[]
  onChange: (name: string, value: string) => void
}

export function EditableSelect({ label, name, value, options, onChange }: EditableSelectProps) {
  return (
    <div>
      <label className="text-xs text-text-muted mb-0.5 block">{label}</label>
      <select
        value={value || ''}
        onChange={(e) => onChange(name, e.target.value)}
        className="w-full bg-surface-alt border border-border-solid rounded-md px-2 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
      >
        <option value="">-</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}

/* ---- EditableText (single-line text input, blur to commit) ---- */

interface EditableTextProps {
  label: string
  name: string
  value: string | null | undefined
  onChange: (name: string, value: string) => void
  placeholder?: string
  helpText?: string
}

export function EditableText({ label, name, value, onChange, placeholder, helpText }: EditableTextProps) {
  const [localValue, setLocalValue] = useState(value || '')
  const isDirty = localValue !== (value || '')

  // Sync from parent when value changes externally (e.g. auto-derived salutation
  // after a first_name edit lands).
  const [prevValue, setPrevValue] = useState(value)
  if (value !== prevValue) {
    setPrevValue(value)
    setLocalValue(value || '')
  }

  const handleBlur = () => {
    if (!isDirty) return
    onChange(name, localValue)
  }

  return (
    <div>
      <label className="text-xs text-text-muted mb-0.5 block">{label}</label>
      <input
        type="text"
        value={localValue}
        onChange={(e) => setLocalValue(e.target.value)}
        onBlur={handleBlur}
        placeholder={placeholder}
        className="w-full bg-surface-alt border border-border-solid rounded-md px-2 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
      />
      {helpText && <p className="text-[11px] text-text-dim mt-0.5">{helpText}</p>}
    </div>
  )
}

/* ---- EditableTextarea ---- */

interface EditableTextareaProps {
  label: string
  name: string
  value: string | null | undefined
  onChange: (name: string, value: string) => void
  rows?: number
  maxLength?: number
  placeholder?: string
  helpText?: string
}

export function EditableTextarea({ label, name, value, onChange, rows = 3, maxLength, placeholder, helpText }: EditableTextareaProps) {
  const [localValue, setLocalValue] = useState(value || '')
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved'>('idle')
  const isDirty = localValue !== (value || '')

  // Sync from parent when value changes externally (e.g. template load)
  const [prevValue, setPrevValue] = useState(value)
  if (value !== prevValue) {
    setPrevValue(value)
    setLocalValue(value || '')
  }

  const remaining = maxLength ? maxLength - localValue.length : undefined

  const handleBlur = () => {
    if (!isDirty) return
    onChange(name, localValue)
    setSaveStatus('saved')
    setTimeout(() => setSaveStatus((s) => s === 'saved' ? 'idle' : s), 2000)
  }

  const helpId = helpText ? `${name}-help` : undefined
  const counterId = maxLength ? `${name}-counter` : undefined
  const describedBy = [helpId, counterId].filter(Boolean).join(' ') || undefined

  return (
    <div className="col-span-full">
      <label className="text-xs text-text-muted mb-0.5 block">{label}</label>
      <textarea
        value={localValue}
        onChange={(e) => setLocalValue(maxLength ? e.target.value.slice(0, maxLength) : e.target.value)}
        onBlur={handleBlur}
        rows={rows}
        maxLength={maxLength}
        placeholder={placeholder}
        aria-describedby={describedBy}
        className="w-full bg-surface-alt border border-border-solid rounded-md px-3 py-2 text-sm text-text resize-y focus:outline-none focus:border-accent"
      />
      {(maxLength || helpText || saveStatus === 'saved') && (
        <div className="flex items-center justify-between mt-1">
          <span id={helpId} className="text-[11px] text-text-dim">
            {helpText || ''}
          </span>
          <span className="flex items-center gap-2">
            {saveStatus === 'saved' && (
              <span className="text-[11px] text-green-400 transition-opacity">Saved</span>
            )}
            {remaining !== undefined && (
              <span
                id={counterId}
                className={`text-[11px] ${remaining < 100 ? 'text-red-400' : 'text-text-dim'}`}
                aria-live={remaining < 100 ? 'polite' : undefined}
              >
                {remaining}/{maxLength}
              </span>
            )}
          </span>
        </div>
      )}
    </div>
  )
}

/* ---- CollapsibleSection ---- */

interface CollapsibleSectionProps {
  title: string
  defaultOpen?: boolean
  children: ReactNode
  badge?: ReactNode
}

export function CollapsibleSection({ title, defaultOpen = false, children, badge }: CollapsibleSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen)

  return (
    <div className="border border-border-solid rounded-lg overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-4 py-3 bg-surface-alt hover:bg-surface-alt/80 transition-colors text-left"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-text">{title}</span>
          {badge}
        </div>
        <svg
          width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"
          className={`transition-transform ${isOpen ? 'rotate-180' : ''}`}
        >
          <path d="M4 6l4 4 4-4" />
        </svg>
      </button>
      {isOpen && <div className="px-4 py-4 border-t border-border-solid">{children}</div>}
    </div>
  )
}

/* ---- SectionDivider ---- */

export function SectionDivider({ title }: { title: string }) {
  return (
    <div className="mt-6 mb-3 flex items-center gap-3">
      <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider">{title}</h3>
      <div className="flex-1 h-px bg-border-solid" />
    </div>
  )
}

/* ---- MiniTable ---- */

interface MiniTableColumn<T> {
  key: string
  label: string
  render?: (item: T) => ReactNode
}

interface MiniTableProps<T> {
  columns: MiniTableColumn<T>[]
  data: T[]
  onRowClick?: (item: T) => void
  onRowAction?: (item: T) => void
  actionLabel?: string
  emptyText?: string
}

export function MiniTable<T extends object>({ columns, data, onRowClick, onRowAction, actionLabel, emptyText = 'None' }: MiniTableProps<T>) {
  if (data.length === 0) {
    return <p className="text-sm text-text-dim italic">{emptyText}</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-solid">
            {columns.map((col) => (
              <th key={col.key} className="text-left text-xs text-text-muted font-medium py-2 px-2">{col.label}</th>
            ))}
            {onRowAction && (
              <th className="text-right text-xs text-text-muted font-medium py-2 px-2">{actionLabel || ''}</th>
            )}
          </tr>
        </thead>
        <tbody>
          {data.map((row, i) => (
            <tr
              key={i}
              onClick={() => onRowClick?.(row)}
              className={`border-b border-border/50 ${onRowClick ? 'cursor-pointer hover:bg-surface-alt/50' : ''}`}
            >
              {columns.map((col) => (
                <td key={col.key} className="py-1.5 px-2 text-text">
                  {col.render ? col.render(row) : ((row as Record<string, unknown>)[col.key] as ReactNode) ?? '-'}
                </td>
              ))}
              {onRowAction && (
                <td className="py-1.5 px-2 text-right">
                  <button
                    onClick={(e) => { e.stopPropagation(); onRowAction(row) }}
                    className="text-xs text-text-muted hover:text-error cursor-pointer bg-transparent border-none transition-colors"
                  >
                    {actionLabel || 'Action'}
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}


/* ---- EditableHeading (BL-1203 / Phase 12) ---- */

export interface EditableHeadingProps {
  /** Aria-label for the pencil button + name attribute. */
  name: string
  value: string
  /** Async save callback. May throw — error.message displayed inline. */
  onSave: (newValue: string) => Promise<void>
  onCancel?: () => void
  placeholder?: string
  /** Tailwind class string applied to the non-editing heading element. */
  className?: string
}

/**
 * Click-to-edit heading. Renders as an `<h2>` with a hover-revealed pencil
 * button; clicking the pencil (or the heading itself) switches to an input
 * with Save / Cancel buttons.
 *
 * Enter = save, Esc = cancel. `onSave` is awaited; on throw the input stays
 * open and the error message is shown in red beneath the input.
 *
 * Used by CompanyDetailPage to inline-edit the company name with the
 * shared 409-duplicate gate.
 */
export function EditableHeading({
  name,
  value,
  onSave,
  onCancel,
  placeholder,
  className = '',
}: EditableHeadingProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  // Re-sync draft to value when value changes externally AND not editing.
  useEffect(() => {
    if (!editing) setDraft(value)
  }, [value, editing])

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  const cancel = () => {
    setDraft(value)
    setEditing(false)
    setError(null)
    onCancel?.()
  }

  const save = async () => {
    if (draft === value) {
      setEditing(false)
      return
    }
    setSaving(true)
    setError(null)
    try {
      await onSave(draft)
      setEditing(false)
    } catch (e) {
      setError((e as Error).message || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      void save()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      cancel()
    }
  }

  if (!editing) {
    return (
      <div className={`group flex items-center gap-2 min-w-0 ${className}`}>
        <h2 className="text-lg font-semibold font-title text-text truncate">
          {value || placeholder || '—'}
        </h2>
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="opacity-0 group-hover:opacity-100 text-text-muted hover:text-text transition-opacity"
          aria-label={`Edit ${name}`}
          title="Edit"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M11 1l4 4-9 9H2v-4l9-9z" />
          </svg>
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1 min-w-0">
      <div className="flex items-center gap-2">
        <input
          ref={inputRef}
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKey}
          placeholder={placeholder}
          disabled={saving}
          className="flex-1 min-w-0 bg-surface-alt border border-border-solid rounded-md px-2 py-1 text-lg font-semibold font-title text-text focus:outline-none focus:border-accent disabled:opacity-50"
          aria-label={name}
        />
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving || draft === value}
          className="px-2 py-1 text-xs rounded bg-accent text-white hover:bg-accent-hover disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          onClick={cancel}
          disabled={saving}
          className="px-2 py-1 text-xs rounded border border-border-solid text-text-muted hover:bg-surface-alt disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
      {error && <p className="text-xs text-status-error">{error}</p>}
    </div>
  )
}
