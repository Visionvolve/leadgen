# Phase 12 — Discussion Log

**Date:** 2026-05-14
**Mode:** Auto-decide (user response to gray-area prompt: *"You know what it is simple, execute full auto and get it to prod"*)
**Phase:** 12 — Editable Company Name + Duplicate Detection

## Gray areas presented

The orchestrator surfaced four phase-specific gray areas to the user:

1. **Normalization rules — how strict?**
2. **Duplicate-found prompt — what choices does the user get?**
3. **Merge semantics — what does "merge" actually do?**
4. **Backfill & where normalized name lives**

User opted out of interactive discussion and authorized auto-decision. The decisions captured in `12-CONTEXT.md` are summarized below.

## Auto-decisions

### Normalization rules
- Trim → lowercase → NFKD + drop combining marks → strip punctuation → strip common legal suffixes (CZ + DE + EN: `s.r.o`, `sro`, `a.s`, `as`, `spol s r o`, `v.o.s`, `vos`, `k.s`, `ks`, `gmbh`, `ag`, `mbh`, `kg`, `ltd`, `limited`, `llc`, `inc`, `corp`, `co`, `company`).
- Exact-match-after-normalization. **No fuzzy/trigram matching in v1** — added to deferred ideas.
- Rationale: CZ is the primary market (LCC tenant); legal-suffix stripping is load-bearing for real-world dedup. Fuzzy matching introduces UX complexity that's overkill for first ship.

### Duplicate-found prompt UX
- Server returns 409 with `{ code: "duplicate_company_name", matches: [...] }` (matches summary: name, domain, owner, status, contact count, last activity).
- Frontend opens `DuplicateCompanyModal`. Per-match actions: **"Use this one"** (navigate, abort edit) | **"Merge into this one"**.
- Footer actions: **"Keep both as separate"** (re-PATCH with `?confirm_duplicate=keep_both`) | **"Cancel"** (revert input, no API call).
- Default focus: "Use this one" on first / highest-confidence match.
- Rationale: covers the three real intents (same → navigate, same → combine, not actually same → proceed). Merge-direction picker deferred — always merge edited record INTO existing match; user can rename the survivor afterwards.

### Merge semantics
- Surviving record = the existing match. Deleted = the edited record.
- Owner: surviving record's `owner_id` wins; modal warns when owners differ.
- Fields: surviving wins; deleted only fills NULL slots on surviving (reuses `dedup.update_empty_fields` pattern).
- FK re-point: `contacts.company_id`, `email_send_log.company_id` (if present), `enrichment_l1.company_id`, `enrichment_l2.company_id`, `company_tags.company_id`, `contact_field_changes.entity_id WHERE entity_type='company'`, and any other `company_id` FK.
- Audit: single row in `contact_field_changes` with `field_name='merged_from'`, plus JSONB metadata snapshot of the deleted row.
- Disposition: hard-delete the duplicate (audit snapshot preserves the data).
- Wrapped in a single Postgres transaction. Rollback on any FK failure.

### Backfill & storage
- New column `companies.normalized_name TEXT` with non-unique index `(tenant_id, normalized_name)`.
- App computes on insert/update; single source of truth = `normalize_company_name()`.
- One-time backfill migration computes for all existing rows.
- Index is **non-unique** — user can intentionally "keep both"; the prompt is the gate, not the schema.
- Surfacing existing in-tenant duplicates retroactively (forced cleanup task) → deferred.

## Deferred ideas (preserved for future phases)

- Fuzzy / `pg_trgm` matching as a fallback to exact-normalized matching.
- Duplicate detection on company **create** (POST), not just edit.
- Same flow for contact full-name editing.
- Bulk merge UI / "find all duplicates" report.
- Choose merge direction (edited record as survivor).
- Side-by-side field-diff preview before merge.

## Notes for the planner

- The dormant `name_edit` column in `companyColumns.tsx` proves this feature was already on someone's roadmap — Phase 12 is the activation. Minimal frontend "discovery delta".
- `useInlineEdit` hook already handles 409 conflicts (built for email duplicates). Phase 12 adds one new code recognizer.
- Real technical dependency is **not** Phase 11 (as ROADMAP.md says) — it's `useInlineEdit.ts`, which is **already in the codebase**. Phase 12 can run independently of Phases 5, 6, 11.
- No matching `BL-####` exists in `gsd-phase-mapping`. Planner should create **BL-1117** (Editable company name + duplicate detection) in `Sprint 25 — LCC client requests` before execution starts.

---

*Auto-decided 2026-05-14. CONTEXT.md is the canonical record; this log is for audit only.*
