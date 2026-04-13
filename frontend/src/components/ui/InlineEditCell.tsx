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
}

export function InlineEditCell({
  value,
  displayValue,
  editType,
  options,
  reverseMap,
  onSave,
  cellStatus,
}: InlineEditCellProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const inputRef = useRef<HTMLInputElement | HTMLSelectElement>(null)

  // API returns display values (e.g. "Moderate Fit") but select options
  // are keyed by DB values (e.g. "moderate_fit"). Resolve via reverseMap.
  const resolvedValue = (reverseMap && value) ? (reverseMap[value] ?? value) : (value ?? '')

  // Focus input when entering edit mode
  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus()
      if (editType === 'text' && inputRef.current instanceof HTMLInputElement) {
        inputRef.current.select()
      }
    }
  }, [isEditing, editType])

  const startEditing = useCallback(() => {
    setEditValue(resolvedValue)
    setIsEditing(true)
  }, [resolvedValue])

  const cancelEditing = useCallback(() => {
    setIsEditing(false)
    setEditValue(resolvedValue)
  }, [resolvedValue])

  const handleSave = useCallback(async (newVal: string) => {
    setIsEditing(false)
    if (newVal === resolvedValue) return
    try {
      await onSave(newVal)
    } catch {
      // Error state handled by cellStatus
    }
  }, [resolvedValue, onSave])

  const handleSelectChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    const newVal = e.target.value
    setEditValue(newVal)
    handleSave(newVal)
  }, [handleSave])

  const handleTextKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleSave(editValue)
    } else if (e.key === 'Escape') {
      cancelEditing()
    }
  }, [handleSave, editValue, cancelEditing])

  const handleTextBlur = useCallback(() => {
    handleSave(editValue)
  }, [handleSave, editValue])

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
        <div className="flex items-center">
          <select
            ref={inputRef as React.RefObject<HTMLSelectElement>}
            value={editValue}
            onChange={handleSelectChange}
            onBlur={() => cancelEditing()}
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
      <div className="flex items-center">
        <input
          ref={inputRef as React.RefObject<HTMLInputElement>}
          type="text"
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onKeyDown={handleTextKeyDown}
          onBlur={handleTextBlur}
          className="w-full bg-surface-alt border border-accent rounded px-1.5 py-0.5 text-xs text-text focus:outline-none"
        />
      </div>
    )
  }

  // Read mode: click anywhere to edit, subtle hover hint
  const displayContent = displayValue ?? (value || '-')
  const isSelect = editType === 'select'
  return (
    <div
      className={`group/edit flex items-center min-w-0 rounded px-0.5 -mx-0.5 transition-colors hover:bg-white/[0.04] ${isSelect ? 'cursor-pointer' : 'cursor-text'}`}
      onClick={startEditing}
    >
      <span className="truncate">{displayContent}</span>
      {statusIcon}
      {/* Subtle dropdown chevron on hover for select fields */}
      {cellStatus !== 'saving' && isSelect && (
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="ml-1 flex-shrink-0 opacity-0 group-hover/edit:opacity-40 transition-opacity text-text-muted">
          <path d="M2.5 4L5 6.5L7.5 4" />
        </svg>
      )}
      {cellStatus === 'saving' && (
        <span className="ml-1 flex-shrink-0 w-3 h-3 border border-border border-t-accent rounded-full animate-spin" />
      )}
    </div>
  )
}
