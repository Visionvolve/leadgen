import { useState } from 'react'
import { Modal } from '../../components/ui/Modal'
import { useCreateUser } from '../../api/queries/useAdmin'

interface AddUserModalProps {
  open: boolean
  onClose: () => void
  tenantId: string
}

export function AddUserModal({ open, onClose, tenantId }: AddUserModalProps) {
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('viewer')
  const [error, setError] = useState<string | null>(null)

  const createUser = useCreateUser()

  function reset() {
    setEmail('')
    setDisplayName('')
    setPassword('')
    setRole('viewer')
    setError(null)
  }

  function handleClose() {
    reset()
    onClose()
  }

  function validate(): string | null {
    if (!email.trim()) {
      return 'Email is required.'
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      return 'Please enter a valid email address.'
    }
    // Display name and password only required for new users
    if (displayName.trim() && password && password.length < 8) {
      return 'Password must be at least 8 characters.'
    }
    return null
  }

  function handleSubmit() {
    const validationError = validate()
    if (validationError) {
      setError(validationError)
      return
    }

    setError(null)

    createUser.mutate(
      {
        email: email.trim(),
        display_name: displayName.trim(),
        password,
        role,
        tenant_id: tenantId,
      },
      {
        onSuccess: () => {
          handleClose()
        },
        onError: (err) => {
          setError(err instanceof Error ? err.message : 'Failed to create user.')
        },
      },
    )
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Add User to Namespace"
      actions={
        <>
          <button
            onClick={handleClose}
            className="border border-border text-text-muted px-4 py-2 rounded-md hover:bg-surface-alt transition-colors text-sm"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={createUser.isPending}
            className="bg-accent-cyan text-bg font-semibold px-4 py-2 rounded-md hover:opacity-90 transition-opacity text-sm disabled:opacity-50"
          >
            {createUser.isPending ? 'Adding...' : 'Add User'}
          </button>
        </>
      }
    >
      <div className="space-y-3.5">
        <div>
          <label className="block text-xs text-text-muted mb-1">Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full bg-surface-alt border border-border rounded-md px-3 py-2 text-sm text-text placeholder:text-text-dim focus:outline-none focus:border-accent-cyan"
            placeholder="user@company.com"
          />
          <p className="text-xs text-text-dim mt-1">
            If this user already exists, they will be granted access to this namespace.
          </p>
        </div>

        <div>
          <label className="block text-xs text-text-muted mb-1">Display Name</label>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="w-full bg-surface-alt border border-border rounded-md px-3 py-2 text-sm text-text placeholder:text-text-dim focus:outline-none focus:border-accent-cyan"
            placeholder="Jane Doe"
          />
        </div>

        <div>
          <label className="block text-xs text-text-muted mb-1">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full bg-surface-alt border border-border rounded-md px-3 py-2 text-sm text-text placeholder:text-text-dim focus:outline-none focus:border-accent-cyan"
            placeholder="Min 8 characters"
          />
        </div>

        <div>
          <label className="block text-xs text-text-muted mb-1">Role</label>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="w-full bg-surface-alt border border-border rounded-md px-3 py-2 text-sm text-text focus:outline-none focus:border-accent-cyan"
          >
            <option value="viewer">Viewer</option>
            <option value="editor">Editor</option>
            <option value="admin">Admin</option>
          </select>
        </div>

        {error && (
          <p className="text-red-400 text-xs">{error}</p>
        )}
      </div>
    </Modal>
  )
}
