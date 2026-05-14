# ADR-011: Resend Open + Click Tracking Is Configured At The Domain, Not Per Send

**Date**: 2026-05-14 | **Status**: Accepted | **Context**: Sprint 25 / AITransformers meetup campaign

## Context

We need open + click tracking for the AITransformers meetup invite campaign (Resend campaign `389a02a6-3a58-48cd-b47b-927649631d92`, 80 contacts) and for every campaign going forward. The expectation coming in was "add `open_tracking: true` / `click_tracking: true` to the Resend send payload" — i.e., per-message flags.

That isn't how Resend's API works. The `POST /emails` endpoint accepts only: `from`, `to`, `cc`, `bcc`, `reply_to`, `subject`, `html`/`text`, `attachments`, `tags`, `headers`, and `scheduled_at`. There is no `tracking` field. Verified directly against Resend's docs via Context7 (`/websites/resend`, May 2026) and by inspecting `GET /emails/{id}` responses on real sends — they expose `last_event`, never a per-email tracking flag.

Tracking is configured **on the domain object** via `PATCH /domains/{id}` with `{open_tracking, click_tracking, tracking_subdomain}`. The flags only activate after a `Tracking` CNAME record (`<sub>.<domain> → links1.resend-dns.com`) is added at the DNS provider and Resend auto-verifies it. From Resend's docs: *"Tracking is active only when both open or click tracking settings are enabled for the domain and a tracking subdomain is configured and successfully verified."*

## Decision

- **No code change** to `api/services/send_service.py` or the `send-test` route. There is no per-send flag to add. Sends continue to go through `resend.Emails.send(...)` with the existing payload shape.
- **Open + click tracking is enabled at the domain layer** for every verified sending domain owned by the relevant tenant's Resend key. Standard tracking subdomain: `track`.
- **Configuration is reproducible** — `scripts/configure_resend_tracking.py` reads a tenant's Resend key from PG (or `RESEND_API_KEY` / `--api-key`) and idempotently flips the flags + emits the CNAME records that must exist for tracking to activate. Re-running the script on an already-configured account is a no-op (Resend caps `tracking_subdomain` mutations to once per 24h).
- **DNS records are an out-of-band operational task** — the script surfaces required CNAMEs on stderr; an operator adds them at the registrar (GoDaddy for `visionvolve.com`, `aitransformers.eu`, `loserscirque.cz`). Until the CNAME verifies, sends still go out and DKIM/SPF stay valid; they just don't get an open pixel or rewritten links. Domain state will read `partially_verified` during this window — that's expected and does not block sending.
- **Event ingestion was already in place** — `api/routes/webhook_routes.py` (lines 36–46, 291–298) already includes `email.opened` and `email.clicked` in `SUPPORTED_EVENTS` and writes `opened_at` / `clicked_at` to `EmailSendLog`. No webhook changes needed.

## Consequences

**Positive**
- Single configuration surface. New campaigns auto-inherit tracking without touching code, as long as they send from a domain whose CNAME has been added.
- The script is callable per tenant — when we onboard a new tenant with its own Resend account we run it once and we're done.
- Sends keep working even while DNS propagates — `partially_verified` doesn't break sending, just tracking. We can launch the AITransformers campaign without tracking and start tracking later if DNS is slow.

**Negative**
- Tracking activation is gated on a DNS change that lives outside this repo, so "ship to prod" requires a manual registrar step.
- Per-campaign tracking opt-out isn't possible at the Resend layer — it's all-or-nothing per domain. If we ever need a no-tracking transactional flow we'd have to send it from a domain (or subdomain) without tracking enabled.

## Operational handoff for AITransformers May 2026 campaign

Resend domain state (2026-05-14, before any DNS work):

| Domain | open / click | tracking_subdomain | CNAME state | sending status |
|---|---|---|---|---|
| visionvolve.com | true / true | track | pending | partially_verified |
| aitransformers.eu | true / true | track | pending | partially_verified |
| loserscirque.cz | true / true | track | pending | partially_verified |

DNS records to add (all CNAMEs point to the same target):

```
track.visionvolve.com    CNAME  links1.resend-dns.com
track.aitransformers.eu  CNAME  links1.resend-dns.com
track.loserscirque.cz    CNAME  links1.resend-dns.com
```

Add at GoDaddy → wait ~minutes for Resend to mark the CNAME `verified` → tracking activates for all subsequent sends. Re-run `python scripts/configure_resend_tracking.py --tenant <slug>` to confirm.

## References

- Resend Domains API: <https://resend.com/docs/api-reference/domains/update-domain>
- Resend tracking concept: <https://resend.com/docs/dashboard/domains/tracking>
- Webhook ingestion already supports `email.opened` / `email.clicked`: `api/routes/webhook_routes.py` lines 36–46, 291–298
- Send payload (unchanged): `api/services/send_service.py:610-633`
- Test-send payload (unchanged): `api/routes/campaign_routes.py:4702-4714`
- Related: ADR-009 (external API patterns), ADR-010 (campaign analytics — consumes the `email.opened` / `email.clicked` events this enables)
