import { useState, useCallback, useRef, useEffect } from 'react'

interface CampaignCheckboxCellProps {
  contactId: string
  isMember: boolean
  onToggle: (contactId: string, currentlyMember: boolean) => Promise<void>
  onUndo?: () => void
}

export function CampaignCheckboxCell({
  contactId,
  isMember,
  onToggle,
}: CampaignCheckboxCellProps) {
  const [isToggling, setIsToggling] = useState(false)
  const [showUndo, setShowUndo] = useState(false)
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (undoTimer.current) clearTimeout(undoTimer.current)
    }
  }, [])

  const handleChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    e.stopPropagation()
    setIsToggling(true)
    try {
      if (isMember) {
        // Removing — show undo toast
        await onToggle(contactId, true)
        setShowUndo(true)
        undoTimer.current = setTimeout(() => {
          setShowUndo(false)
        }, 5000)
      } else {
        await onToggle(contactId, false)
      }
    } catch {
      // Error handled by mutation
    } finally {
      setIsToggling(false)
    }
  }, [contactId, isMember, onToggle])

  const handleUndo = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (undoTimer.current) clearTimeout(undoTimer.current)
    setShowUndo(false)
    setIsToggling(true)
    try {
      // Re-add: toggle with isMember=false means "add"
      await onToggle(contactId, false)
    } catch {
      // Error handled by mutation
    } finally {
      setIsToggling(false)
    }
  }, [contactId, onToggle])

  return (
    <div className="relative flex items-center justify-center" onClick={(e) => e.stopPropagation()}>
      {isToggling ? (
        <span className="w-3.5 h-3.5 border border-border border-t-accent rounded-full animate-spin" />
      ) : (
        <input
          type="checkbox"
          checked={isMember}
          onChange={handleChange}
          onClick={(e) => e.stopPropagation()}
          className="w-3.5 h-3.5 accent-accent cursor-pointer"
          aria-label={isMember ? 'Remove from campaign' : 'Add to campaign'}
        />
      )}

      {/* Undo toast */}
      {showUndo && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 z-50 whitespace-nowrap">
          <div className="bg-surface border border-border-solid rounded-md shadow-lg px-2 py-1 flex items-center gap-1.5 text-[11px]">
            <span className="text-text-muted">Removed</span>
            <button
              type="button"
              onClick={handleUndo}
              className="text-accent-cyan hover:underline bg-transparent border-none cursor-pointer p-0 text-[11px] font-medium"
            >
              Undo
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
