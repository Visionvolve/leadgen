"""Idempotently enable open + click tracking on every verified Resend
sending domain a given tenant owns.

Why this exists
---------------
Resend's tracking model is **domain-level**, not per-send. The ``POST
/emails`` endpoint accepts no ``tracking`` field — open-pixel injection and
link rewriting are toggled on the *domain object* via ``PATCH /domains/
{id}`` with::

    {"open_tracking": true, "click_tracking": true,
     "tracking_subdomain": "track"}

After the flag flip, Resend returns the CNAME record that must exist
(``track.<domain> → links1.resend-dns.com``) before tracking actually
fires. Until DNS verifies, sends still go out and DKIM/SPF stay valid;
they just don't get an open pixel or rewritten links. See ADR-011 for the
full reasoning.

Run
---
Local (against a tenant's Resend key)::

    python scripts/configure_resend_tracking.py --tenant visionvolve

Against any tenant, with explicit key::

    RESEND_API_KEY=re_xxx python scripts/configure_resend_tracking.py \
        --subdomain track

The script is idempotent — if a domain is already configured with the
desired subdomain + flags, it's left untouched (Resend caps
``tracking_subdomain`` mutations to once per 24h).

Output
------
JSON to stdout::

    {
      "domains": [
        {"name": "visionvolve.com", "id": "...",
         "open_tracking": true, "click_tracking": true,
         "tracking_subdomain": "track", "cname_target": "links1.resend-dns.com",
         "cname_status": "pending", "changed": true}
      ],
      "cnames_required": [
        "track.visionvolve.com  CNAME  links1.resend-dns.com"
      ]
    }

Exit status: 0 on success, 1 on any HTTP error from Resend.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib import error, request

RESEND_BASE = "https://api.resend.com"
DEFAULT_SUBDOMAIN = "track"


def _http(method: str, path: str, api_key: str, body: dict | None = None) -> dict:
    """Minimal urllib client — keeps the script stdlib-only so it runs
    inside the api container without extra deps."""
    url = f"{RESEND_BASE}{path}"
    data = None
    headers = {"Authorization": f"Bearer {api_key}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except error.HTTPError as exc:
        msg = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Resend {method} {path} failed: {exc.code} {msg}") from exc


def list_domains(api_key: str) -> list[dict]:
    return _http("GET", "/domains", api_key).get("data", []) or []


def get_domain(api_key: str, domain_id: str) -> dict:
    return _http("GET", f"/domains/{domain_id}", api_key)


def patch_tracking(api_key: str, domain_id: str, *, subdomain: str) -> None:
    _http(
        "PATCH",
        f"/domains/{domain_id}",
        api_key,
        body={
            "open_tracking": True,
            "click_tracking": True,
            "tracking_subdomain": subdomain,
        },
    )


def cname_target_for(domain: dict) -> tuple[str | None, str | None]:
    """Extract the tracking CNAME (name, status) from a domain record's
    ``records`` array. Returns ``(None, None)`` if Resend hasn't issued a
    tracking record yet."""
    for rec in domain.get("records") or []:
        if rec.get("record") == "Tracking" and rec.get("type") == "CNAME":
            return rec.get("value"), rec.get("status")
    return None, None


def needs_update(domain: dict, subdomain: str) -> bool:
    return not (
        domain.get("open_tracking")
        and domain.get("click_tracking")
        and domain.get("tracking_subdomain") == subdomain
    )


def configure_all(api_key: str, subdomain: str) -> dict[str, Any]:
    results: list[dict] = []
    cnames: list[str] = []

    for summary in list_domains(api_key):
        full = get_domain(api_key, summary["id"])
        if full.get("status") not in ("verified", "partially_verified"):
            # skip unverified domains — patching them would silently fail
            results.append(
                {
                    "name": full.get("name"),
                    "id": full.get("id"),
                    "skipped": "domain_not_verified",
                    "status": full.get("status"),
                    "changed": False,
                }
            )
            continue

        changed = False
        if needs_update(full, subdomain):
            patch_tracking(api_key, full["id"], subdomain=subdomain)
            full = get_domain(api_key, full["id"])
            changed = True

        cname_value, cname_status = cname_target_for(full)
        results.append(
            {
                "name": full.get("name"),
                "id": full.get("id"),
                "open_tracking": full.get("open_tracking"),
                "click_tracking": full.get("click_tracking"),
                "tracking_subdomain": full.get("tracking_subdomain"),
                "cname_target": cname_value,
                "cname_status": cname_status,
                "changed": changed,
            }
        )
        if cname_value and cname_status != "verified":
            cnames.append(
                f"{full.get('tracking_subdomain')}.{full.get('name')}  CNAME  {cname_value}"
            )

    return {"domains": results, "cnames_required": cnames}


def _resolve_api_key(args: argparse.Namespace) -> str:
    """Order of precedence:
    1. --api-key on the CLI
    2. RESEND_API_KEY env var
    3. --tenant <slug> → read from PG tenant settings
    """
    if args.api_key:
        return args.api_key
    env_key = os.environ.get("RESEND_API_KEY")
    if env_key:
        return env_key
    if args.tenant:
        # Lazy-import the Flask app context so this script remains
        # importable in unit tests without an app.
        try:
            from api.app import create_app
            from api.models import Tenant, db
        except ImportError as exc:  # pragma: no cover — only fires outside container
            raise SystemExit(
                "Could not import api.app — run inside the leadgen-api "
                "container or supply --api-key explicitly."
            ) from exc

        app = create_app()
        with app.app_context():
            tenant = (
                db.session.query(Tenant)
                .filter(Tenant.slug == args.tenant)
                .one_or_none()
            )
            if not tenant:
                raise SystemExit(f"Tenant {args.tenant!r} not found")
            settings = tenant.settings or {}
            if isinstance(settings, str):
                settings = json.loads(settings)
            key = (settings or {}).get("resend_api_key")
            if not key:
                raise SystemExit(
                    f"Tenant {args.tenant!r} settings missing resend_api_key"
                )
            return key
    raise SystemExit("Need one of: --api-key, RESEND_API_KEY env, or --tenant <slug>")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tenant", help="Tenant slug to read Resend key from")
    parser.add_argument("--api-key", help="Override Resend API key")
    parser.add_argument(
        "--subdomain",
        default=DEFAULT_SUBDOMAIN,
        help=f"Tracking subdomain (default: {DEFAULT_SUBDOMAIN!r})",
    )
    args = parser.parse_args(argv)

    api_key = _resolve_api_key(args)
    result = configure_all(api_key, args.subdomain)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")

    # Surface the DNS to-do prominently on stderr so it doesn't get lost
    # in JSON parsing pipelines.
    if result["cnames_required"]:
        sys.stderr.write("\nDNS records still required for tracking to activate:\n")
        for line in result["cnames_required"]:
            sys.stderr.write(f"  {line}\n")
        sys.stderr.write(
            "Add them at the domain registrar, then Resend auto-verifies "
            "within minutes.\n"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
