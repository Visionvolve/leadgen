"""One-off backfill: populate campaign_contacts.microsite_partner_token for
all EventFest contacts by asking UA for each invite's current token via
/api/invites/bulk.

Uses the UA bulk endpoint idempotently (find-or-reuse). Respects existing
token values (only backfills NULLs). Commits in batches of 10.

Run:
    docker exec leadgen-api python scripts/backfill_eventfest_tokens.py

Exit status:
    0 — every NULL-token row resolved successfully (DB count == expected total)
    1 — any failures, or DB verification mismatch

Failure details (email + reason) are also written to
    /tmp/backfill_eventfest_tokens_failures.json
for lead review.
"""
from __future__ import annotations

import json
import os
import sys

# Flask app context
from api import create_app
from api.models import Campaign, CampaignContact, Contact, db
from api.services.eventfest_campaign import _extract_token
from api.services.microsite_invites import get_or_create_invite

BATCH_SIZE = 10
EVENTFEST_NAME = "EventFest"
FAILURE_LOG_PATH = "/tmp/backfill_eventfest_tokens_failures.json"


def main() -> int:
    app = create_app()

    microsite_url = os.environ.get("UA_MICROSITE_URL", "")
    api_key = os.environ.get("UA_INVITE_API_KEY", "")
    if not microsite_url or not api_key:
        print(
            "ERROR: UA_MICROSITE_URL and UA_INVITE_API_KEY must be set in the "
            "leadgen-api container environment."
        )
        return 1

    with app.app_context():
        campaign = (
            db.session.query(Campaign).filter_by(name=EVENTFEST_NAME).first()
        )
        if campaign is None:
            print(f"ERROR: no campaign named {EVENTFEST_NAME!r} found")
            return 1
        print(f"Campaign: id={campaign.id} name={campaign.name}")

        total_ef = (
            db.session.query(CampaignContact)
            .filter(CampaignContact.campaign_id == campaign.id)
            .count()
        )
        print(f"Total EventFest campaign_contacts: {total_ef}")

        missing = (
            db.session.query(CampaignContact)
            .filter(
                CampaignContact.campaign_id == campaign.id,
                CampaignContact.microsite_partner_token.is_(None),
            )
            .all()
        )
        print(f"Without token (before): {len(missing)}")

        updated = 0
        failed = 0
        failures: list[dict] = []

        for idx, cc in enumerate(missing, 1):
            contact = db.session.get(Contact, cc.contact_id)
            if contact is None:
                reason = "contact row missing"
                failures.append(
                    {
                        "campaign_contact_id": cc.id,
                        "contact_id": cc.contact_id,
                        "email": None,
                        "reason": reason,
                    }
                )
                print(f"[{idx}/{len(missing)}] cc={cc.id} {reason}")
                failed += 1
                continue

            name = (
                f"{contact.first_name or ''} {contact.last_name or ''}".strip()
                or contact.email_address
            )
            company = getattr(contact, "company_name", None)

            try:
                invite_url = get_or_create_invite(
                    email=contact.email_address,
                    name=name,
                    microsite_url=microsite_url,
                    api_key=api_key,
                    company=company,
                    apply_eventfest_defaults=True,
                )
            except Exception as exc:  # pragma: no cover — defensive
                reason = f"exception: {exc}"
                failures.append(
                    {
                        "campaign_contact_id": cc.id,
                        "contact_id": contact.id,
                        "email": contact.email_address,
                        "reason": reason,
                    }
                )
                print(f"[{idx}/{len(missing)}] {contact.email_address} {reason}")
                failed += 1
                continue

            if not invite_url:
                reason = "UA returned no URL (API unreachable or per-contact error)"
                failures.append(
                    {
                        "campaign_contact_id": cc.id,
                        "contact_id": contact.id,
                        "email": contact.email_address,
                        "reason": reason,
                    }
                )
                print(f"[{idx}/{len(missing)}] {contact.email_address} {reason}")
                failed += 1
                continue

            token = _extract_token(invite_url)
            if not token:
                reason = f"token not parseable from url {invite_url!r}"
                failures.append(
                    {
                        "campaign_contact_id": cc.id,
                        "contact_id": contact.id,
                        "email": contact.email_address,
                        "reason": reason,
                    }
                )
                print(f"[{idx}/{len(missing)}] {contact.email_address} {reason}")
                failed += 1
                continue

            cc.microsite_partner_token = token
            db.session.add(cc)
            updated += 1

            if updated % BATCH_SIZE == 0:
                print(
                    f"[{idx}/{len(missing)}] committing batch: "
                    f"updated={updated} failed={failed}"
                )
                db.session.commit()

        db.session.commit()

        with_token_after = (
            db.session.query(CampaignContact)
            .filter(
                CampaignContact.campaign_id == campaign.id,
                CampaignContact.microsite_partner_token.isnot(None),
            )
            .count()
        )

    print()
    print("===== SUMMARY =====")
    print(f"Total EventFest contacts:        {total_ef}")
    print(f"NULL token before:               {len(missing)}")
    print(f"Updated:                         {updated}")
    print(f"Failed:                          {failed}")
    print(f"With token after (DB verified):  {with_token_after}")

    # Write failure log even if empty, so downstream tooling can diff
    with open(FAILURE_LOG_PATH, "w") as fp:
        json.dump({"failures": failures, "total": total_ef}, fp, indent=2)
    print(f"Failure log:                     {FAILURE_LOG_PATH}")

    # Strict exit status: fail if any row failed OR if DB state is not fully resolved
    if failed > 0:
        print("EXIT 1 — some rows failed; inspect failure log.")
        return 1
    if with_token_after != total_ef:
        print(
            f"EXIT 1 — DB verification mismatch: "
            f"with_token={with_token_after} != total={total_ef}"
        )
        return 1

    print("EXIT 0 — all EventFest campaign_contacts have tokens.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
