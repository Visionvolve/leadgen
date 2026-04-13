import { useState } from 'react'
import { Modal } from './Modal'
import { useCreateCompany } from '../../api/queries/useCompanies'
import {
  INDUSTRY_DISPLAY,
  COMPANY_SIZE_DISPLAY,
  GEO_REGION_DISPLAY,
} from '../../lib/display'

interface CreateCompanyModalProps {
  onClose: () => void
  onSuccess: () => void
}

export function CreateCompanyModal({ onClose, onSuccess }: CreateCompanyModalProps) {
  const createCompany = useCreateCompany()

  const [name, setName] = useState('')
  const [domain, setDomain] = useState('')
  const [websiteUrl, setWebsiteUrl] = useState('')
  const [industry, setIndustry] = useState('')
  const [companySize, setCompanySize] = useState('')
  const [geoRegion, setGeoRegion] = useState('')
  const [notes, setNotes] = useState('')

  const canSubmit = name.trim().length > 0

  const handleSubmit = async () => {
    if (!canSubmit) return
    try {
      const body: {
        name: string
        domain?: string
        website_url?: string
        industry?: string
        company_size?: string
        geo_region?: string
        notes?: string
      } = { name: name.trim() }
      if (domain.trim()) body.domain = domain.trim()
      if (websiteUrl.trim()) body.website_url = websiteUrl.trim()
      if (industry) body.industry = industry
      if (companySize) body.company_size = companySize
      if (geoRegion) body.geo_region = geoRegion
      if (notes.trim()) body.notes = notes.trim()
      await createCompany.mutateAsync(body)
      onSuccess()
    } catch {
      // error displayed below
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title="New Company"
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
            disabled={!canSubmit || createCompany.isPending}
            className="px-4 py-1.5 text-xs font-medium rounded-lg bg-accent text-white border-none cursor-pointer hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {createCompany.isPending ? 'Creating...' : 'Create Company'}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        {/* Name */}
        <div>
          <label className="block text-xs font-medium text-text-muted mb-1">
            Company Name <span className="text-error">*</span>
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Acme Corp"
            className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text placeholder:text-text-dim outline-none focus:border-accent"
            autoFocus
          />
        </div>

        {/* Domain + Website row */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">Domain</label>
            <input
              type="text"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder="acme.com"
              className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text placeholder:text-text-dim outline-none focus:border-accent"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">Website</label>
            <input
              type="text"
              value={websiteUrl}
              onChange={(e) => setWebsiteUrl(e.target.value)}
              placeholder="https://acme.com"
              className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text placeholder:text-text-dim outline-none focus:border-accent"
            />
          </div>
        </div>

        {/* Industry */}
        <div>
          <label className="block text-xs font-medium text-text-muted mb-1">Industry</label>
          <select
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text outline-none focus:border-accent"
          >
            <option value="">--</option>
            {Object.entries(INDUSTRY_DISPLAY).map(([val, label]) => (
              <option key={val} value={val}>{label}</option>
            ))}
          </select>
        </div>

        {/* Size + Region row */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">Company Size</label>
            <select
              value={companySize}
              onChange={(e) => setCompanySize(e.target.value)}
              className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text outline-none focus:border-accent"
            >
              <option value="">--</option>
              {Object.entries(COMPANY_SIZE_DISPLAY).map(([val, label]) => (
                <option key={val} value={val}>{label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">Region</label>
            <select
              value={geoRegion}
              onChange={(e) => setGeoRegion(e.target.value)}
              className="w-full px-3 py-1.5 text-sm bg-surface-alt border border-border-solid rounded-md text-text outline-none focus:border-accent"
            >
              <option value="">--</option>
              {Object.entries(GEO_REGION_DISPLAY).map(([val, label]) => (
                <option key={val} value={val}>{label}</option>
              ))}
            </select>
          </div>
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
      {createCompany.isError && (
        <p className="text-xs text-error mt-3">
          {createCompany.error?.message ?? 'Failed to create company'}
        </p>
      )}
    </Modal>
  )
}
