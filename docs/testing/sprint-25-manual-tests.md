# Sprint 25 — LCC Client Requests — Manual Test Script

Use this script when validating Sprint 25 (Milestone v25) features on staging root after merges. Earlier phase sections (1–11) live in their own phase summaries until consolidated here.

## Phase 12: Editable Company Name + Duplicate Detection (BL-1203)

**Login URL:** <https://leadgen-staging.visionvolve.com/>
**Test user:** `test@staging.local` / `staging123` (super_admin)
**Tenant:** `visionvolve` (default after login)

### T12.1 Clean rename from Companies table

1. Navigate to `/visionvolve/companies/`.
2. Confirm the table shows an inline-editable name column by default
   (pencil affordance on hover; the read-only hyperlink column is hidden
   under the column picker).
3. Pick any company with a unique name; click the cell, type a new
   unique name, press Enter.
4. Expect: "Saving" → "Saved" badge; refresh → new name persists.

**PASS** if all three steps green.

### T12.2 Empty-name rejection

1. Same setup as T12.1 but type only whitespace then Enter.
2. Expect: red error indicator on cell; original name remains.

**PASS** if no PATCH 200 is observed (Network panel) and value reverts.

### T12.3 Duplicate-name modal appears

1. Pick company A. Note its name.
2. Pick company B; rename B to match A (e.g. "Acme s.r.o." if A is "Acme")
   — normalization should collapse both to `acme`.
3. Press Enter.
4. Expect: `DuplicateCompanyModal` opens. Card for A is visible with
   A's domain, status, owner, contact count, last activity date.
   Default focus is on "Use this one".

**PASS** if modal renders with one card for A and the default focus is visible.

### T12.4 'Use this one' navigates and discards rename

1. From T12.3 state, click "Use this one" on A's card.
2. Expect: modal closes, B's cell value reverts to its prior value,
   URL changes to `/visionvolve/companies/<A.id>`.

**PASS** if all three.

### T12.5 'Merge into this one' merges and lands on survivor

1. From T12.3 state, click "Merge into this one" on A's card.
2. Expect: modal shows "Merging…", then closes; URL changes to
   `/visionvolve/companies/<A.id>`; A's contact count has increased
   by B's prior contact count; B is gone from `/visionvolve/companies/`
   (the list does not contain B's old name).

**PASS** if all three.

### T12.6 'Keep both as separate'

1. From T12.3 state (recreate B since T12.5 deleted it), click footer
   "Keep both as separate".
2. Expect: modal closes, B's name is saved (PATCH 200), both A and
   B appear in `/visionvolve/companies/` with the same name.

**PASS** if both rows survive.

### T12.7 'Cancel' / Esc reverts

1. From T12.3 state, press Esc.
2. Expect: modal closes, B's cell reverts to pre-edit value, no
   PATCH 200 observed.

**PASS** if value matches pre-edit.

### T12.8 Detail-page edit

1. Open `/visionvolve/companies/<any.id>`.
2. Hover the company name heading — pencil should appear.
3. Click pencil, change name, press Enter.
4. Expect: heading updates; toast "Name saved" appears.

**PASS** if heading reflects new value after refresh.

### T12.9 Detail-page duplicate flow

1. From a Company detail page, rename to an existing in-tenant name.
2. Expect: same `DuplicateCompanyModal` opens; same 4 actions work.

**PASS** if modal renders.

### T12.10 Tenant isolation

Requires a second tenant; this step is an operator/super-admin
verification only. Skip with a note if no second tenant is reachable
on staging.

1. As super_admin, ensure tenant `visionvolve` has "Acme s.r.o." and
   tenant `losers` also has "Acme s.r.o." (or create test data).
2. Login as a visionvolve user, attempt to rename another company to
   "Acme".
3. Expect: the modal shows only the visionvolve Acme, never the losers
   Acme.

**PASS** if losers' row is NOT in matches.

### After all green

Notify the user: "Phase 12 staging validation complete — all 10
scenarios pass. Ready to merge staging → main."
