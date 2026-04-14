import { useState } from 'react'
import { ConfirmDeleteModal } from './ConfirmDeleteModal'

interface DeleteActionCellProps {
  entityType: 'contact' | 'company'
  entityId: string
  entityName: string
  onDelete: (id: string) => void
  isDeleting?: boolean
}

/**
 * Inline trash icon button for table rows.
 * Shows a confirmation modal before deleting.
 */
export function DeleteActionCell({
  entityType,
  entityId,
  entityName,
  onDelete,
  isDeleting,
}: DeleteActionCellProps) {
  const [showConfirm, setShowConfirm] = useState(false)

  return (
    <>
      <button
        onClick={(e) => {
          e.stopPropagation()
          setShowConfirm(true)
        }}
        className="inline-flex items-center justify-center w-6 h-6 rounded opacity-20 hover:opacity-100 hover:text-error transition-all cursor-pointer bg-transparent border-none text-text-dim p-0"
        title={`Delete ${entityName}`}
        aria-label={`Delete ${entityName}`}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M2 4h12M5.333 4V2.667a1.333 1.333 0 0 1 1.334-1.334h2.666a1.333 1.333 0 0 1 1.334 1.334V4M12.667 4v9.333a1.333 1.333 0 0 1-1.334 1.334H4.667a1.333 1.333 0 0 1-1.334-1.334V4h9.334z" />
        </svg>
      </button>
      {showConfirm && (
        <ConfirmDeleteModal
          entityType={entityType}
          count={1}
          isAllMatching={false}
          entityName={entityName}
          onConfirm={() => onDelete(entityId)}
          onClose={() => setShowConfirm(false)}
          isLoading={isDeleting}
        />
      )}
    </>
  )
}
