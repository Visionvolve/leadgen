# Hunter.io Enrichment — Strategy Decision (BL-1212)

## Question

For the Visionvolve emailless-contact backlog (~4,300 contacts per the
2026-05-18 secret handoff), which Hunter endpoint minimises credit spend?

| Endpoint        | Cost           | Returns                          |
| --------------- | -------------- | -------------------------------- |
| `email-finder`  | 1 search/call  | 1 email + confidence score       |
| `domain-search` | 1 search/call  | Up to 100 emails for that domain |
| `email-verifier`| 1 verify/call  | Deliverability check             |

The Data-platform plan has **848 search credits + 1000 verification
credits** remaining before the 2027-01-15 reset (`reports/hunter-secret-handoff.md`).

## Decision

`--mode auto` evaluates **at the start of every run** against the actual
candidate set, then chooses one of three paths:

| unique_domains in candidate set | Mode chosen     | Why                                                                   |
| ------------------------------- | --------------- | --------------------------------------------------------------------- |
| <= 600                          | `domain-search` | One roster fetch hydrates many contacts; lowest credits/contact.      |
| 600 < n < 800                   | `domain-search` | Still favourable, but `--max-credits` caps it.                        |
| >= 800                          | `email-finder`  | When most domains have only one contact, the roster is mostly waste.  |

This logic lives in :func:`scripts.hunter_enrichment_run.decide_strategy`
and is overridable via `--mode email-finder` or `--mode domain-search`.

## How the runner produced the number

Each run prints the unique-domain count from the candidate query at
startup, e.g.:

```
candidates=4123 unique_domains=611 strategy=domain-search projected_credits=611 ...
```

That count drives the live decision, so we never need to maintain a
hand-edited number in this doc.

## Strategy decision NOT made up-front against prod

The build session that produced BL-1212 did **not** have prod SSH
access enabled (`claude --prod-access` was not used), so the count
query referenced in the task brief could not be executed locally
against prod. Instead, the runner does the count itself when it
actually has DB access, which is the only place it matters.

For sizing the secret handoff used a heuristic ("we have far fewer
than 4.3k distinct domains") — the runner will print the real number
on the first run.

## Phase 1 pilot (this PR)

* Source tag: `hunter-pilot-2026-05-18`
* Limit: 10 contacts
* Max credits: 10
* Mode: `auto` (will choose domain-search unless prod has wildly more
  unique domains than expected)
* Target DB: production `leadgen` (cohort is the Visionvolve tenant)
* Distinct from the bulk run by source tag — pilot rows are easy to
  roll back via
  `DELETE FROM contact_enrichment_hunter WHERE source = 'hunter-pilot-2026-05-18';`

## Phase 2 bulk run (separate item)

* Source tag: `hunter-bulk-2026-05-18` (or similar)
* Limit: 5000
* Max credits: 800 (preserve ~50-credit head-room before the cycle reset)
* Mode: `auto`
* Verification: spot-check the top-N by `confidence_score` with
  `--mode verify` (separate verification budget).

Bulk run is **not** part of BL-1212; it spawns a follow-up backlog
item once the pilot validates GO.
