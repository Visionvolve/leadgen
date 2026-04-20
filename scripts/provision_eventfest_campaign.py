#!/usr/bin/env python
"""CLI wrapper for `api.services.eventfest_campaign.provision_eventfest_campaign`.

Usage::

    # From a file (one email per line, blank lines + #-comments ignored)
    python scripts/provision_eventfest_campaign.py \\
        --name "EventFest 2026" \\
        --tenant <tenant-uuid> \\
        --file emails.txt

    # From stdin
    cat emails.txt | python scripts/provision_eventfest_campaign.py \\
        --name "EventFest 2026" \\
        --tenant <tenant-uuid>

    # From repeated --email flags
    python scripts/provision_eventfest_campaign.py \\
        --name "EventFest 2026" \\
        --tenant <tenant-uuid> \\
        --email a@x.com --email b@x.com

Exits 0 on success and prints the Campaign id + dashboard URL to stdout.
Exits 1 on missing env vars, missing emails, or unreachable microsite.
"""

from __future__ import annotations

import argparse
import os
import sys


def _read_emails(args: argparse.Namespace) -> list[str]:
    emails: list[str] = []

    if args.email:
        emails.extend(args.email)

    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                emails.append(line)

    if not args.email and not args.file:
        # Read from stdin.
        if sys.stdin.isatty():
            return []
        for raw in sys.stdin:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            emails.append(line)

    return emails


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name", required=True, help="Campaign name (idempotency key within tenant)"
    )
    parser.add_argument("--tenant", required=True, help="Tenant UUID")
    parser.add_argument(
        "--file", help="Path to file with one email per line (# = comment)"
    )
    parser.add_argument(
        "--email",
        action="append",
        help="Single recipient email (repeatable)",
    )
    parser.add_argument(
        "--dashboard-base",
        default=os.environ.get(
            "LEADGEN_DASHBOARD_BASE",
            "https://leadgen-staging.visionvolve.com",
        ),
        help="Dashboard base URL for the printed campaign link",
    )
    args = parser.parse_args(argv)

    emails = _read_emails(args)
    if not emails:
        print("ERROR: no emails supplied (use --file, --email, or stdin)", file=sys.stderr)
        return 1

    # Defer the import so unit tests can stub the service.
    from api import create_app
    from api.services.eventfest_campaign import provision_eventfest_campaign

    app = create_app()
    with app.app_context():
        try:
            campaign_id = provision_eventfest_campaign(
                name=args.name,
                contact_emails=emails,
                tenant_id=args.tenant,
            )
        except Exception as exc:  # noqa: BLE001 — surface anything to operator
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    dashboard = args.dashboard_base.rstrip("/")
    print(f"Campaign {campaign_id} created. Dashboard: {dashboard}/campaigns/{campaign_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
