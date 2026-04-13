import { useRef, useState, useEffect, useCallback, type ReactNode } from 'react'
import { InlineEditCell } from './InlineEditCell'
import type { ColumnDef } from '../../config/columns'

const ROW_HEIGHT = 41
const BUFFER = 20

export interface Column<T> {
  key: string
  label: string
  sortKey?: string
  render?: (item: T) => ReactNode
  width?: string
  minWidth?: string
  shrink?: boolean
}

export type SelectionMode = 'explicit' | 'all-matching'

interface DataTableProps<T> {
  columns: Column<T>[]
  data: T[]
  sort?: { field: string; dir: 'asc' | 'desc' }
  onSort?: (field: string, dir: 'asc' | 'desc') => void
  onRowClick?: (item: T) => void
  onLoadMore?: () => void
  hasMore?: boolean
  isLoading?: boolean
  emptyText?: string
  // Selection props
  selectable?: boolean
  selectedIds?: Set<string>
  onSelectionChange?: (ids: Set<string>, mode: SelectionMode) => void
  totalMatching?: number
  // Inline editing props
  onCellEdit?: (item: T, field: string, value: string) => Promise<void>
  cellStates?: Map<string, string>
}

export function DataTable<T extends { id?: string }>({
  columns,
  data,
  sort,
  onSort,
  onRowClick,
  onLoadMore,
  hasMore,
  isLoading,
  emptyText = 'No results match your filters.',
  selectable = false,
  selectedIds,
  onSelectionChange,
  totalMatching,
  onCellEdit,
  cellStates,
}: DataTableProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null)
  const sentinelRef = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [containerHeight, setContainerHeight] = useState(0)
  const lastClickedIndex = useRef<number | null>(null)
  const [selectionMode, setSelectionMode] = useState<SelectionMode>('explicit')

  const selected = selectedIds ?? new Set<string>()

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerHeight(entry.contentRect.height)
      }
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const handleScroll = useCallback(() => {
    if (containerRef.current) {
      setScrollTop(containerRef.current.scrollTop)
    }
  }, [])

  // Escape key clears selection
  useEffect(() => {
    if (!selectable || selected.size === 0) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && onSelectionChange) {
        onSelectionChange(new Set(), 'explicit')
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [selectable, selected.size, onSelectionChange])

  useEffect(() => {
    const el = sentinelRef.current
    if (!el || !onLoadMore || !hasMore) return
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !isLoading) {
          onLoadMore()
        }
      },
      { root: containerRef.current, rootMargin: '200px' },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [onLoadMore, hasMore, isLoading])

  const startIndex = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - BUFFER)
  const endIndex = Math.min(data.length, Math.ceil((scrollTop + containerHeight) / ROW_HEIGHT) + BUFFER)
  const visibleData = data.slice(startIndex, endIndex)
  const offsetY = startIndex * ROW_HEIGHT

  const handleSortClick = (col: Column<T>) => {
    if (!col.sortKey || !onSort) return
    const newDir = sort?.field === col.sortKey && sort.dir === 'asc' ? 'desc' : 'asc'
    onSort(col.sortKey, newDir)
  }

  // Selection handlers
  const toggleRow = useCallback((item: T, index: number, shiftKey: boolean) => {
    if (!selectable || !onSelectionChange) return
    const id = item.id
    if (!id) return

    const newSelected = new Set(selected)

    if (shiftKey && lastClickedIndex.current !== null) {
      // Range selection
      const start = Math.min(lastClickedIndex.current, index)
      const end = Math.max(lastClickedIndex.current, index)
      for (let i = start; i <= end; i++) {
        const rowId = data[i]?.id
        if (rowId) newSelected.add(rowId)
      }
    } else {
      // Single toggle
      if (newSelected.has(id)) {
        newSelected.delete(id)
      } else {
        newSelected.add(id)
      }
    }

    lastClickedIndex.current = index
    setSelectionMode('explicit')
    onSelectionChange(newSelected, 'explicit')
  }, [selectable, onSelectionChange, selected, data])

  const allLoadedSelected = selectable && data.length > 0 && data.every((item) => item.id && selected.has(item.id))
  const someSelected = selectable && selected.size > 0

  const toggleSelectAll = useCallback(() => {
    if (!selectable || !onSelectionChange) return
    if (allLoadedSelected) {
      // Deselect all
      onSelectionChange(new Set(), 'explicit')
      setSelectionMode('explicit')
    } else {
      // Select all loaded
      const newSelected = new Set<string>()
      for (const item of data) {
        if (item.id) newSelected.add(item.id)
      }
      onSelectionChange(newSelected, 'explicit')
      setSelectionMode('explicit')
    }
  }, [selectable, onSelectionChange, allLoadedSelected, data])

  const handleSelectAllMatching = useCallback(() => {
    if (!onSelectionChange) return
    // Keep current selection but switch mode to all-matching
    setSelectionMode('all-matching')
    onSelectionChange(selected, 'all-matching')
  }, [onSelectionChange, selected])

  // Determine header checkbox state
  const headerCheckState = !selectable ? 'hidden'
    : allLoadedSelected ? 'checked'
    : someSelected ? 'indeterminate'
    : 'unchecked'

  // Show "select all matching" banner?
  const showSelectAllBanner = selectable && allLoadedSelected && selectionMode !== 'all-matching'
    && totalMatching != null && totalMatching > data.length

  if (!isLoading && data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-text-dim">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" className="mb-3 opacity-50">
          <path d="M3 7h18M3 12h18M3 17h18" />
        </svg>
        <p className="text-sm">{emptyText}</p>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className="flex-1 min-h-0 overflow-auto border border-border-solid rounded-lg bg-surface scrollbar-thin"
    >
      {/* Select all matching banner */}
      {showSelectAllBanner && (
        <div className="sticky top-[37px] z-20 flex items-center justify-center gap-2 py-1.5 px-3 bg-accent/10 border-b border-accent/20 text-xs text-text">
          All {data.length} loaded rows selected.
          <button
            onClick={handleSelectAllMatching}
            className="text-accent-cyan hover:underline font-medium bg-transparent border-none cursor-pointer p-0"
          >
            Select all {totalMatching?.toLocaleString()} matching filters
          </button>
        </div>
      )}

      <table className="w-full text-sm border-collapse" style={{ minWidth: 700 }}>
        <thead className="sticky top-0 z-10 bg-surface-alt">
          <tr>
            {selectable && (
              <th className="w-10 px-2 py-2.5 border-b border-border-solid text-center">
                <input
                  type="checkbox"
                  checked={headerCheckState === 'checked'}
                  ref={(el) => {
                    if (el) el.indeterminate = headerCheckState === 'indeterminate'
                  }}
                  onChange={toggleSelectAll}
                  aria-label="Select all"
                  className="cursor-pointer w-4 h-4 accent-accent"
                />
              </th>
            )}
            {columns.map((col) => (
              <th
                key={col.key}
                style={{
                  width: col.width,
                  minWidth: col.minWidth,
                }}
                onClick={() => handleSortClick(col)}
                className={`
                  text-left text-xs font-medium text-text-muted px-3 py-2.5 border-b border-border-solid whitespace-nowrap
                  ${col.sortKey ? 'cursor-pointer hover:text-text select-none' : ''}
                `}
              >
                <span className="flex items-center gap-1">
                  {col.label}
                  {col.sortKey && sort?.field === col.sortKey && (
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" className={sort.dir === 'desc' ? 'rotate-180' : ''}>
                      <path d="M6 3l3 4H3z" />
                    </svg>
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {offsetY > 0 && (
            <tr><td colSpan={columns.length + (selectable ? 1 : 0)} style={{ height: offsetY, padding: 0, border: 0 }} /></tr>
          )}
          {visibleData.map((item, i) => {
            const globalIndex = startIndex + i
            const isSelected = selectable && item.id ? selected.has(item.id) : false
            return (
              <tr
                key={item.id ?? `vrow-${globalIndex}`}
                className={`border-b border-border/30 ${isSelected ? 'bg-accent/5' : ''} ${!onCellEdit && onRowClick ? 'cursor-pointer hover:bg-surface-alt/50' : selectable ? 'hover:bg-surface-alt/30' : ''}`}
                style={{ height: ROW_HEIGHT }}
              >
                {selectable && (
                  <td className="w-10 px-2 py-0 text-center">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={(e) => {
                        e.stopPropagation()
                        toggleRow(item, globalIndex, e.nativeEvent instanceof MouseEvent && e.nativeEvent.shiftKey)
                      }}
                      onClick={(e) => e.stopPropagation()}
                      aria-label={`Select row ${globalIndex + 1}`}
                      className="cursor-pointer w-4 h-4 accent-accent"
                    />
                  </td>
                )}
                {columns.map((col) => {
                  const colDef = col as ColumnDef<T>
                  const editField = colDef.editField ?? col.key
                  const isEditable = colDef.editable && onCellEdit
                  const cellKey = item.id ? `${item.id}:${editField}` : undefined
                  const cellStatus = cellKey && cellStates ? cellStates.get(cellKey) as 'saving' | 'saved' | 'error' | undefined : undefined
                  const rawValue = (item as Record<string, unknown>)[col.key]

                  if (isEditable && colDef.editType && item.id) {
                    return (
                      <td
                        key={col.key}
                        className={`px-3 py-0 text-text ${col.shrink !== false ? 'truncate' : ''}`}
                        style={{
                          maxWidth: col.width ?? '200px',
                          minWidth: col.minWidth,
                        }}
                      >
                        <InlineEditCell
                          value={(rawValue as string) ?? null}
                          displayValue={col.render ? col.render(item) : undefined}
                          editType={colDef.editType}
                          options={colDef.editOptions}
                          reverseMap={colDef.editReverse}
                          onSave={(newValue) => onCellEdit(item, editField, newValue)}
                          cellStatus={cellStatus}
                        />
                      </td>
                    )
                  }

                  // When inline editing is active, navigation is via name column render.
                  // When no inline editing (e.g. CampaignsPage), onRowClick applies.
                  const useRowClick = !onCellEdit && onRowClick
                  return (
                    <td
                      key={col.key}
                      onClick={useRowClick ? () => onRowClick(item) : undefined}
                      className={`px-3 py-0 text-text ${col.shrink !== false ? 'truncate' : ''} ${useRowClick ? 'cursor-pointer' : ''}`}
                      style={{
                        maxWidth: col.width ?? '200px',
                        minWidth: col.minWidth,
                      }}
                    >
                      {col.render
                        ? col.render(item)
                        : rawValue as ReactNode ?? '-'}
                    </td>
                  )
                })}
              </tr>
            )
          })}
          {endIndex < data.length && (
            <tr><td colSpan={columns.length + (selectable ? 1 : 0)} style={{ height: (data.length - endIndex) * ROW_HEIGHT, padding: 0, border: 0 }} /></tr>
          )}
        </tbody>
      </table>

      <div ref={sentinelRef} className="h-1" />

      {isLoading && (
        <div className="flex items-center justify-center py-4">
          <div className="w-5 h-5 border-2 border-border border-t-accent rounded-full animate-spin" />
          <span className="ml-2 text-sm text-text-muted">Loading...</span>
        </div>
      )}
    </div>
  )
}
