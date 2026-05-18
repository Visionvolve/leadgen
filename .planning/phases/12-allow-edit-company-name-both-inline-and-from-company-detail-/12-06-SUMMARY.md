# Plan 12-06 Summary

**Status:** Complete

## Shipped

- `frontend/src/components/ui/DetailField.tsx` — added new `EditableHeading` component. The pre-existing `EditableText` has a different prop shape (`onChange(name, value)` sync) used by the form-level save flow on CompanyDetail; rather than refactor that, the plan's intent is satisfied by a heading-specific variant: `EditableHeading` exposes async `onSave(newValue) => Promise<void>` that can throw; renders click-to-edit pencil button when not editing; Enter to save, Esc to cancel; in-error display below the input.
- `frontend/src/components/layout/EntityDetailPage.tsx` — added optional `titleSlot?: ReactNode` prop. When supplied, replaces the static `<h2>` heading with the slot. Keeps the existing `title` string prop as a fallback (and for the document-title-like behaviour).
- `frontend/src/pages/companies/CompanyDetailPage.tsx` — replaced the static page-title heading with `<EditableHeading>` bound to `company.name`. `onSave` calls `useUpdateCompany.mutateAsync({ id, data: { name } })` and on 409 `duplicate_company_name` dispatches the same `leadgen:company-duplicate` window event used by the table (so the shared `useCompanyDuplicateGate` + `DuplicateCompanyModal` captures it). Toast on success.

## Note on EditableText

The plan asked to ship `EditableText` with an async-`onSave` shape; that name was already used by a sync-`onChange` component in DetailField.tsx (powering CompanyDetail's form-level save). To avoid breaking ~10 existing call sites, the new component is exported as **`EditableHeading`** instead. Semantically identical to the plan's "EditableText with variant='heading'" — heading style is the only variant used, so a separate name is clearer.

## Header location

Line 47 of `EntityDetailPage.tsx` (the static `<h2>` rendering `title`) was the right insertion point — that's the only place company.name surfaces on the detail page.

## tsc

`npx tsc --noEmit` exits 0.
