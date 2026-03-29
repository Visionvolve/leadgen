"""Re-run enrichment on united-arts data after extraction bug fixes.

Targets:
- 6 companies that passed triage: L2 profile, signals, news enrichment
- 9 contacts that were enriched: person, social, career, contact_details

Usage:
    cd /path/to/leadgen-pipeline
    python scripts/reenrich_united_arts.py
"""

import sys
import time

sys.path.insert(0, ".")

from api import create_app
from api.models import db
from sqlalchemy import text

app = create_app()

TENANT_SLUG = "united-arts"


def get_triage_passed_companies():
    """Get companies that passed triage (eligible for L2 enrichment)."""
    rows = db.session.execute(
        text("""
            SELECT c.id, c.name, c.status
            FROM companies c
            JOIN tenants t ON c.tenant_id = t.id
            WHERE t.slug = :slug
              AND c.status IN ('triage_passed', 'enriched_l2', 'enrichment_l2_failed')
            ORDER BY c.name
        """),
        {"slug": TENANT_SLUG},
    ).fetchall()
    return [(str(r[0]), r[1], r[2]) for r in rows]


def get_enriched_contacts():
    """Get contacts that have been enriched (person stage done)."""
    rows = db.session.execute(
        text("""
            SELECT ct.id, ct.first_name, ct.last_name, ct.job_title, c.name
            FROM contacts ct
            JOIN companies c ON ct.company_id = c.id
            JOIN tenants t ON c.tenant_id = t.id
            WHERE t.slug = :slug
              AND ct.processed_enrich = true
            ORDER BY c.name, ct.last_name
        """),
        {"slug": TENANT_SLUG},
    ).fetchall()
    return [(str(r[0]), f"{r[1]} {r[2]}", r[3], r[4]) for r in rows]


def clear_company_enrichment(company_ids):
    """Delete existing L2, signals, news enrichment for companies."""
    if not company_ids:
        return
    for cid in company_ids:
        for table in [
            "company_enrichment_l2",
            "company_enrichment_profile",
            "company_enrichment_signals",
            "company_enrichment_market",
            "company_enrichment_opportunity",
            "company_news",
        ]:
            db.session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"),
                {"cid": cid},
            )
    db.session.commit()
    print(f"  Cleared enrichment data for {len(company_ids)} companies")


def clear_contact_enrichment(contact_ids):
    """Delete existing contact enrichment data."""
    if not contact_ids:
        return
    for cid in contact_ids:
        db.session.execute(
            text("DELETE FROM contact_enrichment WHERE contact_id = :cid"),
            {"cid": cid},
        )
    db.session.commit()
    print(f"  Cleared enrichment data for {len(contact_ids)} contacts")


def run_company_enrichment(companies):
    """Run L2, signals, and news enrichment on companies."""
    from api.services.l2_enricher import enrich_l2
    from api.services.news_enricher import enrich_news
    from api.services.signals_enricher import enrich_signals

    results = {}
    for cid, name, status in companies:
        print(f"\n  === {name} (status: {status}) ===")

        # L2 deep research (includes profile, signals split, market, opportunity)
        print("    L2 enrichment...", end=" ", flush=True)
        t0 = time.time()
        r = enrich_l2(cid)
        dt = time.time() - t0
        cost = r.get("enrichment_cost_usd", 0)
        qs = r.get("quality_score", "N/A")
        err = r.get("error")
        if err:
            print(f"ERROR: {err} ({dt:.1f}s)")
        else:
            print(f"score={qs}, cost=${cost:.4f} ({dt:.1f}s)")

        # Standalone signals enrichment (separate from L2 split)
        print("    Signals enrichment...", end=" ", flush=True)
        t0 = time.time()
        r2 = enrich_signals(cid)
        dt = time.time() - t0
        cost2 = r2.get("enrichment_cost_usd", 0)
        qs2 = r2.get("quality_score", "N/A")
        err2 = r2.get("error")
        if err2:
            print(f"ERROR: {err2} ({dt:.1f}s)")
        else:
            print(f"score={qs2}, cost=${cost2:.4f} ({dt:.1f}s)")

        # News enrichment
        print("    News enrichment...", end=" ", flush=True)
        t0 = time.time()
        r3 = enrich_news(cid)
        dt = time.time() - t0
        cost3 = r3.get("enrichment_cost_usd", 0)
        qs3 = r3.get("quality_score", "N/A")
        err3 = r3.get("error")
        if err3:
            print(f"ERROR: {err3} ({dt:.1f}s)")
        else:
            print(f"score={qs3}, cost=${cost3:.4f} ({dt:.1f}s)")

        results[name] = {
            "l2": r,
            "signals": r2,
            "news": r3,
            "total_cost": cost + cost2 + cost3,
        }

    return results


def run_contact_enrichment(contacts):
    """Run person, social, career, contact_details enrichment on contacts."""
    from api.services.career_enricher import enrich_career
    from api.services.contact_details_enricher import enrich_contact_details
    from api.services.person_enricher import enrich_person
    from api.services.social_enricher import enrich_social

    results = {}
    for cid, name, title, company in contacts:
        print(f"\n  === {name} ({title} @ {company}) ===")

        # Person enrichment
        print("    Person enrichment...", end=" ", flush=True)
        t0 = time.time()
        r = enrich_person(cid)
        dt = time.time() - t0
        cost = r.get("enrichment_cost_usd", 0)
        qs = r.get("quality_score", "N/A")
        err = r.get("error")
        if err:
            print(f"ERROR: {err} ({dt:.1f}s)")
        else:
            print(f"score={qs}, cost=${cost:.4f} ({dt:.1f}s)")

        # Social enrichment
        print("    Social enrichment...", end=" ", flush=True)
        t0 = time.time()
        r2 = enrich_social(cid)
        dt = time.time() - t0
        cost2 = r2.get("enrichment_cost_usd", 0)
        qs2 = r2.get("quality_score", "N/A")
        err2 = r2.get("error")
        if err2:
            print(f"ERROR: {err2} ({dt:.1f}s)")
        else:
            print(f"score={qs2}, cost=${cost2:.4f} ({dt:.1f}s)")

        # Career enrichment
        print("    Career enrichment...", end=" ", flush=True)
        t0 = time.time()
        r3 = enrich_career(cid)
        dt = time.time() - t0
        cost3 = r3.get("enrichment_cost_usd", 0)
        qs3 = r3.get("quality_score", "N/A")
        err3 = r3.get("error")
        if err3:
            print(f"ERROR: {err3} ({dt:.1f}s)")
        else:
            print(f"score={qs3}, cost=${cost3:.4f} ({dt:.1f}s)")

        # Contact details enrichment
        print("    Contact details...", end=" ", flush=True)
        t0 = time.time()
        r4 = enrich_contact_details(cid)
        dt = time.time() - t0
        cost4 = r4.get("enrichment_cost_usd", 0)
        qs4 = r4.get("quality_score", "N/A")
        err4 = r4.get("error")
        if err4:
            print(f"ERROR: {err4} ({dt:.1f}s)")
        else:
            print(f"score={qs4}, cost=${cost4:.4f} ({dt:.1f}s)")

        results[name] = {
            "person": r,
            "social": r2,
            "career": r3,
            "contact_details": r4,
            "total_cost": cost + cost2 + cost3 + cost4,
        }

    return results


def print_company_score_table():
    """Query and print company enrichment scores."""
    rows = db.session.execute(
        text("""
            SELECT c.name,
                   l1.quality_score AS l1_score,
                   CASE WHEN c.status IN ('triage_passed','enriched_l2') THEN 'Passed' ELSE c.status END AS triage,
                   p.quality_score AS profile_score,
                   o.quality_score AS opportunity_score,
                   s.quality_score AS signals_score,
                   n.quality_score AS news_score,
                   cn.quality_score AS news_pr_score
            FROM companies c
            JOIN tenants t ON c.tenant_id = t.id
            LEFT JOIN company_enrichment_l1 l1 ON l1.company_id = c.id
            LEFT JOIN company_enrichment_profile p ON p.company_id = c.id
            LEFT JOIN company_enrichment_opportunity o ON o.company_id = c.id
            LEFT JOIN company_enrichment_signals s ON s.company_id = c.id
            LEFT JOIN company_enrichment_market n ON n.company_id = c.id
            LEFT JOIN company_news cn ON cn.company_id = c.id
            WHERE t.slug = :slug
            ORDER BY c.name
        """),
        {"slug": TENANT_SLUG},
    ).fetchall()

    print("\n" + "=" * 100)
    print("COMPANY ENRICHMENT SCORES")
    print("=" * 100)
    print(
        f"{'Company':<25} {'L1':>5} {'Triage':>10} {'Profile':>8} {'Oppty':>6} "
        f"{'Signals':>8} {'Market':>7} {'News/PR':>8}"
    )
    print("-" * 100)
    for r in rows:
        name = r[0][:24]
        l1 = r[1] if r[1] is not None else "-"
        triage = r[2] or "-"
        profile = r[3] if r[3] is not None else "-"
        opp = r[4] if r[4] is not None else "-"
        signals = r[5] if r[5] is not None else "-"
        market = r[6] if r[6] is not None else "-"
        news = r[7] if r[7] is not None else "-"
        print(
            f"{name:<25} {l1:>5} {triage:>10} {profile:>8} {opp:>6} "
            f"{signals:>8} {market:>7} {news:>8}"
        )


def print_contact_score_table():
    """Query and print contact enrichment scores."""
    rows = db.session.execute(
        text("""
            SELECT ct.first_name || ' ' || ct.last_name AS name,
                   c.name AS company,
                   ce.quality_score AS person_score,
                   ce.contact_score,
                   ce.icp_fit,
                   bq.value->>'social' AS social_block,
                   bq.value->>'career' AS career_block,
                   bq.value->>'contact_details' AS details_block
            FROM contacts ct
            JOIN companies c ON ct.company_id = c.id
            JOIN tenants t ON c.tenant_id = t.id
            LEFT JOIN contact_enrichment ce ON ce.contact_id = ct.id
            LEFT JOIN LATERAL (
                SELECT jsonb_build_object(
                    'social', ce.block_quality->'social'->>'quality_score',
                    'career', ce.block_quality->'career'->>'quality_score',
                    'contact_details', ce.block_quality->'contact_details'->>'quality_score'
                ) AS value
            ) bq ON true
            WHERE t.slug = :slug AND ct.processed_enrich = true
            ORDER BY c.name, ct.last_name
        """),
        {"slug": TENANT_SLUG},
    ).fetchall()

    print("\n" + "=" * 100)
    print("CONTACT ENRICHMENT SCORES")
    print("=" * 100)
    print(
        f"{'Contact':<25} {'Company':<20} {'Person':>7} {'Score':>6} "
        f"{'ICP Fit':>12} {'Social':>7} {'Career':>7} {'Details':>8}"
    )
    print("-" * 100)
    for r in rows:
        name = r[0][:24]
        company = (r[1] or "")[:19]
        person = r[2] if r[2] is not None else "-"
        cscore = r[3] if r[3] is not None else "-"
        icp = r[4] or "-"
        social = r[5] or "-"
        career = r[6] or "-"
        details = r[7] or "-"
        print(
            f"{name:<25} {company:<20} {person:>7} {cscore:>6} "
            f"{icp:>12} {social:>7} {career:>7} {details:>8}"
        )


def main():
    with app.app_context():
        print("=" * 70)
        print("RE-ENRICHMENT: United Arts (after extraction bug fixes)")
        print("=" * 70)

        # 1. Get companies and contacts
        companies = get_triage_passed_companies()
        contacts = get_enriched_contacts()
        print(f"\nFound {len(companies)} triage-passed companies")
        print(f"Found {len(contacts)} enriched contacts")

        if not companies and not contacts:
            print("No data to re-enrich. Exiting.")
            return

        # 2. Print BEFORE scores
        print("\n--- BEFORE RE-ENRICHMENT ---")
        print_company_score_table()
        print_contact_score_table()

        # 3. Confirm
        print(
            f"\nWill re-enrich {len(companies)} companies and {len(contacts)} contacts."
        )
        answer = input("Proceed? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

        # 4. Clear existing enrichment data
        print("\nClearing existing enrichment data...")
        company_ids = [c[0] for c in companies]
        contact_ids = [c[0] for c in contacts]
        clear_company_enrichment(company_ids)
        clear_contact_enrichment(contact_ids)

        # 5. Run company enrichment
        total_cost = 0.0
        print("\n--- COMPANY ENRICHMENT ---")
        company_results = run_company_enrichment(companies)
        for name, r in company_results.items():
            total_cost += r["total_cost"]

        # 6. Run contact enrichment
        print("\n--- CONTACT ENRICHMENT ---")
        contact_results = run_contact_enrichment(contacts)
        for name, r in contact_results.items():
            total_cost += r["total_cost"]

        # 7. Print AFTER scores
        print("\n--- AFTER RE-ENRICHMENT ---")
        print_company_score_table()
        print_contact_score_table()

        print(f"\n{'=' * 70}")
        print(f"TOTAL COST: ${total_cost:.4f}")
        print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
