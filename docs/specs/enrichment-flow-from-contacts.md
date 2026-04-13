# Enrichment Flow from Contacts/Companies Selection

**Status**: Draft
**Author**: Claude (spec agent)
**Date**: 2026-04-13

---

## Purpose

Allow users to select contacts or companies from their respective list pages and navigate directly to the Enrich page with those entities pre-loaded. This closes the gap between "I see these 15 contacts" and "I want to enrich them" — currently the user must manually copy IDs or rely on tag/owner filters that may not match their ad-hoc selection.

## Background

The EnrichPage (`frontend/src/pages/enrich/EnrichPage.tsx`) already supports:
- DAG visualization with 11 stage cards and dependency edges
- Stage enable/disable toggles, soft dep config, boost toggles
- Cost estimation via `POST /api/enrich/estimate` (accepts `entity_ids`)
- Pipeline execution via `POST /api/enrich/start` (does NOT yet accept `entity_ids` -- see Backend Gap below)
- Re-enrichment horizon controls per stage
- An `entityIds` filter field in `useEnrichState` (text input for comma-separated IDs)

The ContactsPage and CompaniesPage both have a `SelectionActionBar` with bulk actions (Add Tags, Add to Campaign). The pattern for adding a new bulk action is well-established.

### Backend Gap

The `/api/enrich/estimate` endpoint already accepts and processes `entity_ids`. However, `/api/enrich/start` does **not** parse `entity_ids`, `re_enrich`, or `boost` from the request body and does **not** forward them to `start_pipeline_threads`. This must be fixed as part of this feature.

---

## Requirements

### Functional Requirements

**FR-1: "Enrich Selected" bulk action on ContactsPage**
- Add an "Enrich Selected" button to the `SelectionActionBar` actions array on ContactsPage.
- When clicked with explicit selection (specific IDs): navigate to `/{namespace}/enrich?contacts=id1,id2,...`
- When clicked with "all matching" selection: navigate to `/{namespace}/enrich?entity_type=contact&filters={base64-encoded filter state}`
- Button uses a beaker/flask icon consistent with the enrichment theme.

**FR-2: "Enrich Selected" bulk action on CompaniesPage**
- Add an "Enrich Selected" button to the `SelectionActionBar` actions array on CompaniesPage.
- When clicked with explicit selection: navigate to `/{namespace}/enrich?companies=id1,id2,...`
- When clicked with "all matching" selection: navigate to `/{namespace}/enrich?entity_type=company&filters={base64-encoded filter state}`

**FR-3: EnrichPage reads URL params and enters "Selected Entities" mode**
- On mount, EnrichPage reads `?contacts=`, `?companies=`, or `?filters=` from URL search params.
- When `contacts` or `companies` param is present, parse the comma-separated IDs and populate the `entityIds` filter in `useEnrichState`.
- When `filters` param is present (base64-encoded), decode and resolve matching entity IDs via API call to determine the set.
- Show a context banner above the DAG: "Enriching N selected contacts" or "Enriching N selected companies" with a "Change selection" link that navigates back to the originating list page.
- The existing FilterBar is hidden or replaced by this banner when in selected-entities mode (the tag/owner/tier filters don't apply -- the selection IS the filter).

**FR-4: Estimate shows skip/re-enrich breakdown**
- When in selected-entities mode, the estimate response should surface per-stage: how many entities need enrichment vs how many are already enriched and will be skipped.
- Display in the DagControls or a summary row: "10 need enrichment, 5 already enriched (will be skipped)".
- The existing per-stage `eligible_count` in the estimate response already handles this (entities with completed stage completions are excluded from eligible count).

**FR-5: Re-enrich toggle for selected entities**
- The existing re-enrich controls (per-stage toggle + horizon days) work as-is in selected-entities mode.
- When re-enrich is enabled for a stage, the estimate re-counts including previously enriched entities within the horizon window.
- No new UI needed -- the existing `StageCard` re-enrich controls are sufficient.

**FR-6: Backend - `/api/enrich/start` accepts `entity_ids`**
- Parse `entity_ids` from request body (array of UUID strings).
- Parse `re_enrich` from request body (per-stage config object).
- Parse `boost` from request body (per-stage boolean map).
- Store `entity_ids` in the pipeline_run config JSON.
- Pass `entity_ids` to `start_pipeline_threads` which forwards to the DAG executor.
- Duplicate pipeline check: when `entity_ids` are provided, check for running pipelines by tenant_id only (not by tag_id, since entity_ids mode is tag-independent).

**FR-7: URL state is shareable**
- The `?contacts=` or `?companies=` URL is copy-pasteable and bookmarkable.
- Refreshing the page preserves the selection.
- For large selections (>100 IDs), the URL param approach may exceed URL length limits. In that case, fall back to sessionStorage + a short key in the URL (e.g., `?selection=sess_abc123`).

### Non-Functional Requirements

**NFR-1**: Navigation from contacts/companies to enrich page must be instant (client-side route, no full page reload).

**NFR-2**: The estimate API call with entity_ids must respond within 2 seconds for up to 500 entities.

**NFR-3**: URL params must be sanitized -- only valid UUIDs accepted, non-UUIDs silently dropped.

---

## Acceptance Criteria

### AC-1: Contacts bulk enrich (explicit selection)

**Given** the user is on the Contacts page with 5 contacts selected (explicit checkboxes)
**When** they click "Enrich Selected" in the action bar
**Then** the app navigates to `/{namespace}/enrich?contacts=id1,id2,id3,id4,id5`
**And** the EnrichPage shows a banner: "Enriching 5 selected contacts"
**And** the DAG stages show accurate cost estimates for those 5 contacts
**And** clicking "Change selection" navigates back to the Contacts page

### AC-2: Contacts bulk enrich (all matching)

**Given** the user is on the Contacts page with "All 342 matching" selected via the select-all toggle
**When** they click "Enrich Selected" in the action bar
**Then** the app navigates to `/{namespace}/enrich?entity_type=contact&filters={base64}`
**And** the EnrichPage resolves the filter to entity IDs and shows: "Enriching 342 matching contacts"
**And** the estimate and pipeline execution use the resolved IDs

### AC-3: Companies bulk enrich

**Given** the user is on the Companies page with 3 companies selected
**When** they click "Enrich Selected" in the action bar
**Then** the app navigates to `/{namespace}/enrich?companies=id1,id2,id3`
**And** the EnrichPage shows a banner: "Enriching 3 selected companies"

### AC-4: Skip already-enriched by default

**Given** the user navigated to enrich with 10 selected contacts
**And** 4 of those contacts already have Person stage completed
**When** the estimate loads for the Person stage
**Then** the stage card shows eligible_count = 6 (not 10)
**And** the summary shows "6 need enrichment, 4 already enriched"

### AC-5: Re-enrich with horizon

**Given** the user has 10 contacts selected, 4 already enriched (Person stage completed 20 days ago)
**When** they enable re-enrich on Person stage with horizon = 30 days
**Then** the estimate shows eligible_count = 6 (enriched within 30 days are still skipped)
**When** they change horizon to 15 days
**Then** the estimate shows eligible_count = 10 (all 4 enriched contacts now exceed the 15-day horizon)

### AC-6: Pipeline runs with entity_ids

**Given** the user configured stages and clicked "Run Pipeline" with 5 selected contacts
**When** the pipeline starts
**Then** `POST /api/enrich/start` receives `entity_ids: [id1..id5]`
**And** only those 5 contacts are processed through the enabled stages
**And** the pipeline progress tracker shows accurate counts

### AC-7: Empty selection guard

**Given** the user navigates directly to `/{namespace}/enrich?contacts=` (empty param)
**Then** the EnrichPage shows the normal filter-based mode (no banner, standard FilterBar visible)

### AC-8: Large selection fallback

**Given** the user selects "All 2000 matching contacts"
**When** they click "Enrich Selected"
**Then** the selection is stored in sessionStorage (not URL params)
**And** the URL contains a session key reference: `?selection=sess_{key}`
**And** refreshing the page within the same browser session preserves the selection

---

## UX / Design

### User Flow

```
ContactsPage / CompaniesPage
  |
  | [Select contacts/companies via checkboxes]
  | [SelectionActionBar appears at bottom]
  | [Click "Enrich Selected"]
  |
  v
EnrichPage (Selected Entities Mode)
  |
  | [Banner: "Enriching 15 selected contacts" | "Change selection"]
  | [DAG visualization with stage cards]
  | [Cost estimate auto-loads for selected entities]
  | [Configure stages, soft deps, re-enrich, boost]
  | [Click "Run Pipeline"]
  |
  v
Pipeline executes on selected entities only
```

### Interactions

1. **"Enrich Selected" button** in SelectionActionBar:
   - Icon: beaker/flask SVG (matches enrichment theme)
   - Same style as existing "Add Tags" and "Add to Campaign" buttons
   - No loading state needed (it's a navigation, not an API call)

2. **Context banner** on EnrichPage (selected-entities mode):
   - Full-width bar above the DAG, below where FilterBar normally appears
   - Background: `bg-accent/5` with `border-accent/20` left border (4px)
   - Text: "Enriching {N} selected {contacts|companies}" in `text-sm font-medium`
   - "Change selection" link: `text-accent hover:underline` — navigates back to originating page
   - "Clear selection" action: removes URL params, reverts to standard filter mode

3. **FilterBar behavior** in selected-entities mode:
   - The FilterBar is hidden (the selection replaces filter-based targeting)
   - The entity IDs filter field in useEnrichState is populated programmatically from URL params
   - All existing DAG controls (stage toggles, soft deps, re-enrich, boost, cost) work unchanged

4. **Estimate summary** when in selected-entities mode:
   - Below the context banner, show: "{eligible} need enrichment, {skipped} already enriched (will be skipped)"
   - Numbers update reactively as stages are toggled or re-enrich settings change
   - Skipped count = total selected - max eligible across enabled stages

### Layout

```
+-----------------------------------------------------------------------+
| [Banner] Enriching 15 selected contacts    [Change selection] [Clear] |
+-----------------------------------------------------------------------+
| 10 need enrichment, 5 already enriched (will be skipped)              |
+-----------------------------------------------------------------------+
| [DagControls: Run / Stop / Cost estimate / Config save/load]          |
+-----------------------------------------------------------------------+
| [DAG Visualization]                                                    |
|   [StageCard: L1]  -->  [StageCard: Triage]  -->  [StageCard: L2]    |
|   ...                                                                  |
+-----------------------------------------------------------------------+
```

### States

| State | Behavior |
|-------|----------|
| No URL params | Standard mode: FilterBar visible, no banner |
| `?contacts=id1,id2` | Selected-entities mode: banner shown, FilterBar hidden, entity IDs populated |
| `?companies=id1,id2` | Same as above but for companies |
| `?entity_type=contact&filters=base64` | Resolves filters to IDs on mount, then behaves as selected-entities mode |
| `?selection=sess_key` | Reads IDs from sessionStorage, then behaves as selected-entities mode |
| Invalid/empty IDs after parse | Falls back to standard mode |

### Accessibility

- Banner has `role="status"` and `aria-live="polite"` for screen reader announcement
- "Change selection" link has descriptive `aria-label`: "Go back to contacts list to change selection"
- "Enrich Selected" button in action bar follows existing action button pattern (keyboard-accessible, focus-visible)

---

## Technical Design

### Affected Components

| Component | Change |
|-----------|--------|
| `ContactsPage.tsx` | Add "Enrich Selected" action to SelectionActionBar |
| `CompaniesPage.tsx` | Add "Enrich Selected" action to SelectionActionBar |
| `EnrichPage.tsx` | Read URL params, show banner, hide FilterBar in selected mode |
| `useEnrichState.ts` | Add `setEntityIds` for programmatic population from URL params; add `selectionMode` state |
| `useEnrichEstimate.ts` | No changes needed (already handles `entity_ids` in filters) |
| `useEnrichPipeline.ts` | Ensure `entity_ids` is passed to the start API call (verify) |
| `enrich_routes.py` | Parse `entity_ids`, `re_enrich`, `boost` in `/api/enrich/start` |
| `pipeline_engine.py` | Accept `entity_ids` in `start_pipeline_threads` and forward to DAG executor |

### New Components

| Component | Purpose |
|-----------|---------|
| `EnrichSelectionBanner.tsx` | Context banner showing selection count + "Change selection" link |

### Data Model

No schema changes. The `pipeline_runs.config` JSON column already stores arbitrary config; `entity_ids` will be added there.

### API Contract

#### `POST /api/enrich/start` (updated)

New accepted body fields (additive, backwards compatible):

```json
{
  "stages": ["l1", "person", "contact_details"],
  "tag_name": "",
  "owner_name": "",
  "tier_filter": [],
  "sample_size": null,
  "entity_ids": ["uuid1", "uuid2", "uuid3"],
  "re_enrich": {
    "person": { "enabled": true, "horizon": "30" }
  },
  "boost": {
    "l2": true
  }
}
```

- `entity_ids`: Optional array of UUID strings. When provided, the pipeline processes only these entities (ignoring tag/owner/tier filters). Validated: must be valid UUIDs belonging to the tenant.
- `re_enrich`: Optional per-stage re-enrich config. When a stage has `enabled: true`, entities with existing completions are re-processed. `horizon` (days as string or null) limits re-enrichment to entities enriched more than N days ago.
- `boost`: Optional per-stage boost flag. When `true`, the stage uses the enhanced (2x cost) model.

#### `POST /api/enrich/estimate` (no changes)

Already accepts `entity_ids` and `re_enrich`. No modifications needed.

### URL Param Encoding

**Explicit IDs** (up to ~100 entities):
```
/ns/enrich?contacts=uuid1,uuid2,uuid3
/ns/enrich?companies=uuid1,uuid2,uuid3
```

**Filter-based** (all matching):
```
/ns/enrich?entity_type=contact&filters=eyJ0YWdfbmFtZSI6InNwcmludC0xIiwiaWNwX2ZpdCI6IkEifQ==
```
The `filters` value is `btoa(JSON.stringify(filterState))`.

**Large selection fallback** (>100 IDs):
```
/ns/enrich?selection=sess_1713020400000_abc
```
The key maps to `sessionStorage.getItem('enrich_selection_sess_1713020400000_abc')` which contains `JSON.stringify({ entity_type, ids })`.

### Navigation Implementation

In ContactsPage/CompaniesPage, the "Enrich Selected" action:

```typescript
// Pseudocode — not implementation
const handleEnrichSelected = () => {
  if (selectionMode === 'all-matching') {
    const encoded = btoa(JSON.stringify(activeFilters))
    navigate(`/${namespace}/enrich?entity_type=contact&filters=${encoded}`)
  } else if (selectedIds.size > 100) {
    const key = `sess_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    sessionStorage.setItem(`enrich_selection_${key}`, JSON.stringify({
      entity_type: 'contact',
      ids: Array.from(selectedIds),
    }))
    navigate(`/${namespace}/enrich?selection=${key}`)
  } else {
    navigate(`/${namespace}/enrich?contacts=${Array.from(selectedIds).join(',')}`)
  }
}
```

---

## Edge Cases

| Edge Case | Handling |
|-----------|----------|
| User navigates to enrich URL with invalid UUIDs | Silently drop non-UUID values; if no valid IDs remain, fall back to standard mode |
| User navigates with `?contacts=` and `?companies=` both set | `contacts` takes precedence (contacts are the primary entity) |
| Selected entities belong to different tags | Works fine -- entity_ids mode bypasses tag filtering entirely |
| Session storage key expired or cleared | Show a "Selection expired" toast and fall back to standard mode |
| User refreshes during pipeline run | Pipeline run is tracked by `pipeline_run_id` in state; progress polling resumes normally. The entity selection banner re-renders from URL params. |
| 0 eligible entities after estimate | DagControls "Run" button is disabled with tooltip: "No entities need enrichment" |
| Mixed entity types in selection | Not supported -- contacts and companies are separate selections. The URL param distinguishes (`?contacts=` vs `?companies=`). |
| Entity IDs that don't belong to the tenant | Backend validates tenant_id ownership; non-matching IDs are silently excluded from processing |

---

## Security Considerations

- **Tenant isolation**: All entity IDs in the URL/sessionStorage are validated against the current tenant_id on every API call (estimate and start). IDs belonging to other tenants are silently excluded.
- **UUID validation**: Both frontend (regex) and backend (UUID parse) validate that entity_ids are well-formed UUIDs before any DB query.
- **No entity data in URL**: Only UUIDs appear in the URL, not names or other PII. The IDs are opaque to anyone without API access.
- **Session storage scoping**: Selection keys are prefixed with `enrich_selection_` and scoped to the origin. They are cleaned up after use or on page unload.
- **Rate limiting**: The existing `/api/enrich/start` rate limiting applies. No additional rate limiting needed for the entity_ids path.

---

## Testing Strategy

### Unit Tests (Python)

- `test_enrich_start_with_entity_ids`: Verify `/api/enrich/start` accepts `entity_ids`, stores them in config, and spawns pipeline threads with entity filtering.
- `test_enrich_start_entity_ids_tenant_validation`: Verify entity IDs from another tenant are excluded.
- `test_enrich_start_entity_ids_with_re_enrich`: Verify re-enrich config is parsed and forwarded.
- `test_enrich_start_entity_ids_with_boost`: Verify boost config is parsed and forwarded.
- `test_enrich_start_empty_entity_ids_ignored`: Verify empty `entity_ids` array falls back to tag/owner mode.
- `test_enrich_estimate_entity_ids`: Already exists -- verify it still works after start changes.

### Frontend Unit Tests (Vitest)

- `useEnrichState`: Test that `setEntityIds` populates from URL params on mount.
- URL param parsing: Test all three modes (contacts, companies, filters) and edge cases (empty, invalid, mixed).
- Session storage fallback: Test write and read of large selections.

### E2E Tests (Playwright — sprint completion)

- Select 3 contacts on ContactsPage -> click "Enrich Selected" -> verify EnrichPage banner shows "Enriching 3 selected contacts" -> verify estimate loads -> run pipeline -> verify completion.
- Select "All matching" on ContactsPage -> click "Enrich Selected" -> verify filter-based URL -> verify resolution to entity count.
- Same flow for CompaniesPage.
- Refresh during selected-entities mode -> verify selection persists.

---

## Dependencies

- **Existing**: `useEnrichState`, `useEnrichEstimate`, `useEnrichPipeline`, `SelectionActionBar`, `DagVisualization`, `StageCard`, `DagControls`
- **Backend**: `enrich_routes.py`, `pipeline_engine.py`, `dag_executor.py`
- **No new npm packages needed**
- **No database migrations needed**

---

## Out of Scope

- **Cross-entity-type enrichment in a single run**: Cannot select contacts AND companies together for one pipeline run. Each run is either contact-scoped or company-scoped (matching existing stage entity types).
- **Saved selections / selection presets**: Bookmarkable URLs are supported, but there is no UI for saving/naming selections.
- **Batch scheduling of selected entities**: The SchedulePanel on EnrichPage is not wired to entity_ids mode in this iteration.
- **Contacts-to-companies auto-resolution**: Selecting contacts does not automatically include their parent companies. Each entity type is enriched independently.
- **Progress page deep-link back to selection**: After pipeline completes, there is no "re-run with same selection" shortcut (user navigates back to contacts to re-select).
