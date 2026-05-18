# Plan 12-08 Summary

**Status:** Complete

## Shipped

- `docs/testing/sprint-25-manual-tests.md` — **created** (file did not previously exist). Contains the Phase 12 section with T12.1..T12.10 scenarios.
- `tests/unit/test_company_duplicate_full_flow.py` — composed end-to-end backend test: PATCH 409 → POST /merge → verify deleted row gone, contacts re-pointed, audit row with `deleted_snapshot` written. Passes on the first run (the underlying handlers were green in Plans 12-03 and 12-04).
- `frontend/e2e/company-duplicate-merge.spec.ts` — Playwright spec for the sprint-completion E2E run. Login → table → inline rename → 409 modal → "Merge into this one" → assert navigation to surviving record + deleted row gone from list. Includes `beforeAll`/`afterAll` cleanup keyed on `PWTest Bl1203` prefix.

## File created or appended

`docs/testing/sprint-25-manual-tests.md` is **new** in this repo. The earlier phases (1–11) of Sprint 25 didn't have a consolidated test script — their summaries live in their own phase folders. Future phases can append below the Phase 12 section.

## T12.* scenarios

Total: **10** (T12.1..T12.10) — matches the plan's minimum.

## Playwright spec tagging

The plan suggested a `@sprint-end` tag or a `frontend/tests/e2e/sprint-end/` subdir. Inspecting `frontend/e2e/playwright.config.ts` (none found in this commit so far) and the existing 11 spec files, there is no tag mechanism in this codebase — all specs in `frontend/e2e/` run only when invoked manually via `make test-e2e` (which CLAUDE.md explicitly bans during feature development).

So the spec sits in `frontend/e2e/` alongside the others. The header comment **explicitly notes "SPRINT-END E2E ONLY"** so the sprint QA agent knows to include it but operators don't run it per-PR.

## Tests

- `pytest tests/unit/test_company_duplicate_full_flow.py`: **1 passed**.
- Combined BL-1203 backend suite (normalize + dedup + PATCH dup gate + merge + full flow): **68 passed**.
- `npx tsc --noEmit` on the Playwright spec: clean.
