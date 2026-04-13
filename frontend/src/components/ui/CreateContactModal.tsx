import { useState, useMemo } from 'react'
import { Modal } from './Modal'
import { useCreateContact } from '../../api/queries/useContacts'
import { useCompanies } from '../../api/queries/useCompanies'
import {
  SENIORITY_DISPLAY,
  DEPARTMENT_DISPLAY,
} from '../../lib/display'

interface CreateContactModalProps {
  onClose: () => void
  onSuccess: () => void
}

export function CreateContactModal({ onClose, onSuccess }: CreateContactModalProps) {
  const createContact = useCreateContact()

  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [email, setEmail] = useState('')
  const [jobTitle, setJobTitle] = useState('')
  const [companyId, setCompanyId] = useState('')
  const [companySearch, setCompanySearch] = useState('')
  const [seniorityLevel, setSeniorityLevel] = useState('')
  const [department, setDepartment] = useState('')
  const [phoneNumber, setPhoneNumber] = useState('')
  const [notes, setNotes] = useState('')

  // Load companies for the searchable dropdown
  const { data: companiesData } = useCompanies({ search: companySearch || undefined })
  const companyOptions = useMemo(
    () => companiesData?.pages.flatMap((p) => p.companies) ?? [],
    [companiesData],
  )

  const canSubmit = firstName.trim().length > 0 && lastName.trim().length > 0

  const handleSubmit = async () => {
    if (!canSubmit) return
    try {
      const body: {
        first_name: string
        last_name: string
        email_address?: string
        job_title?: string
        company_id?: string
        seniority_level?: string
        department?: string
        phone_number?: string
        notes?: string
      } = {
        first_name: firstName.trim(),
        last_name: lastName.trim(),
      }
      if (email.trim()) body.email_address = email.trim()
      if (jobTitle.trim()) body.job_title = jobTitle.trim()
      if (companyId) body.company_id = companyId
      if (seniorityLevel) body.seniority_level = seniorityLevel
      if (department) body.department = department
      if (phoneNumber.trim()) body.phone_number = phoneNumber.trim()
      if (notes.trim()) body.notes = notes.trim()
      await createContact.mutateAsync(body)
      onSuccess()
    } catch {
      // error displayed below
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title="New Contact"
      actions={
        <>
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-xs text-text-muted hover:text-text bg-transparent border border-border-solid rounded-lg cursor-pointer transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit || createContact.isPending}
            className="px-4 py-1.5 text-xs font-medium rounded-lg bg-accent text-white border-none cursor-pointer hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {createContact.isPending ? 'Creating...' : 'Create Contact'}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        {/* Name row */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">
              First Name <span className="text-error">*</span>
            </label>
            <input
              type="text"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              placeholder="John"
              className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text placeholder:text-text-dim outline-none focus:border-accent"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">
              Last Name <span className="text-error">*</span>
            </label>
            <input
              type="text"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              placeholder="Doe"
              className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text placeholder:text-text-dim outline-none focus:border-accent"
            />
          </div>
        </div>

        {/* Email */}
        <div>
          <label className="block text-xs font-medium text-text-muted mb-1">Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="john@example.com"
            className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text placeholder:text-text-dim outline-none focus:border-accent"
          />
        </div>

        {/* Job Title */}
        <div>
          <label className="block text-xs font-medium text-text-muted mb-1">Job Title</label>
          <input
            type="text"
            value={jobTitle}
            onChange={(e) => setJobTitle(e.target.value)}
            placeholder="VP of Engineering"
            className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text placeholder:text-text-dim outline-none focus:border-accent"
          />
        </div>

        {/* Company (searchable dropdown) */}
        <div>
          <label className="block text-xs font-medium text-text-muted mb-1">Company</label>
          <input
            type="text"
            value={companySearch}
            onChange={(e) => { setCompanySearch(e.target.value); setCompanyId('') }}
            placeholder="Search companies..."
            className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text placeholder:text-text-dim outline-none focus:border-accent"
          />
          {companySearch && !companyId && companyOptions.length > 0 && (
            <div className="mt-1 max-h-[120px] overflow-auto border border-border-solid rounded-md bg-surface">
              {companyOptions.slice(0, 10).map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => { setCompanyId(c.id); setCompanySearch(c.name) }}
                  className="w-full text-left px-3 py-1.5 text-sm text-text hover:bg-surface-alt cursor-pointer border-none bg-transparent transition-colors"
                >
                  {c.name}
                  {c.domain && <span className="text-text-dim ml-1.5 text-xs">{c.domain}</span>}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Seniority + Department row */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">Seniority</label>
            <select
              value={seniorityLevel}
              onChange={(e) => setSeniorityLevel(e.target.value)}
              className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text outline-none focus:border-accent"
            >
              <option value="">--</option>
              {Object.entries(SENIORITY_DISPLAY).map(([val, label]) => (
                <option key={val} value={val}>{label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">Department</label>
            <select
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text outline-none focus:border-accent"
            >
              <option value="">--</option>
              {Object.entries(DEPARTMENT_DISPLAY).map(([val, label]) => (
                <option key={val} value={val}>{label}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Phone */}
        <div>
          <label className="block text-xs font-medium text-text-muted mb-1">Phone</label>
          <input
            type="text"
            value={phoneNumber}
            onChange={(e) => setPhoneNumber(e.target.value)}
            placeholder="+1 555-0123"
            className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text placeholder:text-text-dim outline-none focus:border-accent"
          />
        </div>

        {/* Notes */}
        <div>
          <label className="block text-xs font-medium text-text-muted mb-1">Notes</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Additional notes..."
            rows={2}
            className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text placeholder:text-text-dim outline-none focus:border-accent resize-none"
          />
        </div>
      </div>

      {/* Error */}
      {createContact.isError && (
        <p className="text-xs text-error mt-3">
          {createContact.error?.message ?? 'Failed to create contact'}
        </p>
      )}
    </Modal>
  )
}
