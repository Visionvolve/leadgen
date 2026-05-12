import { useState, useMemo, useCallback, useEffect } from 'react'
import { useInlineEdit } from '../../hooks/useInlineEdit'
import { useParams, useNavigate } from 'react-router'
import { withRev } from '../../lib/revision'
import { useContacts, useDeleteContact, type ContactFilters, type ContactListItem } from '../../api/queries/useContacts'
import { useTags } from '../../api/queries/useTags'
import { useBulkAddTags, useBulkAssignCampaign, useBulkDelete, useContactsMatchingCount } from '../../api/queries/useBulkActions'
import { useLocalStorage } from '../../hooks/useLocalStorage'
import { useAdvancedFilters, CONTACT_MULTI_KEYS } from '../../hooks/useAdvancedFilters'
import { useFilterCounts } from '../../hooks/useFilterCounts'
import { useColumnVisibility } from '../../hooks/useColumnVisibility'
import { useChatFilterSync } from '../../hooks/useChatFilterSync'
import { useOnboardingStatus, shouldShowSignpost } from '../../hooks/useOnboarding'
import { DataTable, type SelectionMode } from '../../components/ui/DataTable'
import { FilterSidebar, type FilterGroup } from '../../components/ui/FilterSidebar'
import { ColumnPicker } from '../../components/ui/ColumnPicker'
import { SelectionActionBar } from '../../components/ui/SelectionActionBar'
import { TagPicker } from '../../components/ui/TagPicker'
import { AddToCampaignModal } from '../../components/ui/AddToCampaignModal'
import { ConfirmDeleteModal } from '../../components/ui/ConfirmDeleteModal'
import { CreateContactModal } from '../../components/ui/CreateContactModal'
import { ChatFilterSyncBar } from '../../components/ui/ChatFilterSyncBar'
import { DeleteActionCell } from '../../components/ui/DeleteActionCell'
import { ContactsEmptyState } from '../../components/onboarding/SmartEmptyState'
import { EntrySignpost } from '../../components/onboarding/EntrySignpost'
import { useToast } from '../../components/ui/Toast'
import { useScrollRestore } from '../../hooks/useScrollRestore'
import { useCampaigns } from '../../api/queries/useCampaigns'
import { useCampaignColumns } from '../../hooks/useCampaignColumns'
import { useShareView } from '../../hooks/useShareView'
import { useCampaignMemberships } from '../../hooks/useCampaignMemberships'
import { buildCampaignColumns } from '../../config/campaignColumnBuilder'
import { CONTACT_COLUMNS, CONTACT_ALWAYS_VISIBLE } from '../../config/contactColumns'
import {
  ICP_FIT_DISPLAY,
  MESSAGE_STATUS_DISPLAY,
  TIER_DISPLAY,
  INDUSTRY_DISPLAY,
  COMPANY_SIZE_DISPLAY,
  GEO_REGION_DISPLAY,
  REVENUE_RANGE_DISPLAY,
  SENIORITY_DISPLAY,
  DEPARTMENT_DISPLAY,
  LINKEDIN_ACTIVITY_DISPLAY,
  filterOptions,
} from '../../lib/display'

/** Build FilterGroup options from a display map + optional facet counts */
function buildGroupOptions(
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

/** Build FilterGroup options directly from facet data (no display map — values are already human-readable) */
function buildFacetOptions(facets?: { value: string; count: number }[]) {
  if (!facets) return []
  return facets.map((f) => ({
    value: f.value,
    label: f.value,
    count: f.count,
  }))
}

export function ContactsPage() {
  const { namespace } = useParams<{ namespace: string }>()
  const navigate = useNavigate()
  const { toast } = useToast()

  // Sidebar collapse state (persisted)
  const [sidebarCollapsed, setSidebarCollapsed] = useLocalStorage('filters_sidebar_collapsed', false)

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
  } = useAdvancedFilters('ct_adv_filters', CONTACT_MULTI_KEYS)

  const [sortField, setSortField] = useLocalStorage('ct_sort_field', 'last_name')
  const [sortDir, setSortDir] = useLocalStorage<'asc' | 'desc'>('ct_sort_dir', 'asc')

  // Column visibility
  const [visibleKeys, setVisibleKeys, resetColumns] = useColumnVisibility(
    'ct_visible_cols',
    CONTACT_COLUMNS,
  )

  // Campaign columns
  const { data: campaignsData } = useCampaigns()
  const { campaignColumnIds, toggle: toggleCampaignColumn, set: setCampaignColumnIds } = useCampaignColumns(namespace)
  const { membershipMap, toggle: toggleMembership } = useCampaignMemberships(campaignColumnIds)
  const activeCampaigns = useMemo(
    () => (campaignsData?.campaigns ?? []).filter((c) => campaignColumnIds.includes(c.id)),
    [campaignsData, campaignColumnIds],
  )
  const campaignCols = useMemo(
    () => buildCampaignColumns(activeCampaigns, membershipMap, toggleMembership),
    [activeCampaigns, membershipMap, toggleMembership],
  )

  // Share view
  const { shareView } = useShareView({
    visibleKeys,
    campaignColumnIds,
    filters: advFilters,
    sortField,
    sortDir,
    setVisibleKeys,
    setCampaignColumnIds,
    replaceAllFilters: replaceAll,
    setSortField,
    setSortDir,
    toast,
  })

  // Selection state
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [selectionMode, setSelectionMode] = useState<SelectionMode>('explicit')
  const [showTagPicker, setShowTagPicker] = useState(false)
  const [showCampaignModal, setShowCampaignModal] = useState(false)
  const [showCreateContact, setShowCreateContact] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  // Inline editing
  const inlineEdit = useInlineEdit('contact')

  const { data: tagsData } = useTags()
  const { data: onboardingStatus } = useOnboardingStatus()
  const bulkAddTags = useBulkAddTags()
  const bulkAssignCampaign = useBulkAssignCampaign()
  const bulkDelete = useBulkDelete()
  const deleteContact = useDeleteContact()
  const matchingCount = useContactsMatchingCount()

  // Chat filter sync
  const { pending: chatFilterPending, dismiss: dismissChatFilter } = useChatFilterSync()

  // Scroll position restore (saves before navigating to detail, restores on mount)
  const { saveScrollPosition } = useScrollRestore('contacts_scroll')

  // Listen for custom navigation events from column renderers
  useEffect(() => {
    const handler = (e: Event) => {
      const path = (e as CustomEvent<string>).detail
      if (path) {
        saveScrollPosition()
        navigate(withRev(path), { state: { origin: withRev(`/${namespace}/contacts`) } })
      }
    }
    window.addEventListener('leadgen:navigate', handler)
    return () => window.removeEventListener('leadgen:navigate', handler)
  }, [navigate, namespace, saveScrollPosition])

  // Build ContactFilters from advanced state + sort
  const filters: ContactFilters = useMemo(() => ({
    ...toQueryParams(),
    sort: sortField,
    sort_dir: sortDir,
  }), [toQueryParams, sortField, sortDir])

  // Active filters for bulk actions (simple key-value pairs for existing API)
  const activeFilters = useMemo(() => {
    const params = toQueryParams()
    delete params.sort
    delete params.sort_dir
    return params
  }, [toQueryParams])

  // Filter counts for faceted options
  const countsPayload = useMemo(() => toCountsPayload(), [toCountsPayload])
  const { data: countsData } = useFilterCounts(countsPayload, '/contacts/filter-counts')

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
  } = useContacts(filters)

  const allContacts = useMemo(
    () => data?.pages.flatMap((p) => p.contacts) ?? [],
    [data],
  )
  const total = data?.pages[0]?.total ?? 0

  const handleFilterChange = useCallback((key: string, value: string) => {
    setSimpleFilter(key, value)
    setSelectedIds(new Set())
    setSelectionMode('explicit')
  }, [setSimpleFilter])

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

  const handleAddTags = useCallback(async (tagIds: string[]) => {
    try {
      const payload = selectionMode === 'all-matching'
        ? { entity_type: 'contact' as const, filters: activeFilters, tag_ids: tagIds }
        : { entity_type: 'contact' as const, ids: Array.from(selectedIds), tag_ids: tagIds }
      const result = await bulkAddTags.mutateAsync(payload)
      toast(`Tagged ${result.affected} contact${result.affected !== 1 ? 's' : ''} (${result.new_assignments} new)`, 'success')
      setShowTagPicker(false)
      handleDeselectAll()
    } catch {
      toast('Failed to add tags', 'error')
    }
  }, [selectionMode, activeFilters, selectedIds, bulkAddTags, toast, handleDeselectAll])

  const handleBulkDelete = useCallback(async () => {
    try {
      const payload = selectionMode === 'all-matching'
        ? { entity_type: 'contact' as const, filters: activeFilters }
        : { entity_type: 'contact' as const, ids: Array.from(selectedIds) }
      const result = await bulkDelete.mutateAsync(payload)
      toast(`Deleted ${result.deleted} contact${result.deleted !== 1 ? 's' : ''}`, 'success')
      setShowDeleteConfirm(false)
      handleDeselectAll()
    } catch {
      toast('Failed to delete contacts', 'error')
    }
  }, [selectionMode, activeFilters, selectedIds, bulkDelete, toast, handleDeselectAll])

  const handleAssignCampaign = useCallback(async (campaignId: string) => {
    try {
      const payload = selectionMode === 'all-matching'
        ? { entity_type: 'contact' as const, filters: activeFilters, campaign_id: campaignId }
        : { entity_type: 'contact' as const, ids: Array.from(selectedIds), campaign_id: campaignId }
      const result = await bulkAssignCampaign.mutateAsync(payload)
      toast(`Assigned ${result.affected} contact${result.affected !== 1 ? 's' : ''} to campaign`, 'success')
      setShowCampaignModal(false)
      handleDeselectAll()
    } catch {
      toast('Failed to assign to campaign', 'error')
    }
  }, [selectionMode, activeFilters, selectedIds, bulkAssignCampaign, toast, handleDeselectAll])

  // Inline single-record delete
  const handleInlineDelete = useCallback(async (id: string) => {
    try {
      await deleteContact.mutateAsync(id)
      toast('Contact deleted', 'success')
    } catch {
      toast('Failed to delete contact', 'error')
    }
  }, [deleteContact, toast])

  // Accept chat filter suggestions
  const handleAcceptChatFilters = useCallback((chatFilters: Record<string, string | string[]>) => {
    for (const [key, value] of Object.entries(chatFilters)) {
      if (CONTACT_MULTI_KEYS.includes(key as typeof CONTACT_MULTI_KEYS[number])) {
        const values = Array.isArray(value) ? value : [value]
        setMultiFilter(key, values)
      } else if (typeof value === 'string') {
        setSimpleFilter(key, value)
      }
    }
    setSelectedIds(new Set())
    setSelectionMode('explicit')
    dismissChatFilter()
  }, [setMultiFilter, setSimpleFilter, dismissChatFilter])

  const selectionCount = selectionMode === 'all-matching'
    ? (matchingCount.data?.count ?? total)
    : selectedIds.size

  // Filter columns by visibility + append campaign columns + action column
  const visibleSet = new Set(visibleKeys)
  const deleteActionColumn = useMemo(() => ({
    key: '_actions',
    label: '',
    width: '40px',
    minWidth: '40px',
    shrink: false,
    render: (c: ContactListItem) => (
      <DeleteActionCell
        entityType="contact"
        entityId={c.id}
        entityName={c.full_name || 'this contact'}
        onDelete={handleInlineDelete}
        isDeleting={deleteContact.isPending}
      />
    ),
  }), [handleInlineDelete, deleteContact.isPending])

  const columns = useMemo(
    () => [...CONTACT_COLUMNS.filter((c) => visibleSet.has(c.key)), ...campaignCols, deleteActionColumn],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [visibleKeys, campaignCols, deleteActionColumn],
  )

  const facets = countsData?.facets

  // Build filter groups for sidebar
  const filterGroups: FilterGroup[] = useMemo(() => [
    {
      key: 'company_tier',
      label: 'Company Tier',
      options: buildGroupOptions(TIER_DISPLAY, facets?.company_tier),
      selected: getMulti('company_tier').values,
      exclude: getMulti('company_tier').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('company_tier', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('company_tier'); handleDeselectAll() },
    },
    {
      key: 'industry',
      label: 'Industry',
      options: buildGroupOptions(INDUSTRY_DISPLAY, facets?.industry),
      selected: getMulti('industry').values,
      exclude: getMulti('industry').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('industry', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('industry'); handleDeselectAll() },
    },
    {
      key: 'company_size',
      label: 'Company Size',
      options: buildGroupOptions(COMPANY_SIZE_DISPLAY, facets?.company_size),
      selected: getMulti('company_size').values,
      exclude: getMulti('company_size').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('company_size', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('company_size'); handleDeselectAll() },
    },
    {
      key: 'geo_region',
      label: 'Region',
      options: buildGroupOptions(GEO_REGION_DISPLAY, facets?.geo_region),
      selected: getMulti('geo_region').values,
      exclude: getMulti('geo_region').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('geo_region', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('geo_region'); handleDeselectAll() },
    },
    {
      key: 'revenue_range',
      label: 'Revenue',
      options: buildGroupOptions(REVENUE_RANGE_DISPLAY, facets?.revenue_range),
      selected: getMulti('revenue_range').values,
      exclude: getMulti('revenue_range').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('revenue_range', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('revenue_range'); handleDeselectAll() },
    },
    {
      key: 'seniority_level',
      label: 'Seniority',
      options: buildGroupOptions(SENIORITY_DISPLAY, facets?.seniority_level),
      selected: getMulti('seniority_level').values,
      exclude: getMulti('seniority_level').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('seniority_level', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('seniority_level'); handleDeselectAll() },
    },
    {
      key: 'department',
      label: 'Department',
      options: buildGroupOptions(DEPARTMENT_DISPLAY, facets?.department),
      selected: getMulti('department').values,
      exclude: getMulti('department').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('department', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('department'); handleDeselectAll() },
    },
    {
      key: 'linkedin_activity',
      label: 'LinkedIn Activity',
      options: buildGroupOptions(LINKEDIN_ACTIVITY_DISPLAY, facets?.linkedin_activity),
      selected: getMulti('linkedin_activity').values,
      exclude: getMulti('linkedin_activity').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('linkedin_activity', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('linkedin_activity'); handleDeselectAll() },
      searchable: false,
    },
    {
      key: 'skills',
      label: 'Skills / Expertise',
      options: buildFacetOptions(facets?.skills),
      selected: getMulti('skills').values,
      exclude: getMulti('skills').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('skills', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('skills'); handleDeselectAll() },
    },
    {
      key: 'interests',
      label: 'Interests / Technology',
      options: buildFacetOptions(facets?.interests),
      selected: getMulti('interests').values,
      exclude: getMulti('interests').exclude,
      onSelectionChange: (v: string[]) => { setMultiFilter('interests', v); handleDeselectAll() },
      onExcludeToggle: () => { toggleExclude('interests'); handleDeselectAll() },
    },
  ], [facets, getMulti, setMultiFilter, toggleExclude, handleDeselectAll])

  // Sidebar header slot: simple selects for ICP fit, message status, tag, owner
  const headerSlot = (
    <div className="space-y-2">
      <SidebarSelect
        label="ICP Fit"
        value={(advFilters.icp_fit as string) || ''}
        options={filterOptions(ICP_FIT_DISPLAY)}
        onChange={(v) => handleFilterChange('icp_fit', v)}
      />
      <SidebarSelect
        label="Msg Status"
        value={(advFilters.message_status as string) || ''}
        options={filterOptions(MESSAGE_STATUS_DISPLAY)}
        onChange={(v) => handleFilterChange('message_status', v)}
      />
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

  // Show EntrySignpost when namespace is fully empty (no contacts, no strategy)
  // This renders without the filter sidebar, matching the Playbook page behavior
  if (shouldShowSignpost(onboardingStatus)) {
    return <EntrySignpost />
  }

  // Show context-aware empty state when namespace has contacts = 0 but has strategy
  const namespaceHasNoContacts =
    onboardingStatus !== undefined && onboardingStatus.contact_count === 0

  if (namespaceHasNoContacts && !isLoading) {
    return <ContactsEmptyState />
  }

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
        {/* Top bar: result count + layout toggle + column picker */}
        <div className="flex items-center gap-2 mb-2">
          <span className="text-sm text-text-muted">
            {total.toLocaleString()} contact{total !== 1 ? 's' : ''}
          </span>
          <div className="ml-auto flex items-center gap-2">
            {/* New Contact button */}
            <button
              type="button"
              onClick={() => setShowCreateContact(true)}
              className="px-2.5 py-1.5 text-xs rounded-md border border-accent bg-accent/10 text-accent hover:bg-accent/20 transition-colors flex items-center gap-1.5"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M7 2v10M2 7h10" />
              </svg>
              New Contact
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
            <ColumnPicker
              allColumns={CONTACT_COLUMNS}
              visibleKeys={visibleKeys}
              onChange={setVisibleKeys}
              onReset={resetColumns}
              alwaysVisible={CONTACT_ALWAYS_VISIBLE}
              campaigns={(campaignsData?.campaigns ?? []).map((c) => ({ id: c.id, name: c.name }))}
              activeCampaignIds={campaignColumnIds}
              onToggleCampaign={toggleCampaignColumn}
            />
          </div>
        </div>

        {/* Chat filter sync bar */}
        <ChatFilterSyncBar
          pending={chatFilterPending}
          onAccept={handleAcceptChatFilters}
          onDismiss={dismissChatFilter}
        />

        {/* Data table */}
        <DataTable
          columns={columns}
          data={allContacts}
          sort={{ field: sortField, dir: sortDir }}
          onSort={handleSort}
          onLoadMore={() => fetchNextPage()}
          hasMore={hasNextPage}
          isLoading={isLoading || isFetchingNextPage}
          emptyText="No contacts match your filters."
          selectable
          selectedIds={selectedIds}
          onSelectionChange={handleSelectionChange}
          totalMatching={total}
          onCellEdit={(item, field, value) => inlineEdit.save(item.id, field, value)}
          cellStates={inlineEdit.cellStates}
        />
      </div>

      {/* Selection action bar */}
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
            label: 'Add to Campaign',
            icon: <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M2 3.5h10M2 7h10M2 10.5h6" /></svg>,
            onClick: () => setShowCampaignModal(true),
            loading: bulkAssignCampaign.isPending,
          },
          {
            label: 'Enrich Selected',
            icon: <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M5.5 1v4.5H3L7 10l4-4.5H8.5V1h-3z" /><path d="M2 12h10" /></svg>,
            onClick: () => {
              if (selectionMode === 'all-matching') {
                const encoded = btoa(JSON.stringify(activeFilters))
                navigate(`/${namespace}/enrich?entity_type=contact&filters=${encoded}`)
              } else {
                const ids = Array.from(selectedIds)
                if (ids.length > 100) {
                  const key = `sess_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
                  sessionStorage.setItem(`enrich_selection_${key}`, JSON.stringify({
                    entity_type: 'contact',
                    ids,
                  }))
                  navigate(`/${namespace}/enrich?selection=${key}`)
                } else {
                  navigate(`/${namespace}/enrich?contacts=${ids.join(',')}`)
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

      {/* Tag picker modal */}
      {showTagPicker && (
        <TagPicker
          onConfirm={handleAddTags}
          onClose={() => setShowTagPicker(false)}
          isLoading={bulkAddTags.isPending}
        />
      )}

      {/* Add to Campaign modal */}
      {showCampaignModal && (
        <AddToCampaignModal
          selectedCount={selectionCount}
          selectedIds={Array.from(selectedIds)}
          onConfirm={handleAssignCampaign}
          onClose={() => setShowCampaignModal(false)}
          isLoading={bulkAssignCampaign.isPending}
        />
      )}

      {/* Confirm Delete modal */}
      {showDeleteConfirm && (
        <ConfirmDeleteModal
          entityType="contact"
          count={selectionCount}
          isAllMatching={selectionMode === 'all-matching'}
          onConfirm={handleBulkDelete}
          onClose={() => setShowDeleteConfirm(false)}
          isLoading={bulkDelete.isPending}
        />
      )}

      {/* Create Contact modal */}
      {showCreateContact && (
        <CreateContactModal
          onClose={() => setShowCreateContact(false)}
          onSuccess={() => {
            setShowCreateContact(false)
            toast('Contact created', 'success')
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
