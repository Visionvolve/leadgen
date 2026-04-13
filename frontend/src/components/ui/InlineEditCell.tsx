import { useState, useRef, useEffect, useCallback, type ReactNode } from 'react'

type CellStatus = 'saving' | 'saved' | 'error' | undefined

interface InlineEditCellProps {
  value: string | null
  displayValue?: ReactNode
  editType: 'select' | 'text'
  options?: Record<string, string>
  reverseMap?: Record<string, string>
  onSave: (newValue: string) => Promise<void>
  cellStatus?: CellStatus
  onRowClick?: () => void
}

export function InlineEditCell({
  value,
  displayValue,
  editType,
  options,
  reverseMap: _reverseMap,
  onSave,
  cellStatus,
  onRowClick,
}: InlineEditCellProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState(value ?? '')
  const inputRef = useRef<HTMLInputElement | HTMLSelectElement>(null)

  // Focus input when entering edit mode
  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus()
      if (editType === 'text' && inputRef.current instanceof HTMLInputElement) {
        inputRef.current.select()
      }
    }
  }, [isEditing, editType])

  const startEditing = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    // For select: find display value's db key as starting value
    setEditValue(value ?? '')
    setIsEditing(true)
  }, [value])

  const cancelEditing = useCallback(() => {
    setIsEditing(false)
    setEditValue(value ?? '')
  }, [value])

  const handleSave = useCallback(async (newVal: string) => {
    setIsEditing(false)
    if (newVal === (value ?? '')) return
    try {
      await onSave(newVal)
    } catch {
      // Error state handled by cellStatus
    }
  }, [value, onSave])

  const handleSelectChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    e.stopPropagation()
    const newVal = e.target.value
    setEditValue(newVal)
    handleSave(newVal)
  }, [handleSave])

  const handleTextKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    e.stopPropagation()
    if (e.key === 'Enter') {
      handleSave(editValue)
    } else if (e.key === 'Escape') {
      cancelEditing()
    }
  }, [handleSave, editValue, cancelEditing])

  const handleTextBlur = useCallback((e: React.FocusEvent) => {
    e.stopPropagation()
    handleSave(editValue)
  }, [handleSave, editValue])

  const handleCellClick = useCallback((e: React.MouseEvent) => {
    if (!isEditing) {
      onRowClick?.()
    } else {
      e.stopPropagation()
    }
  }, [isEditing, onRowClick])

  // Status indicator
  const statusIcon = cellStatus === 'saved' ? (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-green-400 ml-1 flex-shrink-0 animate-fade-in">
      <path d="M13 4L6 11L3 8" />
    </svg>
  ) : cellStatus === 'error' ? (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-red-400 ml-1 flex-shrink-0">
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  ) : null

  if (isEditing) {
    if (editType === 'select' && options) {
      return (
        <div className="flex items-center" onClick={(e) => e.stopPropagation()}>
          <select
            ref={inputRef as React.RefObject<HTMLSelectElement>}
            value={editValue}
            onChange={handleSelectChange}
            onBlur={() => cancelEditing()}
            onClick={(e) => e.stopPropagation()}
            className="w-full bg-surface-alt border border-accent rounded px-1.5 py-0.5 text-xs text-text focus:outline-none"
          >
            <option value="">-</option>
            {Object.entries(options).map(([dbVal, label]) => (
              <option key={dbVal} value={dbVal}>{label}</option>
            ))}
          </select>
        </div>
      )
    }

    return (
      <div className="flex items-center" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef as React.RefObject<HTMLInputElement>}
          type="text"
          value={editValue}
          onChange={(e) => { e.stopPropagation(); setEditValue(e.target.value) }}
          onKeyDown={handleTextKeyDown}
          onBlur={handleTextBlur}
          onClick={(e) => e.stopPropagation()}
          className="w-full bg-surface-alt border border-accent rounded px-1.5 py-0.5 text-xs text-text focus:outline-none"
        />
      </div>
    )
  }

  // Read mode: show value + pencil icon on hover
  const displayContent = displayValue ?? (value || '-')
  return (
    <div
      className="group/edit flex items-center min-w-0 cursor-pointer"
      onClick={handleCellClick}
    >
      <span className="truncate">{displayContent}</span>
      {statusIcon}
      {cellStatus !== 'saving' && (
        <button
          type="button"
          onClick={startEditing}
          className="ml-1 flex-shrink-0 opacity-0 group-hover/edit:opacity-100 transition-opacity p-0.5 rounded hover:bg-surface-alt text-text-dim hover:text-text-muted"
          aria-label="Edit"
        >
          <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z" />
          </svg>
        </button>
      )}
      {cellStatus === 'saving' && (
        <span className="ml-1 flex-shrink-0 w-3 h-3 border border-border border-t-accent rounded-full animate-spin" />
      )}
    </div>
  )
}
