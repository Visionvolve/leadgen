import { type ReactNode } from 'react'

interface SelectionActionBarProps {
  count: number
  isAllMatching?: boolean
  totalMatching?: number
  actions: Array<{
    label: string
    icon?: ReactNode
    onClick: () => void
    disabled?: boolean
    loading?: boolean
    destructive?: boolean
  }>
  onDeselectAll: () => void
}

export function SelectionActionBar({
  count,
  isAllMatching,
  totalMatching,
  actions,
  onDeselectAll,
}: SelectionActionBarProps) {
  if (count === 0) return null

  const label = isAllMatching && totalMatching
    ? `All ${totalMatching.toLocaleString()} matching filters`
    : `${count} selected`

  return (
    <div
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 flex items-center gap-3 px-4 py-2.5 rounded-xl bg-surface border border-border-solid shadow-lg"
      role="toolbar"
      aria-label={`Bulk actions for ${label}`}
      style={{ animation: 'slideUp 0.2s ease-out' }}
    >
      <span className="text-sm font-medium text-text whitespace-nowrap flex items-center gap-1.5">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="text-accent">
          <path d="M13.3 4.7L6 12l-3.3-3.3 1.4-1.4L6 9.2l5.9-5.9 1.4 1.4z" fill="currentColor" />
        </svg>
        {label}
      </span>

      <div className="w-px h-5 bg-border-solid" />

      {actions.map((action) => (
        <button
          key={action.label}
          onClick={action.onClick}
          disabled={action.disabled || action.loading}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap ${
            action.destructive
              ? 'bg-error/10 hover:bg-error/20 text-error border-error/30'
              : 'bg-surface-alt hover:bg-accent/10 text-text border-border-solid'
          }`}
        >
          {action.loading ? (
            <div className="w-3.5 h-3.5 border-2 border-border border-t-accent rounded-full animate-spin" />
          ) : action.icon}
          {action.label}
        </button>
      ))}

      <div className="w-px h-5 bg-border-solid" />

      <button
        onClick={onDeselectAll}
        className="flex items-center gap-1 px-2 py-1.5 text-xs text-text-muted hover:text-text bg-transparent border-none cursor-pointer transition-colors"
        aria-label="Deselect all"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" />
        </svg>
        Deselect
      </button>

      <style>{`
        @keyframes slideUp {
          from { transform: translateX(-50%) translateY(20px); opacity: 0; }
          to { transform: translateX(-50%) translateY(0); opacity: 1; }
        }
      `}</style>
    </div>
  )
}
