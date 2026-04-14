import { useState, useMemo, useRef, useEffect, type ReactNode } from 'react'

/* ── Types ──────────────────────────────────────────────── */

interface FacetOption {
  value: string
  label: string
  count?: number
}

export interface FilterGroup {
  key: string
  label: string
  options: FacetOption[]
  selected: string[]
  exclude: boolean
  onSelectionChange: (values: string[]) => void
  onExcludeToggle: () => void
  searchable?: boolean
}

interface FilterSidebarProps {
  groups: FilterGroup[]
  activeFilterCount: number
  onClearAll: () => void
  /** Search input value + handler (rendered at top of sidebar) */
  search: string
  onSearchChange: (v: string) => void
  /** Optional extra content above filters (e.g. owner/tag selects) */
  headerSlot?: ReactNode
  /** Whether the sidebar is collapsed */
  collapsed?: boolean
  /** Callback to toggle collapsed state */
  onToggleCollapse?: () => void
}

/* ── Component ──────────────────────────────────────────── */

export function FilterSidebar({
  groups,
  activeFilterCount,
  onClearAll,
  search,
  onSearchChange,
  headerSlot,
  collapsed = false,
  onToggleCollapse,
}: FilterSidebarProps) {
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <>
      {/* Mobile toggle button */}
      <button
        type="button"
        onClick={() => setMobileOpen(true)}
        className="md:hidden fixed bottom-20 right-4 z-30 flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-accent text-white shadow-lg border-none cursor-pointer"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M1.5 3.5h11M3.5 7h7M5.5 10.5h3" />
        </svg>
        Filters
        {activeFilterCount > 0 && (
          <span className="inline-flex items-center justify-center w-4 h-4 text-[10px] font-bold rounded-full bg-white text-accent">
            {activeFilterCount}
          </span>
        )}
      </button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="md:hidden fixed inset-0 z-40 bg-black/50"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar wrapper — handles collapse transition */}
      <div
        className="hidden md:flex flex-shrink-0 transition-[width] duration-250 ease-in-out overflow-hidden"
        style={{ width: collapsed ? '36px' : '280px' }}
      >
        {/* Collapsed strip — small toggle button */}
        {collapsed && (
          <button
            type="button"
            onClick={onToggleCollapse}
            className="w-[36px] h-full flex flex-col items-center pt-3 gap-2 bg-surface border-r border-border-solid cursor-pointer border-l-0 border-t-0 border-b-0 hover:bg-surface-alt transition-colors"
            title="Show filters"
          >
            {/* Chevron pointing right */}
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-text-muted">
              <path d="M5 2.5l4.5 4.5L5 11.5" />
            </svg>
            {activeFilterCount > 0 && (
              <span className="inline-flex items-center justify-center w-5 h-5 text-[10px] font-bold rounded-full bg-accent-cyan/20 text-accent-cyan">
                {activeFilterCount}
              </span>
            )}
            {/* Vertical "Filters" text */}
            <span
              className="text-[10px] text-text-dim uppercase tracking-widest"
              style={{ writingMode: 'vertical-rl', textOrientation: 'mixed' }}
            >
              Filters
            </span>
          </button>
        )}

        {/* Sidebar panel — fully hidden when collapsed (not just clipped) */}
        <aside
          className={`
            w-[280px] flex-shrink-0 bg-surface border-r border-border-solid overflow-y-auto
            md:relative
            ${mobileOpen
              ? 'fixed inset-y-0 left-0 z-50 block shadow-xl'
              : collapsed ? 'hidden' : 'hidden md:block'
            }
          `}
        >
          {/* Header */}
          <div className="sticky top-0 z-10 bg-surface px-3 pt-3 pb-2 border-b border-border-solid">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-text-muted uppercase tracking-wider">Filters</span>
              <div className="flex items-center gap-2">
                {activeFilterCount > 0 && (
                  <button
                    type="button"
                    onClick={onClearAll}
                    className="text-[11px] text-text-muted hover:text-error transition-colors bg-transparent border-none cursor-pointer p-0"
                  >
                    Clear all
                  </button>
                )}
                {/* Collapse toggle (desktop) */}
                {onToggleCollapse && (
                  <button
                    type="button"
                    onClick={onToggleCollapse}
                    className="hidden md:flex w-6 h-6 items-center justify-center rounded text-text-muted hover:text-text hover:bg-surface-alt bg-transparent border-none cursor-pointer transition-colors"
                    aria-label="Collapse filters"
                    title="Collapse filters"
                  >
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <path d="M9 2.5L4.5 7 9 11.5" />
                    </svg>
                  </button>
                )}
                {/* Mobile close */}
                <button
                  type="button"
                  onClick={() => setMobileOpen(false)}
                  className="md:hidden w-6 h-6 flex items-center justify-center rounded text-text-muted hover:text-text bg-transparent border-none cursor-pointer"
                  aria-label="Close filters"
                >
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" />
                  </svg>
                </button>
              </div>
            </div>

            {/* Search */}
            <SearchInput value={search} onChange={onSearchChange} />
          </div>

          {/* Optional header slot (owner, tag selects) */}
          {headerSlot && (
            <div className="px-3 py-2 border-b border-border-solid">
              {headerSlot}
            </div>
          )}

          {/* Active filter pills */}
          <ActiveFilterPills groups={groups} />

          {/* Filter groups */}
          <div className="px-1 py-1">
            {groups.map((group) => (
              <FilterGroupSection key={group.key} group={group} />
            ))}
          </div>
        </aside>
      </div>
    </>
  )
}

/* ── Active filter pills ────────────────────────────────── */

function ActiveFilterPills({ groups }: { groups: FilterGroup[] }) {
  const active = groups.filter((g) => g.selected.length > 0)
  if (active.length === 0) return null

  return (
    <div className="flex flex-wrap gap-1 px-3 py-2 border-b border-border-solid">
      {active.map((g) =>
        g.selected.map((val) => {
          const opt = g.options.find((o) => o.value === val)
          return (
            <span
              key={`${g.key}-${val}`}
              className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[11px] rounded ${
                g.exclude
                  ? 'bg-warning/15 text-warning'
                  : 'bg-accent-cyan/15 text-accent-cyan'
              }`}
            >
              {g.exclude && <span className="text-[9px] font-bold">NOT</span>}
              {opt?.label ?? val}
              <button
                type="button"
                onClick={() => g.onSelectionChange(g.selected.filter((v) => v !== val))}
                className="opacity-70 hover:opacity-100 bg-transparent border-none cursor-pointer p-0 text-inherit text-[11px] leading-none"
              >
                x
              </button>
            </span>
          )
        }),
      )}
    </div>
  )
}

/* ── Collapsible filter group ───────────────────────────── */

function FilterGroupSection({ group }: { group: FilterGroup }) {
  const [collapsed, setCollapsed] = useState(false)
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    const sorted = [...group.options].sort((a, b) => (b.count ?? 0) - (a.count ?? 0))
    if (!search) return sorted
    const q = search.toLowerCase()
    return sorted.filter((o) => o.label.toLowerCase().includes(q))
  }, [group.options, search])

  const hasSelection = group.selected.length > 0

  return (
    <div className="border-b border-border/30">
      {/* Group header */}
      <button
        type="button"
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-text-muted hover:text-text bg-transparent border-none cursor-pointer transition-colors"
      >
        <span className="flex items-center gap-1.5">
          {group.label}
          {hasSelection && (
            <span className="inline-flex items-center justify-center w-4 h-4 text-[9px] font-bold rounded-full bg-accent-cyan/20 text-accent-cyan">
              {group.selected.length}
            </span>
          )}
        </span>
        <svg
          width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5"
          className={`transition-transform ${collapsed ? '' : 'rotate-180'}`}
        >
          <path d="M2 3.5l3 3 3-3" />
        </svg>
      </button>

      {/* Collapsible content */}
      {!collapsed && (
        <div className="px-2 pb-2">
          {/* Search within group (if many options) */}
          {group.searchable !== false && group.options.length > 6 && (
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={`Filter ${group.label.toLowerCase()}...`}
              className="w-full px-2 py-1 mb-1 text-[11px] bg-surface-alt border border-border-solid rounded text-text placeholder:text-text-dim outline-none focus:border-accent"
            />
          )}

          {/* Include/exclude toggle */}
          {hasSelection && (
            <div className="flex items-center gap-1 mb-1 px-1">
              <button
                type="button"
                onClick={group.onExcludeToggle}
                className="text-[10px] px-1.5 py-0.5 rounded bg-transparent border border-border-solid cursor-pointer transition-colors hover:border-accent"
                style={{ color: group.exclude ? 'var(--color-warning)' : 'var(--color-text-muted)' }}
              >
                {group.exclude ? 'Excluding' : 'Including'}
              </button>
            </div>
          )}

          {/* Options */}
          <div className="max-h-[200px] overflow-y-auto">
            {filtered.map((opt) => {
              const isSelected = group.selected.includes(opt.value)
              const isZero = opt.count === 0 && opt.count !== undefined
              return (
                <label
                  key={opt.value}
                  className={`flex items-center gap-2 px-1 py-1 rounded text-[12px] cursor-pointer transition-colors ${
                    isSelected ? 'bg-accent-cyan/8' : 'hover:bg-surface-alt'
                  } ${isZero ? 'opacity-40' : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => {
                      if (isSelected) {
                        group.onSelectionChange(group.selected.filter((v) => v !== opt.value))
                      } else {
                        group.onSelectionChange([...group.selected, opt.value])
                      }
                    }}
                    className="w-3.5 h-3.5 accent-accent-cyan flex-shrink-0 cursor-pointer"
                  />
                  <span className="flex-1 min-w-0 truncate text-text">{opt.label}</span>
                  {opt.count !== undefined && (
                    <span className="text-[11px] text-text-dim flex-shrink-0 tabular-nums">{opt.count}</span>
                  )}
                </label>
              )
            })}
            {filtered.length === 0 && (
              <p className="text-[11px] text-text-dim px-1 py-2 text-center">No options match</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Search input with debounce ─────────────────────────── */

function SearchInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [local, setLocal] = useState(value)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    setLocal(value)
  }, [value])

  const handleChange = (v: string) => {
    setLocal(v)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => onChange(v), 400)
  }

  useEffect(() => () => clearTimeout(timer.current), [])

  return (
    <div className="relative">
      <svg
        width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"
        className="absolute left-2 top-1/2 -translate-y-1/2 text-text-dim"
      >
        <circle cx="7" cy="7" r="4.5" />
        <path d="M10.5 10.5L14 14" />
      </svg>
      <input
        type="text"
        value={local}
        onChange={(e) => handleChange(e.target.value)}
        placeholder="Search name, email, title..."
        className="w-full pl-7 pr-2 py-1.5 text-xs bg-surface-alt border border-border-solid rounded-md text-text placeholder:text-text-dim focus:outline-none focus:border-accent"
      />
    </div>
  )
}
