"""Seed the three LCC campaign-prep smart lists.

Source: BL-1111 / BL-1112 / BL-1113 (v25 Phase 10 — Campaign Database
Foundations).

Usage::

    python scripts/seed_lcc_smart_lists.py --tenant losers

Idempotent: skips any list whose name already exists for the tenant.

The three lists are filters over the ``companies`` table. They use
``organization_type`` (migration 068, BL-1108) plus geo / engagement
dimensions to define campaign target audiences:

* "CZ agencies that don't know us" — Czech B2B agencies with no prior
  outreach (cold engagement).
* "Cultural event organizers (autumn/winter)" — CZ-leaning public-sector,
  cultural and event-organizer companies.
* "DACH foreign event agencies" — B2B agencies in Germany / Austria /
  Switzerland.

Requires ``DATABASE_URL`` to point at the target database. The tenant is
looked up by ``slug`` first; if no match is found, the script logs the
expected slug and exits non-zero.
"""

import argparse
import os
import sys

# Allow running from repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import create_app  # noqa: E402
from api.models import SmartList, Tenant, db  # noqa: E402


# --------------------------------------------------------------------------- #
#  LCC smart-list definitions
# --------------------------------------------------------------------------- #

# Sources:
#   BL-1111 — Czech B2B agencies, cold (no prior outreach).
#   BL-1112 — Cultural / event organizers, autumn/winter focus.
#   BL-1113 — DACH region B2B agencies.
LCC_SMART_LISTS = [
    {
        "name": "CZ agencies that don't know us",
        "description": (
            "Czech B2B agencies who have never been in an LCC campaign. "
            "Source: BL-1111 (LCC client ask #12, v25 Phase 10)."
        ),
        "target": "company",
        "filters": {
            "organization_type": ["b2b_agency"],
            "geo_region": ["cee"],
            "engagement_status": ["cold"],
        },
    },
    {
        "name": "Cultural event organizers (autumn/winter)",
        "description": (
            "Multi-category event organizers for autumn/winter seasonal "
            "campaigns (Christmas parties, balls). Source: BL-1112 "
            "(LCC client ask #13, v25 Phase 10)."
        ),
        "target": "company",
        "filters": {
            "organization_type": [
                "event_organizer",
                "b2g_cultural",
                "b2g_municipal",
                "non_profit",
            ],
            "geo_region": ["cee"],
        },
    },
    {
        "name": "DACH foreign agencies",
        "description": (
            "International event agencies in DACH region (Germany, Austria, "
            "Switzerland). Source: BL-1113 (LCC client ask #14, v25 Phase 10)."
        ),
        "target": "company",
        "filters": {
            "organization_type": ["b2b_agency"],
            "geo_region": ["dach"],
        },
    },
]


def seed_lcc_lists(tenant_slug: str) -> int:
    """Seed the 3 LCC smart lists for the given tenant. Returns process exit code."""
    app = create_app()
    with app.app_context():
        tenant = Tenant.query.filter_by(slug=tenant_slug, is_active=True).first()
        if not tenant:
            print(
                f"ERROR: No active tenant with slug={tenant_slug!r}. "
                f"Pass --tenant <slug> for an existing tenant.",
                file=sys.stderr,
            )
            return 2

        print(f"Seeding LCC smart lists for tenant '{tenant_slug}' ({tenant.id})")

        created = 0
        skipped = 0
        for spec in LCC_SMART_LISTS:
            existing = SmartList.query.filter_by(
                tenant_id=str(tenant.id),
                name=spec["name"],
            ).first()
            if existing:
                print(f"  SKIP: {spec['name']} (already exists)")
                skipped += 1
                continue

            sl = SmartList(
                tenant_id=str(tenant.id),
                name=spec["name"],
                description=spec["description"],
                target=spec["target"],
                filters=spec["filters"],
            )
            db.session.add(sl)
            try:
                db.session.commit()
                print(
                    f"  CREATE: {spec['name']} "
                    f"(target={spec['target']}, "
                    f"filters={list(spec['filters'].keys())})"
                )
                created += 1
            except Exception as exc:  # noqa: BLE001
                db.session.rollback()
                print(f"  ERROR: {spec['name']} — {exc}", file=sys.stderr)

        print(f"\nDone: {created} created, {skipped} skipped.")
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant",
        required=True,
        help="Tenant slug to seed lists into (e.g. 'losers' for LCC).",
    )
    args = parser.parse_args()
    sys.exit(seed_lcc_lists(args.tenant))


if __name__ == "__main__":
    main()
