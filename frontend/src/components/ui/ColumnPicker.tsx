import { useState, useRef, useEffect } from 'react'
import type { ColumnDef } from '../../config/columns'

interface CampaignColumnOption {
  id: string
  name: string
}

interface ColumnPickerProps<T> {
  allColumns: ColumnDef<T>[]
  visibleKeys: string[]
  onChange: (keys: string[]) => void
  onReset: () => void
  alwaysVisible?: string[]
  /** Campaign columns section — available campaigns with toggle state */
  campaigns?: CampaignColumnOption[]
  /** Which campaign IDs are currently shown as columns */
  activeCampaignIds?: string[]
  /** Toggle a campaign column on/off */
  onToggleCampaign?: (id: string) => void
}

export function ColumnPicker<T>({
  allColumns,
  visibleKeys,
  onChange,
  onReset,
  alwaysVisible = [],
  campaigns,
  activeCampaignIds,
  onToggleCampaign,
}: ColumnPickerProps<T>) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Close on click outside
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const toggleColumn = (key: string) => {
    if (alwaysVisible.includes(key)) return
    if (visibleKeys.includes(key)) {
      onChange(visibleKeys.filter((k) => k !== key))
    } else {
      // Insert at the position matching allColumns order
      const ordered = allColumns
        .map((c) => c.key)
        .filter((k) => visibleKeys.includes(k) || k === key)
      onChange(ordered)
    }
  }

  const visibleSet = new Set(visibleKeys)
  const defaultCount = allColumns.filter(
    (c) => c.defaultVisible !== false,
  ).length
  const isCustomised = visibleKeys.length !== defaultCount ||
    allColumns.some(
      (c) =>
        (c.defaultVisible !== false) !== visibleSet.has(c.key),
    )

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        className={`p-1.5 rounded-md border text-text-muted hover:text-text hover:border-accent transition-colors ${
          isCustomised
            ? 'border-accent/50 text-accent-cyan'
            : 'border-border-solid bg-surface-alt'
        }`}
        onClick={() => setOpen(!open)}
        title="Configure columns"
        aria-label="Configure columns"
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          <path d="M2 4h12M2 8h12M2 12h12" />
          <path d="M5 2v4M10 6v4M7 10v4" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-30 w-56 bg-surface border border-border-solid rounded-lg shadow-lg py-1 max-h-80 overflow-auto">
          <div className="px-3 py-1.5 text-xs font-medium text-text-muted border-b border-border/30">
            Visible columns ({visibleKeys.length}/{allColumns.length})
          </div>
          {allColumns.map((col) => {
            const isAlwaysVisible = alwaysVisible.includes(col.key)
            const isChecked = visibleSet.has(col.key)
            return (
              <label
                key={col.key}
                className={`flex items-center gap-2 px-3 py-1.5 text-sm cursor-pointer hover:bg-surface-alt/50 ${
                  isAlwaysVisible ? 'opacity-60 cursor-default' : ''
                } ${isChecked ? 'text-text' : 'text-text-muted'}`}
              >
                <input
                  type="checkbox"
                  checked={isChecked}
                  disabled={isAlwaysVisible}
                  onChange={() => toggleColumn(col.key)}
                  className="w-3.5 h-3.5 accent-accent cursor-pointer disabled:cursor-default"
                />
                <span className="truncate">{col.label}</span>
              </label>
            )
          })}
          {/* Campaign columns section */}
          {campaigns && campaigns.length > 0 && onToggleCampaign && (
            <>
              <div className="px-3 py-1.5 text-xs font-medium text-text-muted border-t border-border/30 mt-1">
                Campaign Columns
              </div>
              {campaigns.map((campaign) => {
                const isActive = activeCampaignIds?.includes(campaign.id) ?? false
                return (
                  <label
                    key={campaign.id}
                    className={`flex items-center gap-2 px-3 py-1.5 text-sm cursor-pointer hover:bg-surface-alt/50 ${
                      isActive ? 'text-text' : 'text-text-muted'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isActive}
                      onChange={() => onToggleCampaign(campaign.id)}
                      className="w-3.5 h-3.5 accent-accent cursor-pointer"
                    />
                    <span className="truncate">{campaign.name}</span>
                  </label>
                )
              })}
            </>
          )}
          {isCustomised && (
            <div className="border-t border-border/30 mt-1 pt-1">
              <button
                type="button"
                className="w-full px-3 py-1.5 text-xs text-text-muted hover:text-accent-cyan text-left"
                onClick={() => {
                  onReset()
                  setOpen(false)
                }}
              >
                Reset to defaults
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
