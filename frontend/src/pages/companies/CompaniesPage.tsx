import { useState, useMemo, useCallback, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useInlineEdit } from '../../hooks/useInlineEdit'
import { useParams, useNavigate } from 'react-router'
import { withRev } from '../../lib/revision'
import { useCompanies, useDeleteCompany, type CompanyFilters, type CompanyListItem } from '../../api/queries/useCompanies'
import { useTags } from '../../api/queries/useTags'
import { useBulkAddTags, useBulkDelete, useCompaniesMatchingCount } from '../../api/queries/useBulkActions'
import { useLocalStorage } from '../../hooks/useLocalStorage'
import { useAdvancedFilters, COMPANY_MULTI_KEYS } from '../../hooks/useAdvancedFilters'
import { useFilterCounts } from '../../hooks/useFilterCounts'
import { useColumnVisibility } from '../../hooks/useColumnVisibility'
import { useShareView } from '../../hooks/useShareView'
import { DataTable, type SelectionMode } from '../../components/ui/DataTable'
import { FilterSidebar, type FilterGroup } from '../../components/ui/FilterSidebar'
import { ColumnPicker } from '../../components/ui/ColumnPicker'
import { SelectionActionBar } from '../../components/ui/SelectionActionBar'
import { TagPicker } from '../../components/ui/TagPicker'
import { CreateCompanyModal } from '../../components/ui/CreateCompanyModal'
import { ConfirmDeleteModal } from '../../components/ui/ConfirmDeleteModal'
import { DeleteActionCell } from '../../components/ui/DeleteActionCell'
import { useToast } from '../../components/ui/Toast'
import { useScrollRestore } from '../../hooks/useScrollRestore'
import { COMPANY_COLUMNS, COMPANY_ALWAYS_VISIBLE } from '../../config/companyColumns'
import {
  ENRICHMENT_STAGE_DISPLAY,
  TIER_DISPLAY,
  INDUSTRY_DISPLAY,
  COMPANY_SIZE_DISPLAY,
  GEO_REGION_DISPLAY,
  REVENUE_RANGE_DISPLAY,
  ORGANIZATION_TYPE_DISPLAY,
} from '../../lib/display'

/** Build MultiSelectFilter options from a display map + optional facet counts */
function buildMultiOptions(
  displayMap: Record<string, string>,
  facets?: { value: string; count: number }[],
) {
  const countMap = new Map<string, number>()
  if (facets) {
    for (const f of facets) countMap.set(f.value, f.count)
  }
  return Object.entries(displayMap).map(([dbVal, label]) => ({
    value: dbVal,
    label,
    count: countMap.get(dbVal),
  }))
}

export function CompaniesPage() {
  const { namespace } = useParams<{ namespace: string }>()
  const navigate = useNavigate()
  const { toast } = useToast()
  const qc = useQueryClient()

  // Advanced filters (persisted to localStorage)
  const {
    filters: advFilters,
    setSimpleFilter,
    setMultiFilter,
    toggleExclude,
    clearAll,
    replaceAll,
    activeFilterCount,
    getMulti,
    toQueryParams,
    toCountsPayload,
  } = useAdvancedFilters('co_adv_filters', COMPANY_MULTI_KEYS)

  const [sortField, setSortField] = useLocalStorage('co_sort_field', 'name')
  const [sortDir, setSortDir] = useLocalStorage<'asc' | 'desc'>('co_sort_dir', 'asc')
  const [sidebarCollapsed, setSidebarCollapsed] = useLocalStorage('co_filters_sidebar_collapsed', false)

  // Column visibility
  const [visibleKeys, setVisibleKeys, resetColumns] = useColumnVisibility(
    'co_visible_cols',
    COMPANY_COLUMNS,
  )

  // Share view
  const { shareView } = useShareView({
    visibleKeys,
    filters: advFilters,
    sortField,
    sortDir,
    setVisibleKeys,
    replaceAllFilters: replaceAll,
    setSortField,
    setSortDir,
    toast,
  })

  // Selection state
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [selectionMode, setSelectionMode] = useState<SelectionMode>('explicit')
  const [showTagPicker, setShowTagPicker] = useState(false)
  const [showCreateCompany, setShowCreateCompany] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  // Inline editing
  const inlineEdit = useInlineEdit('company')

  const { data: tagsData } = useTags()
  const bulkAddTags = useBulkAddTags()
  const bulkDelete = useBulkDelete()
  const deleteCompany = useDeleteCompany()
  const matchingCount = useCompaniesMatchingCount()

  // Scroll position restore (saves before navigating to detail, restores on mount)
  const { saveScrollPosition } = useScrollRestore('companies_scroll')

  // Listen for custom navigation events from column renderers
  useEffect(() => {
    const handler = (e: Event) => {
      const path = (e as CustomEvent<string>).detail
      if (path) {
        saveScrollPosition()
        navigate(withRev(path), { state: { origin: withRev(`/${namespace}/companies`) } })
      }
    }
    window.addEventListener('leadgen:navigate', handler)
    return () => window.removeEventListener('leadgen:navigate', handler)
  }, [navigate, namespace, saveScrollPosition])

  // Build CompanyFilters from advanced state + sort
  const filters: CompanyFilters = useMemo(() => ({
    ...toQueryParams(),
    sort: sortField,
    sort_dir: sortDir,
  }), [toQueryParams, sortField, sortDir])

  // Active filters for bulk actions (no sort params)
  const activeFilters = useMemo(() => {
    const params = toQueryParams()
    delete params.sort
    delete params.sort_dir
    return params
  }, [toQueryParams])

  // Filter counts for faceted options
  const countsPayload = useMemo(() => toCountsPayload(), [toCountsPayload])
  const { data: countsData } = useFilterCounts(countsPayload, '/companies/filter-counts')

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
  } = useCompanies(filters)

  // Dedup memo safety net: even with the backend `id ASC` tiebreaker in place,
  // a brief overlap can still leak through if pages overlap during refetch.
  // Drop any company whose id was already emitted by an earlier page. (BL-1116)
  const allCompanies = useMemo(() => {
    if (!data?.pages) return []
    const seen = new Set<string>()
    const result: CompanyListItem[] = []
    for (const p of data.pages) {
      for (const c of p.companies) {
        if (!c.id || seen.has(c.id)) continue
        seen.add(c.id)
        result.push(c)
      }
    }
    return result
  }, [data])
  const total = data?.pages[0]?.total ?? 0

  const handleFilterChange = useCallback((key: string, value: string) => {
    setSimpleFilter(key, value)
    // Clear selection when filters change
    setSelectedIds(new Set())
    setSelectionMode('explicit')
    // Invalidate the cached pages so the table refetches from page 1 instead of
    // rendering stale data accumulated under the old filter set. (BL-1116)
    qc.invalidateQueries({ queryKey: ['companies'] })
  }, [setSimpleFilter, qc])

  const handleSort = useCallback((field: string, dir: 'asc' | 'desc') => {
    setSortField(field)
    setSortDir(dir)
  }, [setSortField, setSortDir])

  const handleSelectionChange = useCallback((ids: Set<string>, mode: SelectionMode) => {
    setSelectedIds(ids)
    setSelectionMode(mode)
    if (mode === 'all-matching') {
      matchingCount.mutate(activeFilters)
    }
  }, [matchingCount, activeFilters])

  const handleDeselectAll = useCallback(() => {
    setSelectedIds(new Set())
    setSelectionMode('explicit')
  }, [])

  const handleBulkDelete = useCallback(async () => {
    try {
      const payload = selectionMode === 'all-matching'
        ? { entity_type: 'company' as const, filters: activeFilters }
        : { entity_type: 'company' as const, ids: Array.from(selectedIds) }
      const result = await bulkDelete.mutateAsync(payload)
      toast(`Deleted ${result.deleted} compan${result.deleted !== 1 ? 'ies' : 'y'}`, 'success')
      setShowDeleteConfirm(false)
      handleDeselectAll()
    } catch {
      toast('Failed to delete companies', 'error')
    }
  }, [selectionMode, activeFilters, selectedIds, bulkDelete, toast, handleDeselectAll])

  // Inline single-record delete
  const handleInlineDelete = useCallback(async (id: string) => {
    try {
      await deleteCompany.mutateAsync(id)
      toast('Company deleted', 'success')
    } catch {
      toast('Failed to delete company', 'error')
    }
  }, [deleteCompany, toast])

  const handleAddTags = useCallback(async (tagIds: string[]) => {
    try {
      const payload = selectionMode === 'all-matching'
        ? { entity_type: 'company' as const, filters: activeFilters, tag_ids: tagIds }
        : { entity_type: 'company' as const, ids: Array.from(selectedIds), tag_ids: tagIds }
      const result = await bulkAddTags.mutateAsync(payload)
      toast(`Tagged ${result.affected} compan${result.affected !== 1 ? 'ies' : 'y'} (${result.new_assignments} new)`, 'success')
      setShowTagPicker(false)
      handleDeselectAll()
    } catch {
      toast('Failed to add tags', 'error')
    }
  }, [selectionMode, activeFilters, selectedIds, bulkAddTags, toast, handleDeselectAll])

  const selectionCount = selectionMode === 'all-matching'
    ? (matchingCount.data?.count ?? total)
    : selectedIds.size

  // Filter columns by visibility + action column
  const visibleSet = new Set(visibleKeys)
  const deleteActionColumn = useMemo(() => ({
    key: '_actions',
    label: '',
    width: '40px',
    minWidth: '40px',
    shrink: false,
    render: (c: CompanyListItem) => (
      <DeleteActionCell
        entityType="company"
        entityId={c.id}
        entityName={c.name || 'this company'}
        onDelete={handleInlineDelete}
        isDeleting={deleteCompany.isPending}
      />
    ),
  }), [handleInlineDelete, deleteCompany.isPending])

  const columns = useMemo(
    () => [...COMPANY_COLUMNS.filter((c) => visibleSet.has(c.key)), deleteActionColumn],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [visibleKeys, deleteActionColumn],
  )

  const facets = countsData?.facets

  // Build filter groups for sidebar
  const filterGroups: FilterGroup[] = useMemo(() => [
    {
      key: 'enrichment_stage',
      label: 'Stage',
      options: buildMultiOptions(ENRICHMENT_STAGE_DISPLAY, facets?.enrichment_stage),
      selected: getMulti('enrichment_stage').values,
      exclude: getMulti('enrichment_stage').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('enrichment_stage', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('enrichment_stage'); handleDeselectAll() },
    },
    {
      key: 'tier',
      label: 'Tier',
      options: buildMultiOptions(TIER_DISPLAY, facets?.tier),
      selected: getMulti('tier').values,
      exclude: getMulti('tier').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('tier', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('tier'); handleDeselectAll() },
    },
    {
      key: 'industry',
      label: 'Industry',
      options: buildMultiOptions(INDUSTRY_DISPLAY, facets?.industry),
      selected: getMulti('industry').values,
      exclude: getMulti('industry').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('industry', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('industry'); handleDeselectAll() },
    },
    {
      key: 'company_size',
      label: 'Company Size',
      options: buildMultiOptions(COMPANY_SIZE_DISPLAY, facets?.company_size),
      selected: getMulti('company_size').values,
      exclude: getMulti('company_size').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('company_size', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('company_size'); handleDeselectAll() },
    },
    {
      key: 'geo_region',
      label: 'Region',
      options: buildMultiOptions(GEO_REGION_DISPLAY, facets?.geo_region),
      selected: getMulti('geo_region').values,
      exclude: getMulti('geo_region').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('geo_region', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('geo_region'); handleDeselectAll() },
    },
    {
      key: 'revenue_range',
      label: 'Revenue',
      options: buildMultiOptions(REVENUE_RANGE_DISPLAY, facets?.revenue_range),
      selected: getMulti('revenue_range').values,
      exclude: getMulti('revenue_range').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('revenue_range', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('revenue_range'); handleDeselectAll() },
    },
    {
      // BL-1108: filter by market-facing organization type (migration 068).
      // No facet counts yet — facet endpoint backfill is out of scope for this phase.
      key: 'organization_type',
      label: 'Org Type',
      options: buildMultiOptions(ORGANIZATION_TYPE_DISPLAY),
      selected: getMulti('organization_type').values,
      exclude: getMulti('organization_type').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('organization_type', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('organization_type'); handleDeselectAll() },
    },
  ], [facets, getMulti, setMultiFilter, toggleExclude, handleDeselectAll])

  // Sidebar header slot: simple selects for tag, owner
  const headerSlot = (
    <div className="space-y-2">
      <SidebarSelect
        label="Tag"
        value={(advFilters.tag_name as string) || ''}
        options={(tagsData?.tags ?? []).map((b) => ({ value: b.name, label: b.name }))}
        onChange={(v) => handleFilterChange('tag_name', v)}
      />
      <SidebarSelect
        label="Owner"
        value={(advFilters.owner_name as string) || ''}
        options={(tagsData?.owners ?? []).map((o) => ({ value: o.name, label: o.name }))}
        onChange={(v) => handleFilterChange('owner_name', v)}
      />
    </div>
  )

  return (
    <div className="flex h-full min-h-0">
      {/* Sidebar */}
      <FilterSidebar
        groups={filterGroups}
        activeFilterCount={activeFilterCount}
        onClearAll={() => { clearAll(); handleDeselectAll() }}
        search={(advFilters.search as string) || ''}
        onSearchChange={(v) => handleFilterChange('search', v)}
        headerSlot={headerSlot}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      {/* Main content */}
      <div className="flex-1 min-w-0 flex flex-col h-full min-h-0 px-3 py-2">
        {/* Top bar: result count + actions */}
        <div className="flex items-center gap-2 mb-2">
          <span className="text-sm text-text-muted">
            {total.toLocaleString()} compan{total !== 1 ? 'ies' : 'y'}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowCreateCompany(true)}
              className="px-2.5 py-1.5 text-xs rounded-md border border-accent bg-accent/10 text-accent hover:bg-accent/20 transition-colors flex items-center gap-1.5"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M7 2v10M2 7h10" />
              </svg>
              New Company
            </button>
            <button
              type="button"
              onClick={shareView}
              className="px-2.5 py-1.5 text-xs rounded-md border border-border-solid bg-surface-alt text-text-muted hover:text-text hover:border-accent transition-colors flex items-center gap-1.5"
              title="Copy a link that shares your current columns, filters, and sort with your team"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                <circle cx="3" cy="7" r="1.5" />
                <circle cx="11" cy="3" r="1.5" />
                <circle cx="11" cy="11" r="1.5" />
                <path d="M4.5 6.2l5 -2.4M4.5 7.8l5 2.4" />
              </svg>
              Share View
            </button>
            {namespace && (
              <a
                href={`/${namespace}/enrich`}
                className="text-xs text-accent-cyan hover:underline"
              >
                Enrich Selection
              </a>
            )}
            <ColumnPicker
              allColumns={COMPANY_COLUMNS}
              visibleKeys={visibleKeys}
              onChange={setVisibleKeys}
              onReset={resetColumns}
              alwaysVisible={COMPANY_ALWAYS_VISIBLE}
            />
          </div>
        </div>

        <DataTable
          columns={columns}
          data={allCompanies}
          sort={{ field: sortField, dir: sortDir }}
          onSort={handleSort}
          onLoadMore={() => fetchNextPage()}
          hasMore={hasNextPage}
          isLoading={isLoading || isFetchingNextPage}
          emptyText="No companies match your filters."
          selectable
          selectedIds={selectedIds}
          onSelectionChange={handleSelectionChange}
          totalMatching={total}
          onCellEdit={(item, field, value) => inlineEdit.save(item.id, field, value)}
          cellStates={inlineEdit.cellStates}
        />
      </div>

      <SelectionActionBar
        count={selectionCount}
        isAllMatching={selectionMode === 'all-matching'}
        totalMatching={selectionMode === 'all-matching' ? (matchingCount.data?.count ?? total) : undefined}
        actions={[
          {
            label: 'Add Tags',
            icon: <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M7.5 1.5h4a1 1 0 0 1 1 1v4L6.5 12.5l-5-5L7.5 1.5z" /><circle cx="10" cy="4" r="0.5" fill="currentColor" /></svg>,
            onClick: () => setShowTagPicker(true),
            loading: bulkAddTags.isPending,
          },
          {
            label: 'Enrich Selected',
            icon: <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M5.5 1v4.5H3L7 10l4-4.5H8.5V1h-3z" /><path d="M2 12h10" /></svg>,
            onClick: () => {
              if (selectionMode === 'all-matching') {
                const encoded = btoa(JSON.stringify(activeFilters))
                navigate(`/${namespace}/enrich?entity_type=company&filters=${encoded}`)
              } else {
                const ids = Array.from(selectedIds)
                if (ids.length > 100) {
                  const key = `sess_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
                  sessionStorage.setItem(`enrich_selection_${key}`, JSON.stringify({
                    entity_type: 'company',
                    ids,
                  }))
                  navigate(`/${namespace}/enrich?selection=${key}`)
                } else {
                  navigate(`/${namespace}/enrich?companies=${ids.join(',')}`)
                }
              }
            },
          },
          {
            label: 'Delete',
            icon: <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M2.5 4h9M5 4V2.5h4V4M3.5 4v7.5a1 1 0 0 0 1 1h5a1 1 0 0 0 1-1V4M5.5 6.5v3M8.5 6.5v3" /></svg>,
            onClick: () => setShowDeleteConfirm(true),
            loading: bulkDelete.isPending,
            destructive: true,
          },
        ]}
        onDeselectAll={handleDeselectAll}
      />

      {showTagPicker && (
        <TagPicker
          onConfirm={handleAddTags}
          onClose={() => setShowTagPicker(false)}
          isLoading={bulkAddTags.isPending}
        />
      )}

      {/* Confirm Delete modal */}
      {showDeleteConfirm && (
        <ConfirmDeleteModal
          entityType="company"
          count={selectionCount}
          isAllMatching={selectionMode === 'all-matching'}
          onConfirm={handleBulkDelete}
          onClose={() => setShowDeleteConfirm(false)}
          isLoading={bulkDelete.isPending}
        />
      )}

      {/* Create Company modal */}
      {showCreateCompany && (
        <CreateCompanyModal
          onClose={() => setShowCreateCompany(false)}
          onSuccess={() => {
            setShowCreateCompany(false)
            toast('Company created', 'success')
          }}
        />
      )}
    </div>
  )
}

/* ── Sidebar simple select ──────────────────────────────── */

function SidebarSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (v: string) => void
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[11px] text-text-dim w-16 flex-shrink-0">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="flex-1 min-w-0 px-1.5 py-1 text-[11px] bg-surface-alt border border-border-solid rounded text-text focus:outline-none focus:border-accent"
      >
        <option value="">All</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}
