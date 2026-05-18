# Plan 12-07 Summary

**Status:** Complete (modal component + page wiring)

## Shipped

- `frontend/src/components/companies/DuplicateCompanyModal.tsx` — new component. Renders all 4 resolution actions: per-match "Use this one" + "Merge into this one", footer "Keep both as separate" + "Cancel". Focus trap (default focus on first "Use this one"; Esc and overlay click cancel). Owner-mismatch warning per card when `currentOwnerId` is set and differs. Domain link gated by `^[a-z0-9.-]+$` regex to prevent `javascript:`-scheme injection. Busy state disables all buttons during an in-flight merge; error message in red beneath the list on failure.
- Render slots wired in:
  - `frontend/src/pages/companies/CompaniesPage.tsx` (with `currentOwnerId={null}` per per-row owner not being trivially available in table context).
  - `frontend/src/pages/companies/CompanyDetailPage.tsx` (with `currentOwnerId={null}` because the `CompanyDetail` API type does not expose `owner_id`, only `owner_name`).

## Frontend test runner

None configured. The project has Playwright (`frontend/e2e/`) but no vitest/jest/testing-library. Per Plan 12-08 the test artifact for the modal is a Playwright E2E spec covering the visible flow — written in Plan 12-08 / Task 3.

## Modal style

Mirrors existing `CreateCompanyModal` semantics (fixed overlay + max-width card + sticky header/footer). Uses the existing tailwind tokens (`bg-surface-1`, `text-status-warn`, `text-accent-cyan`, etc.).

## currentOwnerId on CompaniesPage / CompanyDetailPage

Passed `null` for both per the plan's note ("per-row owner is not trivially available in table context, so null is acceptable for v1"). The owner-mismatch warning will activate in v1.1 once a richer entity context is plumbed.
