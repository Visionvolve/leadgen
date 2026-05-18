"""Hunter.io contact-enrichment batch runner (BL-1212).

Resumable, idempotent CLI for finding emails for the Visionvolve tenant's
emailless contacts. Mirrors the shape of ``scripts/wave2_email_finding.py``
but talks to Hunter.io instead of Perplexity + SMTP.

Three modes
-----------

``email-finder``
    1 search credit per contact. Best when the unique-domain count is high
    relative to the contact count (one contact per company).

``domain-search``
    1 search credit per *domain* (returns up to 100 emails). Best when many
    contacts share a domain — we hydrate by matching first/last name
    against the returned roster.

``auto`` (default)
    Counts unique domains in the candidate set first and picks the mode
    that minimises projected credit spend. The rule of thumb:

    *   ``unique_domains <= 600``: domain-search.
    *   ``unique_domains > 800``: email-finder.
    *   In between: domain-search but capped at ``--max-credits``.

Safety
------

* ``--dry-run`` makes zero API calls and zero DB writes; it prints the
  candidate plan, the strategy decision, and the projected spend.
* ``--max-credits`` is a hard cap. The runner stops as soon as the
  service credit total reaches this number.
* Idempotency: writes are ``INSERT ... ON CONFLICT (contact_id, source,
  method) DO NOTHING``. Re-running the same source tag adds zero rows.
* The runner NEVER mutates ``contacts``, ``contact_enrichment``,
  ``campaigns``, ``campaign_contacts``, or ``messages``.

Local-dev usage::

    bash scripts/init-env.sh                       # loads HUNTER_API_KEY into .env.dev
    bash scripts/db-tunnel.sh &                    # localhost:5433 -> prod RDS
    PGPASSWORD=... python3 scripts/hunter_enrichment_run.py \
        --tenant visionvolve --limit 10 --mode auto \
        --max-credits 10 --source hunter-pilot-2026-05-18
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

# Make the api package importable when run from a checkout.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.services.hunter_enrichment import (  # noqa: E402
    DomainSearchResult,
    EmailFinderResult,
    HunterAuthError,
    HunterEnrichmentService,
    HunterError,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TENANT_SLUGS = {
    "visionvolve": "8f7d2027-3e09-4db7-b607-6c1424038a54",
}
EXCLUDED_CAMPAIGN_ID = "389a02a6-3a58-48cd-b47b-927649631d92"

DEFAULT_SOURCE_TAG = f"hunter-{time.strftime('%Y-%m-%d')}"
DOMAIN_SEARCH_CAP = 600  # auto threshold — below this, prefer domain-search
EMAIL_FINDER_FLOOR = 800  # above this, prefer email-finder

logger = logging.getLogger("hunter_enrichment_run")


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    contact_id: str
    first_name: str
    last_name: str
    domain: str


CANDIDATE_SQL = """
    SELECT
        ct.id::text AS contact_id,
        COALESCE(ct.first_name, '') AS first_name,
        COALESCE(ct.last_name, '')  AS last_name,
        COALESCE(c.domain, '')       AS domain
    FROM contacts ct
    JOIN companies c
      ON c.id = ct.company_id
     AND c.tenant_id = ct.tenant_id
    WHERE ct.tenant_id = %(tenant_id)s::uuid
      AND (
            ct.email_address IS NULL
         OR ct.email_address = ''
         OR ct.email_address NOT ILIKE '%%@%%'
      )
      AND ct.first_name IS NOT NULL AND ct.first_name <> ''
      AND ct.last_name  IS NOT NULL AND ct.last_name  <> ''
      AND c.domain IS NOT NULL AND c.domain <> ''
      AND NOT EXISTS (
            SELECT 1 FROM campaign_contacts cc
            WHERE cc.campaign_id = %(excluded_campaign)s::uuid
              AND cc.contact_id  = ct.id
      )
      AND NOT EXISTS (
            SELECT 1 FROM contact_enrichment_hunter h
            WHERE h.contact_id = ct.id
              AND h.source     = %(source)s
      )
    ORDER BY ct.updated_at DESC
    LIMIT %(limit)s
"""


def normalise_domain(value: str) -> str:
    """Strip protocol, www., trailing slash and path. Lowercase."""
    s = (value or "").strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = s.split("/", 1)[0]
    if s.startswith("www."):
        s = s[4:]
    return s.rstrip(".")


def normalise_name(value: str) -> str:
    """Lower, strip diacritics, alpha-only — for fuzzy hydrating."""
    nf = unicodedata.normalize("NFD", value or "")
    cleaned = "".join(ch for ch in nf if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", cleaned.lower())


def fetch_candidates(
    cur: psycopg2.extensions.cursor,
    tenant_id: str,
    source_tag: str,
    limit: int,
) -> list[Candidate]:
    cur.execute(
        CANDIDATE_SQL,
        {
            "tenant_id": tenant_id,
            "excluded_campaign": EXCLUDED_CAMPAIGN_ID,
            "source": source_tag,
            "limit": limit,
        },
    )
    out: list[Candidate] = []
    for row in cur.fetchall():
        domain = normalise_domain(row["domain"])
        if not domain:
            continue
        out.append(
            Candidate(
                contact_id=row["contact_id"],
                first_name=row["first_name"],
                last_name=row["last_name"],
                domain=domain,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


@dataclass
class StrategyDecision:
    chosen: str  # 'email-finder' or 'domain-search'
    unique_domains: int
    total_candidates: int
    projected_credits: int
    rationale: str


def decide_strategy(
    candidates: list[Candidate], mode: str, max_credits: int
) -> StrategyDecision:
    """Pick a Hunter endpoint based on the candidate set + mode flag."""
    total = len(candidates)
    domains = {c.domain for c in candidates}
    unique_domains = len(domains)

    if mode == "email-finder":
        return StrategyDecision(
            chosen="email-finder",
            unique_domains=unique_domains,
            total_candidates=total,
            projected_credits=min(total, max_credits),
            rationale="forced via --mode email-finder",
        )
    if mode == "domain-search":
        return StrategyDecision(
            chosen="domain-search",
            unique_domains=unique_domains,
            total_candidates=total,
            projected_credits=min(unique_domains, max_credits),
            rationale="forced via --mode domain-search",
        )

    # mode == 'auto'
    if unique_domains <= DOMAIN_SEARCH_CAP:
        rationale = (
            f"auto: {unique_domains} unique domains <= {DOMAIN_SEARCH_CAP} "
            f"-> domain-search (1 credit per domain returns roster)"
        )
        return StrategyDecision(
            chosen="domain-search",
            unique_domains=unique_domains,
            total_candidates=total,
            projected_credits=min(unique_domains, max_credits),
            rationale=rationale,
        )
    if unique_domains >= EMAIL_FINDER_FLOOR:
        rationale = (
            f"auto: {unique_domains} unique domains >= {EMAIL_FINDER_FLOOR} "
            f"-> email-finder (per-contact lookup is cheaper than fetching "
            f"a roster we'll mostly discard)"
        )
        return StrategyDecision(
            chosen="email-finder",
            unique_domains=unique_domains,
            total_candidates=total,
            projected_credits=min(total, max_credits),
            rationale=rationale,
        )
    rationale = (
        f"auto: {unique_domains} unique domains in mid-band "
        f"({DOMAIN_SEARCH_CAP}-{EMAIL_FINDER_FLOOR}) -> domain-search, "
        f"capped at --max-credits"
    )
    return StrategyDecision(
        chosen="domain-search",
        unique_domains=unique_domains,
        total_candidates=total,
        projected_credits=min(unique_domains, max_credits),
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# DB writes
# ---------------------------------------------------------------------------


INSERT_SQL = """
    INSERT INTO contact_enrichment_hunter
        (contact_id, tenant_id, domain, found_email, confidence_score,
         position, sources_count, verification_status, method, raw_response,
         credits_used, source)
    VALUES
        (%(contact_id)s, %(tenant_id)s, %(domain)s, %(found_email)s,
         %(confidence_score)s, %(position)s, %(sources_count)s,
         %(verification_status)s, %(method)s, %(raw_response)s::jsonb,
         %(credits_used)s, %(source)s)
    ON CONFLICT (contact_id, source, method) DO NOTHING
"""


def insert_row(
    conn: psycopg2.extensions.connection,
    *,
    tenant_id: str,
    source_tag: str,
    method: str,
    candidate: Candidate,
    email: str | None,
    score: int | None,
    position: str | None,
    sources_count: int | None,
    verification_status: str | None,
    raw_response: dict[str, Any],
    credits_used: int,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            INSERT_SQL,
            {
                "contact_id": candidate.contact_id,
                "tenant_id": tenant_id,
                "domain": candidate.domain,
                "found_email": email,
                "confidence_score": score,
                "position": position,
                "sources_count": sources_count,
                "verification_status": verification_status,
                "method": method,
                "raw_response": json.dumps(raw_response),
                "credits_used": credits_used,
                "source": source_tag,
            },
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Domain-search hydration
# ---------------------------------------------------------------------------


def best_email_for_contact(
    contact: Candidate, roster: DomainSearchResult
) -> tuple[str | None, int | None, str | None, str | None]:
    """Pick the best email from a domain-search roster for a contact.

    Returns (email, confidence, position, verification_status).
    """
    target_first = normalise_name(contact.first_name)
    target_last = normalise_name(contact.last_name)

    exact: tuple[Any, ...] | None = None
    last_only: tuple[Any, ...] | None = None
    first_only: tuple[Any, ...] | None = None

    for entry in roster.emails:
        en_first = normalise_name(entry.first_name or "")
        en_last = normalise_name(entry.last_name or "")
        if en_first == target_first and en_last == target_last:
            exact = (
                entry.value,
                entry.confidence,
                entry.position,
                entry.verification_status,
            )
            break
        if en_last == target_last and last_only is None:
            last_only = (
                entry.value,
                entry.confidence,
                entry.position,
                entry.verification_status,
            )
        elif en_first == target_first and first_only is None:
            first_only = (
                entry.value,
                entry.confidence,
                entry.position,
                entry.verification_status,
            )

    picked = exact or last_only or first_only
    if picked is None:
        return (None, None, None, None)
    return picked  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Mode runners
# ---------------------------------------------------------------------------


def run_email_finder_mode(
    svc: HunterEnrichmentService,
    conn: psycopg2.extensions.connection | None,
    tenant_id: str,
    source_tag: str,
    candidates: list[Candidate],
    max_credits: int,
    dry_run: bool,
    progress_every: int,
) -> dict[str, int]:
    stats: Counter[str] = Counter()
    for i, c in enumerate(candidates, 1):
        if svc.get_credits_used()["total"] >= max_credits:
            logger.info(
                "max-credits %d reached; stopping at contact %d", max_credits, i
            )
            break
        if dry_run:
            stats["would_call"] += 1
            logger.info(
                "[dry-run] %d/%d email-finder %s %s @ %s",
                i,
                len(candidates),
                c.first_name,
                c.last_name,
                c.domain,
            )
            continue
        try:
            result: EmailFinderResult = svc.find_email(
                c.domain, c.first_name, c.last_name
            )
        except HunterError as exc:
            logger.warning(
                "find_email failed for %s %s @ %s: %s",
                c.first_name,
                c.last_name,
                c.domain,
                exc,
            )
            stats["errors"] += 1
            continue
        if result.email:
            stats["found"] += 1
        else:
            stats["no_email"] += 1
        if conn is not None:
            insert_row(
                conn,
                tenant_id=tenant_id,
                source_tag=source_tag,
                method="email-finder",
                candidate=c,
                email=result.email,
                score=result.score,
                position=result.position,
                sources_count=result.sources_count,
                verification_status=result.verification_status,
                raw_response=result.raw,
                credits_used=1,
            )
        if i % progress_every == 0:
            logger.info(
                "progress: %d/%d processed, %d found, %d no-email, %d errors, "
                "credits=%d",
                i,
                len(candidates),
                stats["found"],
                stats["no_email"],
                stats["errors"],
                svc.get_credits_used()["total"],
            )
    return dict(stats)


def run_domain_search_mode(
    svc: HunterEnrichmentService,
    conn: psycopg2.extensions.connection | None,
    tenant_id: str,
    source_tag: str,
    candidates: list[Candidate],
    max_credits: int,
    dry_run: bool,
    progress_every: int,
) -> dict[str, int]:
    """Group contacts by domain, call domain-search once per domain, hydrate."""
    by_domain: dict[str, list[Candidate]] = {}
    for c in candidates:
        by_domain.setdefault(c.domain, []).append(c)

    domains = sorted(by_domain)
    stats: Counter[str] = Counter()

    for di, domain in enumerate(domains, 1):
        if svc.get_credits_used()["total"] >= max_credits:
            logger.info(
                "max-credits %d reached; stopping at domain %d/%d",
                max_credits,
                di,
                len(domains),
            )
            break

        domain_contacts = by_domain[domain]
        if dry_run:
            stats["would_call"] += 1
            logger.info(
                "[dry-run] %d/%d domain-search %s (%d contacts to hydrate)",
                di,
                len(domains),
                domain,
                len(domain_contacts),
            )
            continue

        try:
            roster = svc.domain_search(domain, limit=100)
        except HunterError as exc:
            logger.warning("domain_search failed for %s: %s", domain, exc)
            stats["errors"] += 1
            continue

        for c in domain_contacts:
            email, score, position, vs = best_email_for_contact(c, roster)
            if email:
                stats["found"] += 1
            else:
                stats["no_match"] += 1
            if conn is not None:
                # credits_used=1 only on the FIRST insert per domain — Hunter
                # charges per call, not per hydrated contact. We attribute
                # that 1 credit to the first contact and 0 to the rest so
                # SUM(credits_used) ≈ total Hunter spend.
                attributed = 1 if c is domain_contacts[0] else 0
                insert_row(
                    conn,
                    tenant_id=tenant_id,
                    source_tag=source_tag,
                    method="domain-search",
                    candidate=c,
                    email=email,
                    score=score,
                    position=position,
                    sources_count=roster.total,
                    verification_status=vs,
                    raw_response={
                        "domain_total": roster.total,
                        "organization": roster.organization,
                        "matched_email": email,
                        "matched_confidence": score,
                        # Keep the raw roster only on the first row to avoid
                        # ballooning DB size when many contacts share a domain.
                        "raw": roster.raw if attributed == 1 else None,
                    },
                    credits_used=attributed,
                )

        if di % progress_every == 0:
            logger.info(
                "progress: %d/%d domains, %d found, %d no-match, %d errors, credits=%d",
                di,
                len(domains),
                stats["found"],
                stats["no_match"],
                stats["errors"],
                svc.get_credits_used()["total"],
            )

    return dict(stats)


# ---------------------------------------------------------------------------
# Env loading (mirrors wave2 helper)
# ---------------------------------------------------------------------------


def load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env.dev"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Hunter.io contact-enrichment runner")
    p.add_argument(
        "--tenant", default="visionvolve", help="tenant slug (default: visionvolve)"
    )
    p.add_argument(
        "--mode",
        choices=["email-finder", "domain-search", "auto"],
        default="auto",
        help="which Hunter endpoint to drive",
    )
    p.add_argument(
        "--limit", type=int, default=200, help="max candidates to load from DB"
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="(reserved; runner is single-threaded)",
    )
    p.add_argument(
        "--max-credits",
        type=int,
        default=100,
        help="hard cap on Hunter credits spent in this run",
    )
    p.add_argument(
        "--source",
        default=DEFAULT_SOURCE_TAG,
        help="batch tag persisted to contact_enrichment_hunter.source (default: hunter-YYYY-MM-DD)",
    )
    p.add_argument("--dry-run", action="store_true", help="no API calls, no DB writes")
    p.add_argument(
        "--progress-every", type=int, default=10, help="emit progress every N items"
    )
    p.add_argument("--db-host", default="localhost")
    p.add_argument(
        "--db-port",
        type=int,
        default=int(os.environ.get("PGPORT", "5433")),
        help="(default: 5433 — `bash scripts/db-tunnel.sh` opens that port to prod RDS)",
    )
    p.add_argument("--db-name", default=os.environ.get("PGDATABASE", "leadgen"))
    p.add_argument("--db-user", default=os.environ.get("PGUSER", "dbmasteruser"))
    p.add_argument(
        "--db-password-env",
        default="PGPASSWORD",
        help="env var holding the DB password",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    load_env()

    tenant_id = TENANT_SLUGS.get(args.tenant)
    if not tenant_id:
        logger.error(
            "unknown tenant slug %r (known: %s)", args.tenant, list(TENANT_SLUGS)
        )
        return 2

    api_key = os.environ.get("HUNTER_API_KEY", "")
    if not api_key and not args.dry_run:
        logger.error(
            "HUNTER_API_KEY env var not set. Source it via scripts/init-env.sh or set on the container."
        )
        return 2

    pgpass = os.environ.get(args.db_password_env, "")
    if not pgpass and not args.dry_run:
        logger.error("$%s not set", args.db_password_env)
        return 2

    conn: psycopg2.extensions.connection | None = None
    candidates: list[Candidate]

    if args.dry_run and not pgpass:
        logger.info("[dry-run] no DB password set — using empty candidate list")
        candidates = []
    else:
        conn = psycopg2.connect(
            host=args.db_host,
            port=args.db_port,
            dbname=args.db_name,
            user=args.db_user,
            password=pgpass,
            sslmode="require",
            connect_timeout=15,
        )
        conn.autocommit = False
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        candidates = fetch_candidates(cur, tenant_id, args.source, args.limit)
        cur.close()

    if not candidates:
        logger.info(
            "no candidates to process (already-enriched + filters left nothing)"
        )
        if conn is not None:
            conn.close()
        return 0

    decision = decide_strategy(candidates, args.mode, args.max_credits)
    logger.info(
        "candidates=%d unique_domains=%d strategy=%s projected_credits=%d rationale=%s",
        decision.total_candidates,
        decision.unique_domains,
        decision.chosen,
        decision.projected_credits,
        decision.rationale,
    )

    if args.dry_run:
        logger.info("[dry-run] strategy decided; no API calls or DB writes will occur")

    # Drop the connection during the API loop in dry-run mode — we don't
    # need it open and it makes test runs simpler.
    db_conn = None if args.dry_run else conn

    try:
        svc = (
            HunterEnrichmentService(api_key=api_key)
            if not args.dry_run
            else HunterEnrichmentService(api_key="dry-run-placeholder")
        )

        if decision.chosen == "email-finder":
            stats = run_email_finder_mode(
                svc,
                db_conn,
                tenant_id,
                args.source,
                candidates,
                args.max_credits,
                args.dry_run,
                args.progress_every,
            )
        else:
            stats = run_domain_search_mode(
                svc,
                db_conn,
                tenant_id,
                args.source,
                candidates,
                args.max_credits,
                args.dry_run,
                args.progress_every,
            )
    except HunterAuthError as exc:
        logger.error("Hunter auth failure: %s", exc)
        if conn is not None:
            conn.close()
        return 3
    finally:
        if conn is not None:
            conn.close()

    credits = svc.get_credits_used() if not args.dry_run else {"total": 0}
    logger.info("done. stats=%s credits=%s", stats, credits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
