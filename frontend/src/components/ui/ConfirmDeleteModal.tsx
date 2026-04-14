import { useState } from 'react'
import { Modal } from './Modal'

interface ConfirmDeleteModalProps {
  entityType: 'contact' | 'company'
  count: number
  isAllMatching: boolean
  onConfirm: () => void
  onClose: () => void
  isLoading?: boolean
}

export function ConfirmDeleteModal({
  entityType,
  count,
  isAllMatching,
  onConfirm,
  onClose,
  isLoading,
}: ConfirmDeleteModalProps) {
  const [confirmed, setConfirmed] = useState(false)

  const entityLabel = entityType === 'contact'
    ? count === 1 ? 'contact' : 'contacts'
    : count === 1 ? 'company' : 'companies'

  const title = `Delete ${count.toLocaleString()} ${entityLabel}?`

  return (
    <Modal
      open
      onClose={onClose}
      title={title}
      actions={
        <>
          <button
            onClick={onClose}
            autoFocus
            className="px-3 py-1.5 text-xs text-text-muted hover:text-text bg-transparent border border-border-solid rounded-lg cursor-pointer transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={!confirmed || isLoading}
            className="px-4 py-1.5 text-xs font-medium rounded-lg bg-error text-white border-none cursor-pointer hover:bg-error/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? 'Deleting...' : `Delete ${count.toLocaleString()} ${entityLabel}`}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {/* Warning */}
        <div className="flex items-start gap-3 p-3 rounded-lg bg-error/10 border border-error/20">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-error flex-shrink-0 mt-0.5">
            <path d="M10 3L2 17h16L10 3z" />
            <path d="M10 8v4M10 14v.5" />
          </svg>
          <div className="text-sm text-text">
            {isAllMatching ? (
              <p>This will permanently delete <strong>all {count.toLocaleString()} matching {entityLabel}</strong>. This action cannot be undone.</p>
            ) : (
              <p>This will permanently delete <strong>{count.toLocaleString()} {entityLabel}</strong>. This action cannot be undone.</p>
            )}
          </div>
        </div>

        {/* Confirmation checkbox */}
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            className="w-4 h-4 accent-error cursor-pointer"
          />
          <span className="text-xs text-text-muted">
            I understand this action is irreversible
          </span>
        </label>
      </div>
    </Modal>
  )
}
