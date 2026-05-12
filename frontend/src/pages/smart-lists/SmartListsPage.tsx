/**
 * Smart Lists — saved audience-filter primitives for campaign prep.
 *
 * A smart list captures a named JSON filter spec over either contacts or
 * companies. Operators define filters once, then re-run on demand to pick
 * campaign audiences without writing ad-hoc SQL. Backs BL-1111 / BL-1112 /
 * BL-1113 (v25 Phase 10 — Campaign Database Foundations).
 */

import { useCallback, useMemo, useState } from 'react'
import {
  useSmartLists,
  useCreateSmartList,
  useDeleteSmartList,
  useRunSmartList,
  type SmartList,
  type SmartListTarget,
  type SmartListRunResult,
  type SmartListCompanyRow,
  type SmartListContactRow,
} from '../../api/queries/useSmartLists'
import { useToast } from '../../components/ui/Toast'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'

// --------------------------------------------------------------------------
// Filter dimensions exposed in the lightweight builder. Keys must match the
// allowed list in api/routes/smart_list_routes.py.
// --------------------------------------------------------------------------

const COMPANY_DIMENSIONS: {
  key: string
  label: string
  options: { value: string; label: string }[]
}[] = [
  {
    key: 'organization_type',
    label: 'Organization type',
    options: [
      { value: 'b2b_agency', label: 'B2B agency' },
      { value: 'b2c_business', label: 'B2C business' },
      { value: 'b2g_municipal', label: 'B2G — municipal' },
      { value: 'b2g_cultural', label: 'B2G — cultural' },
      { value: 'event_organizer', label: 'Event organizer' },
      { value: 'non_profit', label: 'Non-profit' },
      { value: 'other', label: 'Other' },
    ],
  },
  {
    key: 'geo_region',
    label: 'Geo region',
    options: [
      { value: 'dach', label: 'DACH' },
      { value: 'nordics', label: 'Nordics' },
      { value: 'benelux', label: 'Benelux' },
      { value: 'cee', label: 'CEE' },
      { value: 'uk_ireland', label: 'UK & Ireland' },
      { value: 'southern_europe', label: 'Southern Europe' },
      { value: 'us', label: 'US' },
      { value: 'other', label: 'Other' },
    ],
  },
  {
    key: 'engagement_status',
    label: 'Engagement status',
    options: [
      { value: 'cold', label: 'Cold' },
      { value: 'warm', label: 'Warm' },
      { value: 'hot', label: 'Hot' },
      { value: 'customer', label: 'Customer' },
    ],
  },
  {
    key: 'business_model',
    label: 'Business model',
    options: [
      { value: 'b2b', label: 'B2B' },
      { value: 'b2c', label: 'B2C' },
      { value: 'b2g', label: 'B2G' },
    ],
  },
]

const CONTACT_DIMENSIONS: typeof COMPANY_DIMENSIONS = [
  {
    key: 'organization_type',
    label: 'Org type (company)',
    options: COMPANY_DIMENSIONS[0]!.options,
  },
  {
    key: 'geo_region',
    label: 'Geo region (company)',
    options: COMPANY_DIMENSIONS[1]!.options,
  },
  {
    key: 'seniority_level',
    label: 'Seniority',
    options: [
      { value: 'cxo', label: 'C-level' },
      { value: 'vp', label: 'VP' },
      { value: 'director', label: 'Director' },
      { value: 'manager', label: 'Manager' },
      { value: 'individual', label: 'Individual contributor' },
    ],
  },
  {
    key: 'language',
    label: 'Language',
    options: [
      { value: 'cs', label: 'Czech' },
      { value: 'en', label: 'English' },
      { value: 'de', label: 'German' },
      { value: 'sk', label: 'Slovak' },
    ],
  },
]

// --------------------------------------------------------------------------
// Builder modal
// --------------------------------------------------------------------------

interface BuilderProps {
  onClose: () => void
  onCreated: () => void
}

function SmartListBuilder({ onClose, onCreated }: BuilderProps) {
  const { toast } = useToast()
  const create = useCreateSmartList()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [target, setTarget] = useState<SmartListTarget>('company')
  const [selected, setSelected] = useState<Record<string, string[]>>({})

  const dims = target === 'company' ? COMPANY_DIMENSIONS : CONTACT_DIMENSIONS

  const toggleValue = (key: string, value: string) => {
    setSelected((prev) => {
      const current = new Set(prev[key] ?? [])
      if (current.has(value)) current.delete(value)
      else current.add(value)
      const next = { ...prev }
      if (current.size === 0) delete next[key]
      else next[key] = Array.from(current)
      return next
    })
  }

  const handleSubmit = async () => {
    if (!name.trim()) {
      toast('Name is required', 'error')
      return
    }
    try {
      await create.mutateAsync({
        name: name.trim(),
        description: description.trim() || undefined,
        target,
        filters: selected,
      })
      toast('Smart list created', 'success')
      onCreated()
      onClose()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to create smart list'
      toast(msg, 'error')
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-surface rounded-lg p-6 w-[600px] max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-text mb-4">New smart list</h2>

        <div className="space-y-4">
          <label className="block">
            <span className="text-sm text-text-muted">Name</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. CZ agencies that don't know us"
              className="mt-1 block w-full rounded border border-border bg-surface px-3 py-1.5 text-sm"
              data-testid="smart-list-name"
            />
          </label>

          <label className="block">
            <span className="text-sm text-text-muted">Description (optional)</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className="mt-1 block w-full rounded border border-border bg-surface px-3 py-1.5 text-sm"
            />
          </label>

          <div>
            <span className="text-sm text-text-muted">Target</span>
            <div className="mt-1 flex gap-2">
              {(['company', 'contact'] as SmartListTarget[]).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => {
                    setTarget(t)
                    setSelected({})
                  }}
                  className={`px-3 py-1 text-sm rounded border ${
                    target === t
                      ? 'bg-accent-cyan/10 border-accent-cyan text-accent-cyan'
                      : 'border-border text-text-muted'
                  }`}
                >
                  {t === 'company' ? 'Companies' : 'Contacts'}
                </button>
              ))}
            </div>
          </div>

          {dims.map((dim) => (
            <div key={dim.key}>
              <span className="text-sm text-text-muted">{dim.label}</span>
              <div className="mt-1 flex flex-wrap gap-1">
                {dim.options.map((opt) => {
                  const active = (selected[dim.key] ?? []).includes(opt.value)
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => toggleValue(dim.key, opt.value)}
                      className={`px-2 py-0.5 text-xs rounded border ${
                        active
                          ? 'bg-accent-cyan/15 border-accent-cyan text-accent-cyan'
                          : 'border-border text-text-muted hover:border-accent'
                      }`}
                    >
                      {opt.label}
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded border border-border text-text-muted"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={create.isPending || !name.trim()}
            className="px-3 py-1.5 text-sm rounded bg-accent-cyan text-white disabled:opacity-50"
            data-testid="smart-list-save"
          >
            {create.isPending ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------
// Results panel
// --------------------------------------------------------------------------

function ResultsPanel({ result }: { result: SmartListRunResult | null }) {
  if (!result) return null

  if (result.companies) {
    return (
      <div className="mt-4 border border-border rounded bg-surface-alt p-3">
        <div className="text-sm font-semibold text-text">
          {result.total} matching {result.total === 1 ? 'company' : 'companies'}
        </div>
        <table className="w-full mt-2 text-xs">
          <thead>
            <tr className="text-text-muted">
              <th className="text-left py-1">Name</th>
              <th className="text-left py-1">Domain</th>
              <th className="text-left py-1">Org type</th>
              <th className="text-left py-1">Geo</th>
              <th className="text-left py-1">Engagement</th>
            </tr>
          </thead>
          <tbody>
            {result.companies.map((c: SmartListCompanyRow) => (
              <tr key={c.id} className="border-t border-border">
                <td className="py-1">{c.name}</td>
                <td className="py-1 text-text-muted">{c.domain ?? '—'}</td>
                <td className="py-1">{c.organization_type ?? '—'}</td>
                <td className="py-1">{c.geo_region ?? '—'}</td>
                <td className="py-1">{c.engagement_status ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  if (result.contacts) {
    return (
      <div className="mt-4 border border-border rounded bg-surface-alt p-3">
        <div className="text-sm font-semibold text-text">
          {result.total} matching {result.total === 1 ? 'contact' : 'contacts'}
        </div>
        <table className="w-full mt-2 text-xs">
          <thead>
            <tr className="text-text-muted">
              <th className="text-left py-1">Name</th>
              <th className="text-left py-1">Job title</th>
              <th className="text-left py-1">Company</th>
              <th className="text-left py-1">Language</th>
            </tr>
          </thead>
          <tbody>
            {result.contacts.map((c: SmartListContactRow) => (
              <tr key={c.id} className="border-t border-border">
                <td className="py-1">{c.full_name}</td>
                <td className="py-1 text-text-muted">{c.job_title ?? '—'}</td>
                <td className="py-1">{c.company_name ?? '—'}</td>
                <td className="py-1">{c.language ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  return null
}

// --------------------------------------------------------------------------
// Page
// --------------------------------------------------------------------------

export function SmartListsPage() {
  const { data, isLoading, refetch } = useSmartLists()
  const runList = useRunSmartList()
  const deleteList = useDeleteSmartList()
  const { toast } = useToast()

  const [builderOpen, setBuilderOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<SmartList | null>(null)
  const [runResult, setRunResult] = useState<SmartListRunResult | null>(null)
  const [activeListId, setActiveListId] = useState<string | null>(null)

  const lists = useMemo(() => data?.smart_lists ?? [], [data])

  const handleRun = useCallback(
    async (sl: SmartList) => {
      try {
        const res = await runList.mutateAsync({ id: sl.id })
        setRunResult(res)
        setActiveListId(sl.id)
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Run failed'
        toast(msg, 'error')
      }
    },
    [runList, toast],
  )

  const handleDelete = useCallback(async () => {
    if (!deleteTarget) return
    try {
      await deleteList.mutateAsync(deleteTarget.id)
      toast('Smart list deleted', 'success')
      if (activeListId === deleteTarget.id) {
        setRunResult(null)
        setActiveListId(null)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Delete failed'
      toast(msg, 'error')
    } finally {
      setDeleteTarget(null)
    }
  }, [deleteList, deleteTarget, activeListId, toast])

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-semibold text-text">Smart Lists</h1>
          <p className="text-sm text-text-muted">
            Saved audience filters for campaign prep — re-run any time to refresh
            the matching set.
          </p>
        </div>
        <button
          onClick={() => setBuilderOpen(true)}
          className="px-3 py-1.5 text-sm rounded bg-accent-cyan text-white"
          data-testid="smart-list-new"
        >
          + New smart list
        </button>
      </div>

      {isLoading ? (
        <div className="text-text-muted text-sm">Loading…</div>
      ) : lists.length === 0 ? (
        <div className="border border-border border-dashed rounded p-8 text-center text-text-muted">
          No smart lists yet. Click <strong>+ New smart list</strong> to create
          your first one.
        </div>
      ) : (
        <table className="w-full text-sm" data-testid="smart-list-table">
          <thead>
            <tr className="text-text-muted border-b border-border">
              <th className="text-left py-2">Name</th>
              <th className="text-left py-2">Target</th>
              <th className="text-left py-2">Last run</th>
              <th className="text-left py-2">Match count</th>
              <th className="text-right py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {lists.map((sl) => (
              <tr key={sl.id} className="border-b border-border">
                <td className="py-2">
                  <div className="font-medium text-text">{sl.name}</div>
                  {sl.description && (
                    <div className="text-xs text-text-muted">{sl.description}</div>
                  )}
                </td>
                <td className="py-2 text-text-muted">{sl.target}</td>
                <td className="py-2 text-text-muted text-xs">
                  {sl.last_run_at
                    ? new Date(sl.last_run_at).toLocaleString()
                    : '—'}
                </td>
                <td className="py-2">{sl.last_run_count ?? '—'}</td>
                <td className="py-2 text-right">
                  <button
                    onClick={() => handleRun(sl)}
                    disabled={runList.isPending}
                    className="px-2 py-1 text-xs rounded border border-accent-cyan text-accent-cyan mr-1"
                    data-testid={`smart-list-run-${sl.id}`}
                  >
                    Run
                  </button>
                  <button
                    onClick={() => setDeleteTarget(sl)}
                    className="px-2 py-1 text-xs rounded border border-border text-text-muted"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <ResultsPanel result={runResult} />

      {builderOpen && (
        <SmartListBuilder
          onClose={() => setBuilderOpen(false)}
          onCreated={() => refetch()}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete smart list?"
        message={
          deleteTarget
            ? `Delete "${deleteTarget.name}"? This cannot be undone.`
            : ''
        }
        confirmLabel="Delete"
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
