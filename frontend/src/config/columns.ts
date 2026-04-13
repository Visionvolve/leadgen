import type { Column } from '../components/ui/DataTable'

/**
 * Extended column definition that includes visibility metadata.
 * Used by ColumnPicker to manage which columns are shown.
 */
export interface ColumnDef<T> extends Column<T> {
  /** Whether the column is shown by default (before user customisation) */
  defaultVisible?: boolean
  /** Whether this column supports inline editing */
  editable?: boolean
  /** Edit input type: 'select' for dropdowns, 'text' for free text */
  editType?: 'select' | 'text'
  /** API field key to use when saving (defaults to column key) */
  editField?: string
  /** Display map for select edit options (db value → display label) */
  editOptions?: Record<string, string>
  /** Reverse map for select edit options (display label → db value) */
  editReverse?: Record<string, string>
}

/**
 * Helper to create a typed column definition array.
 */
export function defineColumns<T>(cols: ColumnDef<T>[]): ColumnDef<T>[] {
  return cols
}
