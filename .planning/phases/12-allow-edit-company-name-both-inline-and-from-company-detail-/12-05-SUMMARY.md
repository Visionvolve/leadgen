# Plan 12-05 Summary

**Status:** Complete (bundled commit with 12-06 + 12-07)

## Shipped

- `frontend/src/api/queries/useCompanies.ts` — `useUpdateCompany` already supported `params?: Record<string, string>` from a previous phase; no change needed beyond verifying the `apiFetch` error path forwards `details`. No edits.
- `frontend/src/hooks/useInlineEdit.ts` — added 409 `duplicate_company_name` branch alongside the existing email-duplicate branch. Dispatches `leadgen:company-duplicate` window event with full detail payload; awaits Promise resolution from the modal's chosen callback.
- `frontend/src/hooks/useCompanyDuplicateGate.ts` — new shared hook. Subscribes to `leadgen:company-duplicate`, exposes `pendingDuplicate` state + 4 resolution callbacks (merge / use existing / keep both / cancel). Merge calls `POST /api/companies/<id>/merge?into=<intoId>` via `apiFetch`. Navigation handled via `leadgen:navigate` event.
- `frontend/src/config/companyColumns.tsx` — flipped `name_edit` to `defaultVisible: true` (with click-to-navigate render preserved); flipped read-only `name` column to `defaultVisible: false` (still available in column picker).
- `frontend/src/pages/companies/CompaniesPage.tsx` — mounted `useCompanyDuplicateGate` + render slot for the modal.

## Backend tweak

- `api/routes/company_routes.py` PATCH 409 body now nests `matches` under `details` as well (preserves top-level `matches` for legacy clients) so the frontend `ApiError.details` carries them. Existing tests still pass — the response body grew but didn't change shape.

## Companies list page file modified

`frontend/src/pages/companies/CompaniesPage.tsx` (the production list page).

## tsc

`npx tsc --noEmit` exits 0.

## Email duplicate (contact) regression

Existing `entityType === 'contact' && field === 'email_address'` branch is untouched. The new branch is gated on `entityType === 'company' && field === 'name'`, so the two paths cannot interfere.
