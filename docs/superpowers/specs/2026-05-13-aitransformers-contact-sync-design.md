# AITransformers Contact Sync — Design Spec

**Date:** 2026-05-13
**Author:** brainstormed with michal@visionvolve.ai
**Status:** Approved — ready for implementation plan
**Touches:** `leadgen-pipeline`, `aitransformers-platform`
**Audience:** Sprint engineers, EM/PM/PD reviewers

---

## 1. Problem

We want to run an outbound campaign in the leadgen tool targeting users of
the AITransformers product. Today there is no automated way to get those
users into the Visionvolve namespace of `leadgen-pipeline`. Manual
CSV-shuffling is error-prone and doesn't keep up as new AITransformers
users sign up.

## 2. Goal

Sync AITransformers users into the **Visionvolve namespace** of
`leadgen-pipeline` (prod), import each one as a **contact**, and tag every
imported contact with the **`AITransformers`** tag so they can be filtered
and addressed as a campaign audience.

## 3. Non-goals

- Building user-level tagging in leadgen (tags remain on contacts/companies).
- Bi-directional sync. The flow is AITransformers → leadgen only.
- Removing or untagging contacts when a user loses AITransformers access.
  Sync is additive only; manual cleanup is acceptable for v1.
- Enriching contacts beyond the fields AITransformers already provides
  (no L1/L2/Person enrichment pipeline triggers in v1).
- Importing `community_subscribers` (landing-page newsletter signups).
  Only authenticated AITransformers users are in scope.

## 4. Audience & source of truth

| Source | Field for sync | Notes |
|---|---|---|
| **AITransformers `users` table** (cases-api, prod) | All rows | Users who have logged in at least once. Has rich profile. |
| ~~IAM `app_access`~~ | n/a | Considered and rejected — thinner data, requires a second new endpoint. |
| ~~`community_subscribers`~~ | n/a | Out of scope for v1. |

AITransformers' `users` table already filters effectively to "users of
AITransformers" (the row is only created on first IAM-authenticated login).
We do not need a server-side `app=aitransformers` filter.

## 5. Architecture

```
┌─ aitransformers-platform (cases-api, prod) ─────────────┐
│  NEW: GET /api/admin/leads-export                       │
│    Auth: existing admin middleware                      │
│    Query: ?limit=200&offset=0                           │
│    Returns paginated JSON:                              │
│      { items: [...], next_offset: N | null }            │
│    Each item: iam_id, email, name, display_name,        │
│      company, industry, role, company_size,             │
│      maturity_level, tier, is_founding_member,          │
│      newsletter_subscribed, created_at, updated_at      │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTPS, Bearer service token
                           ▼
┌─ leadgen-pipeline (api/, prod) ─────────────────────────┐
│  NEW: api/jobs/aitransformers_contact_sync.py           │
│  NEW: api/cli/aitransformers_sync.py — flask CLI        │
│  Cron: registered to run daily at 03:00 UTC             │
└─────────────────────────────────────────────────────────┘
```

**Two coordinated PRs, one backlog item** (per the cross-repo pattern
already used in v25): both must pass review before either merges.

## 6. New AITransformers admin endpoint

**Path:** `GET /api/admin/leads-export`

**Auth:** existing admin middleware (super_admin via IAM session) +
optional service token (`X-Service-Token`) for cron usage. Service token
stored in IAM-issued credentials, configured in prod `.env`.

**Query params:**
- `limit` — int, default 200, max 500
- `offset` — int, default 0

**Response (200):**

```json
{
  "items": [
    {
      "iam_id": "uuid-from-iam",
      "email": "alice@acme.com",
      "name": "Alice Example",
      "display_name": "Alice",
      "company": "Acme Corp",
      "industry": "manufacturing",
      "role": "ml-engineer",
      "company_size": "50-200",
      "maturity_level": 3,
      "tier": "free",
      "is_founding_member": false,
      "newsletter_subscribed": true,
      "created_at": "2026-04-12T10:30:00Z",
      "updated_at": "2026-05-01T08:00:00Z"
    }
  ],
  "next_offset": 200
}
```

`next_offset` is `null` when the page is the last.

**Errors:**
- 401 if no/bad auth.
- 400 on invalid params.
- 500 on DB error — no item array.

**Source query:** `SELECT … FROM users ORDER BY created_at LIMIT $1 OFFSET $2`.
Ordering by `created_at` keeps pagination stable.

## 7. Leadgen sync module

### File layout

```
api/jobs/aitransformers_contact_sync.py        # Pure logic
api/cli/aitransformers_sync.py                 # @click.command wrapper
api/cli/__init__.py                            # register command
tests/unit/jobs/test_aitransformers_contact_sync.py
```

Cron registration on the API container (mechanism matches existing scheduled
jobs — to be confirmed during planning; likely a `cron` line in the API
container's entrypoint).

### Config (env vars)

| Var | Default | Required | Notes |
|---|---|---|---|
| `AITRANSFORMERS_API_URL` | `https://aitransformers.eu/api` | yes | |
| `AITRANSFORMERS_ADMIN_TOKEN` | — | yes | Service token, prod-only |
| `LEADGEN_AITRANSFORMERS_TENANT_SLUG` | `visionvolve` | no | |
| `LEADGEN_AITRANSFORMERS_BATCH_SIZE` | `200` | no | |
| `LEADGEN_AITRANSFORMERS_TAG_NAME` | `AITransformers` | no | |

Token is added to the prod `.env` and to GHA secrets via the same pattern
already used for `IAM_SERVICE_API_KEY`.

### Algorithm

```text
sync_aitransformers_users():
    cfg = load_config()
    tenant = Tenant.query.filter_by(slug=cfg.tenant_slug).first()
    require(tenant, abort=True)

    with advisory_lock("aitransformers-sync", tenant.id):
        tag = find_or_create_tag(tenant.id, cfg.tag_name)

        offset = 0
        totals = {"created":0,"updated":0,"tagged_new":0,
                  "tagged_existing":0,"skipped":0,"errors":0}

        while True:
            page = http_get_with_retry(
                f"{cfg.api_url}/admin/leads-export",
                params={"limit": cfg.batch_size, "offset": offset},
                headers={"Authorization": f"Bearer {cfg.admin_token}"}
            )
            for row in page["items"]:
                try:
                    process_row(tenant.id, tag.id, row, totals)
                except Exception as e:
                    totals["errors"] += 1
                    log_error(row.get("iam_id"), e)
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]

        log_summary(totals)
```

### Row processing

```text
process_row(tenant_id, tag_id, row, totals):
    if not row.get("email"):
        totals["skipped"] += 1; return

    # 1. Find contact: prefer stable source_id, fallback to email
    contact = Contact.query.filter_by(
        tenant_id=tenant_id, source="aitransformers",
        source_id=row["iam_id"]
    ).first()
    if not contact:
        contact = Contact.query.filter_by(
            tenant_id=tenant_id, email=row["email"].lower()
        ).first()

    if contact is None:
        contact = Contact(tenant_id=tenant_id,
                          email=row["email"].lower(),
                          source="aitransformers",
                          source_id=row["iam_id"])
        db.session.add(contact)
        totals["created"] += 1
        new_contact = True
    else:
        # Adopt source_id if matched by email and source_id was empty
        if not contact.source_id:
            contact.source = "aitransformers"
            contact.source_id = row["iam_id"]
        new_contact = False

    # 2. Field merge — fill blanks only
    first, last = split_name(row.get("name") or row.get("display_name"))
    fill_if_empty(contact, "first_name", first)
    fill_if_empty(contact, "last_name", last)
    fill_if_empty(contact, "company", row.get("company"))
    fill_if_empty(contact, "title", row.get("role"))
    # Optional fields land in JSONB metadata if the column doesn't exist;
    # exact mapping confirmed in planning against api/models.py
    merge_metadata(contact, "aitransformers", {
        "industry": row.get("industry"),
        "company_size": row.get("company_size"),
        "maturity_level": row.get("maturity_level"),
        "tier": row.get("tier"),
        "is_founding_member": row.get("is_founding_member"),
        "newsletter_subscribed": row.get("newsletter_subscribed"),
        "synced_at": utcnow_iso(),
    })

    if not new_contact:
        totals["updated"] += 1

    db.session.flush()  # need contact.id

    # 3. Tag assignment — idempotent via ON CONFLICT DO NOTHING
    result = db.session.execute(
        insert(ContactTagAssignment.__table__)
            .values(contact_id=contact.id, tag_id=tag_id,
                    tenant_id=tenant_id)
            .on_conflict_do_nothing()
    )
    if result.rowcount > 0:
        totals["tagged_new"] += 1
    else:
        totals["tagged_existing"] += 1

    db.session.commit()
```

### Idempotency guarantees

- **Tag**: found-or-created once per run.
- **Contact match**: prefers `source_id` (IAM UUID — survives email
  changes); falls back to email; finally inserts.
- **Tag assignment**: `ON CONFLICT DO NOTHING` on the existing
  `(contact_id, tag_id)` uniqueness constraint.
- **Field merge**: never overwrites a non-empty leadgen value. Manual
  edits in the dashboard are safe.
- **Per-row tx**: a single bad row doesn't fail the run.
- **Advisory lock**: overlapping runs (cron + manual CLI) are serialized.

## 8. Failure modes

| Failure | Behavior |
|---|---|
| AITransformers 5xx / network timeout | Retry 3× exp backoff (1s, 4s, 16s) on the HTTP call. After exhaustion, abort run, log fatal. |
| AITransformers 4xx | Abort, log fatal (config or token error). |
| Row missing email | Skipped, counted in `skipped`. |
| Row processing exception | Counted in `errors`, logged with `iam_id`, run continues. |
| Tenant `visionvolve` missing | Abort, log fatal. |
| Overlapping run | Second run sees advisory lock taken, exits cleanly with log line `skipped — already running`. |

## 9. Observability

- Single structured JSON log line per run summarizing
  `{created, updated, tagged_new, tagged_existing, skipped, errors,
  duration_ms, pages_fetched}`.
- Per-error log includes `iam_id` and exception class.
- Logs are emitted to stdout and captured by the existing container log
  pipeline (Alloy).

## 10. Testing strategy

### Unit (leadgen-pipeline)

- `test_creates_new_contact`
- `test_updates_existing_contact_by_source_id`
- `test_adopts_source_id_when_matched_by_email`
- `test_fill_if_empty_does_not_overwrite_existing_fields`
- `test_idempotent_on_second_run` (no duplicate tag rows)
- `test_skips_row_without_email`
- `test_per_row_exception_does_not_abort_batch`
- `test_advisory_lock_serializes_runs`

### Unit (aitransformers-platform)

- `test_leads_export_requires_admin_auth`
- `test_leads_export_pagination_returns_next_offset`
- `test_leads_export_last_page_returns_null_next_offset`
- `test_leads_export_returns_expected_fields`

### Manual prod validation (acceptance gate)

1. Both PRs merged to main; auto-deploy completes.
2. Run `flask sync-aitransformers` once in prod (`docker exec` into the
   API container or trigger the cron unit manually).
3. Verify counts:

   ```sql
   SELECT COUNT(*) AS tagged_contacts
   FROM contact_tag_assignments cta
   JOIN tags t ON t.id = cta.tag_id
   JOIN tenants te ON te.id = t.tenant_id
   WHERE te.slug = 'visionvolve'
     AND t.name = 'AITransformers';
   ```

4. Log in to `https://leadgen.visionvolve.com/visionvolve/` as a
   Visionvolve admin, navigate to Contacts, filter by tag `AITransformers`
   — list renders, count matches the SQL above.

## 11. Security & compliance

- New service token (`AITRANSFORMERS_ADMIN_TOKEN`) stored as a secret only
  (prod `.env`, GHA secret). Never committed.
- Endpoint requires admin auth — no public exposure of user lists.
- Imported data already lives in our own systems (AITransformers DB →
  leadgen DB). No new third-party data sharing.
- GDPR: imported users already consented to AITransformers ToS; the
  campaign sender (Visionvolve) must continue to honor unsubscribe
  preferences. `newsletter_subscribed=false` users are imported but
  flagged in metadata; the campaign layer (out of scope for this spec)
  is responsible for honoring it.

## 12. Rollout plan

1. Open PR on `aitransformers-platform` from `staging` with admin endpoint + tests.
2. Open PR on `leadgen-pipeline` from `staging` with sync module + CLI + tests.
3. Both PRs pass CI + code review + security scan.
4. Merge `aitransformers-platform` PR first → auto-deploy.
5. Merge `leadgen-pipeline` PR → staging deploy.
6. Run staging sync against AITransformers staging (or prod if staging IAM is shared); verify rows + filterability.
7. Promote both to prod via staging → main PRs.
8. Run one prod sync.
9. Cron picks up daily at 03:00 UTC from that point on.

## 13. Open questions deferred to planning

Resolved during BL-1200 implementation (2026-05-13):

- **Contact schema** (`api/models.py:654`):
  - `email` → real column is **`email_address`**.
  - `title` → real column is **`job_title`**.
  - `source` / `source_id` → **do not exist**. We use the existing
    `import_source` TEXT column (set to `"aitransformers"`) and store the
    stable IAM id in `custom_fields["aitransformers"]["iam_id"]` for the
    primary upsert key.
  - `company` → no column on `Contact`. v1 stores the AITransformers
    `company` string in `custom_fields["aitransformers"]["company"]`. No
    `Company` row is created. The campaign layer can promote later.
  - `metadata` → the existing JSONB column is **`custom_fields`**.
    `industry`, `company_size`, `maturity_level`, `tier`,
    `is_founding_member`, `newsletter_subscribed`, and `synced_at` all
    nest under `custom_fields["aitransformers"]`.
  - `first_name` is **NOT NULL** — sync defaults to the local part of
    the email when the AITransformers row has no name at all.
  - Tag join: `ContactTagAssignment` has a unique constraint on
    `(contact_id, tag_id)`. We INSERT via raw SQL with
    `ON CONFLICT DO NOTHING` (the existing pattern at
    `api/routes/bulk_routes.py:163` — works on Postgres and degrades
    gracefully on the SQLite test backend).
- **Advisory lock**: no existing helper. We added a minimal context
  manager that issues `pg_try_advisory_lock(hashtext(...))` on Postgres
  and is a no-op on SQLite (tests), so overlapping runs are serialized in
  prod but tests stay clean.
- **Cron registration mechanism**: no in-container cron framework is in
  use today. The closest precedent is the GitHub-Actions-dispatched
  reconciler stub (`.github/workflows/resend-reconcile.yml`). We added
  the analogous `aitransformers-sync.yml` workflow with a daily
  `cron: '0 3 * * *'` schedule + manual dispatch, plus a documented
  `docker exec leadgen-api flask sync-aitransformers` invocation. Final
  SSH wiring is a small follow-up that mirrors the resend reconciler.
- **Owner assignment**: left blank in v1. Campaign layer can backfill.

---

**Approval log:**
- Section 1 (architecture) — approved 2026-05-13
- Section 2 (data flow & identity) — approved 2026-05-13
- Sections 3 & 4 (failure / cron / testing) — defaults accepted under
  autonomous-execution directive 2026-05-13
