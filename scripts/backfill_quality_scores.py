"""Backfill quality scores for existing enrichment data that predates the quality scoring feature."""

import sys
sys.path.insert(0, '.')

from api.services.quality_scoring import assess_block_quality, BLOCK_FIELD_SPECS
from api import create_app
from api.models import db
import json

app = create_app()

with app.app_context():
    print("=" * 70)
    print("BACKFILL: Company Enrichment Quality Scores")
    print("=" * 70)

    # ---- L1 (already scored for united-arts, but check for any NULLs) ----
    rows = db.session.execute(db.text("""
        SELECT l1.company_id, c.name, l1.triage_notes, l1.pre_score, l1.confidence, l1.quality_score
        FROM company_enrichment_l1 l1
        JOIN companies c ON l1.company_id = c.id
        JOIN tenants t ON c.tenant_id = t.id
        WHERE t.slug = 'united-arts' AND l1.quality_score IS NULL
    """)).fetchall()
    print(f"\nL1 blocks needing scoring: {len(rows)}")
    for row in rows:
        # L1 doesn't have a block spec in BLOCK_FIELD_SPECS, score based on triage_notes
        triage_notes = row[2] or ''
        confidence = float(row[4]) if row[4] is not None else 0.5
        flags = []
        if not triage_notes or triage_notes.strip().lower() in ('unverified', 'unknown', ''):
            flags.append('summary_too_short')
        data = {'triage_notes': triage_notes, 'pre_score': row[3]}
        # Manual scoring since L1 isn't in BLOCK_FIELD_SPECS
        fc = 1.0 if triage_notes and triage_notes.strip().lower() not in ('unverified', 'unknown', '') else 0.0
        from api.services.quality_scoring import compute_quality_score
        score = compute_quality_score(fc, confidence, flags)
        db.session.execute(db.text("""
            UPDATE company_enrichment_l1
            SET quality_score = :qs, confidence = :conf, qc_flags = CAST(:flags AS jsonb)
            WHERE company_id = :cid
        """), {
            'qs': score, 'conf': confidence,
            'flags': json.dumps(flags), 'cid': str(row[0])
        })
        print(f"  L1 {row[1]}: score={score}, confidence={confidence}, flags={flags}")

    # ---- L2 Profile ----
    rows = db.session.execute(db.text("""
        SELECT p.company_id, c.name,
               p.company_intel, p.key_products, p.customer_segments,
               p.competitors, p.tech_stack, p.leadership_team, p.certifications
        FROM company_enrichment_profile p
        JOIN companies c ON p.company_id = c.id
        JOIN tenants t ON c.tenant_id = t.id
        WHERE t.slug = 'united-arts' AND p.quality_score IS NULL
    """)).fetchall()
    print(f"\nL2 Profile blocks needing scoring: {len(rows)}")
    for row in rows:
        data = {
            'company_intel': row[2], 'key_products': row[3], 'customer_segments': row[4],
            'competitors': row[5], 'tech_stack': row[6], 'leadership_team': row[7],
            'certifications': row[8],
        }
        quality = assess_block_quality(data, 'l2_profile', confidence=0.5, extra_flags=[])
        db.session.execute(db.text("""
            UPDATE company_enrichment_profile
            SET quality_score = :qs, confidence = :conf, qc_flags = CAST(:flags AS jsonb)
            WHERE company_id = :cid
        """), {
            'qs': quality.quality_score, 'conf': quality.confidence,
            'flags': json.dumps(quality.qc_flags), 'cid': str(row[0])
        })
        print(f"  Profile {row[1]}: score={quality.quality_score}, coverage={quality.field_coverage:.0%}, flags={quality.qc_flags}")

    # ---- Signals ----
    signal_fields = BLOCK_FIELD_SPECS.get('signals', [])
    rows = db.session.execute(db.text("""
        SELECT s.company_id, c.name,
               s.digital_initiatives, s.leadership_changes, s.hiring_signals,
               s.ai_hiring, s.tech_partnerships, s.ai_adoption_level,
               s.growth_indicators, s.job_posting_count, s.digital_maturity_score,
               s.it_spend_indicators
        FROM company_enrichment_signals s
        JOIN companies c ON s.company_id = c.id
        JOIN tenants t ON c.tenant_id = t.id
        WHERE t.slug = 'united-arts' AND s.quality_score IS NULL
    """)).fetchall()
    print(f"\nSignals blocks needing scoring: {len(rows)}")
    for row in rows:
        data = {
            'digital_initiatives': row[2], 'leadership_changes': row[3],
            'hiring_signals': row[4], 'ai_hiring': row[5],
            'tech_partnerships': row[6], 'ai_adoption_level': row[7],
            'growth_indicators': row[8], 'job_posting_count': row[9],
            'digital_maturity_score': row[10], 'it_spend_indicators': row[11],
        }
        quality = assess_block_quality(data, 'signals', confidence=0.5, extra_flags=[])
        db.session.execute(db.text("""
            UPDATE company_enrichment_signals
            SET quality_score = :qs, confidence = :conf, qc_flags = CAST(:flags AS jsonb)
            WHERE company_id = :cid
        """), {
            'qs': quality.quality_score, 'conf': quality.confidence,
            'flags': json.dumps(quality.qc_flags), 'cid': str(row[0])
        })
        print(f"  Signals {row[1]}: score={quality.quality_score}, coverage={quality.field_coverage:.0%}, flags={quality.qc_flags}")

    # ---- Market (news) ----
    rows = db.session.execute(db.text("""
        SELECT m.company_id, c.name,
               m.recent_news, m.press_releases, m.media_sentiment,
               m.thought_leadership, m.funding_history
        FROM company_enrichment_market m
        JOIN companies c ON m.company_id = c.id
        JOIN tenants t ON c.tenant_id = t.id
        WHERE t.slug = 'united-arts' AND m.quality_score IS NULL
    """)).fetchall()
    print(f"\nMarket/News blocks needing scoring: {len(rows)}")
    for row in rows:
        # Map DB columns to BLOCK_FIELD_SPECS['news'] expected fields
        # news spec: media_mentions, press_releases, sentiment_score, thought_leadership, news_summary
        data = {
            'media_mentions': row[2],  # recent_news -> media_mentions
            'press_releases': row[3],
            'sentiment_score': row[4],  # media_sentiment -> sentiment_score
            'thought_leadership': row[5],
            'news_summary': row[6],  # funding_history -> news_summary (approx)
        }
        quality = assess_block_quality(data, 'news', confidence=0.5, extra_flags=[])
        db.session.execute(db.text("""
            UPDATE company_enrichment_market
            SET quality_score = :qs, confidence = :conf, qc_flags = CAST(:flags AS jsonb)
            WHERE company_id = :cid
        """), {
            'qs': quality.quality_score, 'conf': quality.confidence,
            'flags': json.dumps(quality.qc_flags), 'cid': str(row[0])
        })
        print(f"  Market {row[1]}: score={quality.quality_score}, coverage={quality.field_coverage:.0%}, flags={quality.qc_flags}")

    # ---- Opportunity ----
    rows = db.session.execute(db.text("""
        SELECT o.company_id, c.name,
               o.pain_hypothesis, o.ai_opportunities, o.quick_wins, o.industry_pain_points
        FROM company_enrichment_opportunity o
        JOIN companies c ON o.company_id = c.id
        JOIN tenants t ON c.tenant_id = t.id
        WHERE t.slug = 'united-arts' AND o.quality_score IS NULL
    """)).fetchall()
    print(f"\nOpportunity blocks needing scoring: {len(rows)}")
    for row in rows:
        data = {
            'pain_hypothesis': row[2], 'ai_opportunities': row[3],
            'quick_wins': row[4], 'industry_pain_points': row[5],
        }
        quality = assess_block_quality(data, 'l2_opportunity', confidence=0.5, extra_flags=[])
        db.session.execute(db.text("""
            UPDATE company_enrichment_opportunity
            SET quality_score = :qs, confidence = :conf, qc_flags = CAST(:flags AS jsonb)
            WHERE company_id = :cid
        """), {
            'qs': quality.quality_score, 'conf': quality.confidence,
            'flags': json.dumps(quality.qc_flags), 'cid': str(row[0])
        })
        print(f"  Opportunity {row[1]}: score={quality.quality_score}, coverage={quality.field_coverage:.0%}, flags={quality.qc_flags}")

    # ---- Contact Enrichments ----
    print("\n" + "=" * 70)
    print("BACKFILL: Contact Enrichment Quality Scores")
    print("=" * 70)

    rows = db.session.execute(db.text("""
        SELECT ce.contact_id, ct.first_name || ' ' || ct.last_name as name,
               ce.person_summary, ce.career_trajectory, ce.authority_score,
               ct.seniority_level, ct.department, ct.contact_score,
               ct.ai_champion_score, ct.icp_fit
        FROM contact_enrichment ce
        JOIN contacts ct ON ce.contact_id = ct.id
        JOIN tenants t ON ct.tenant_id = t.id
        WHERE t.slug = 'united-arts'
          AND (ce.block_quality IS NULL OR ce.block_quality = '{}'::jsonb)
    """)).fetchall()
    print(f"\nContacts needing quality scoring: {len(rows)}")

    for row in rows:
        contact_id = row[0]
        name = row[1]

        # Person block
        person_data = {
            'person_summary': row[2],
            'career_trajectory': row[4],  # authority_score used as proxy
            'authority_score': int(row[4]) if row[4] else None,
            'seniority': str(row[5]) if row[5] else None,
            'department': str(row[6]) if row[6] else None,
            'contact_score': int(row[7]) if row[7] else None,
            'icp_fit': str(row[9]) if row[9] and str(row[9]) != 'unknown' else None,
            'role_verified': None,  # Not in our data yet
        }
        person_quality = assess_block_quality(person_data, 'person', confidence=0.5, extra_flags=[])

        # Social block
        social_row = db.session.execute(db.text("""
            SELECT ce.linkedin_profile_summary, ce.twitter_handle, ce.github_username,
                   ce.speaking_engagements, ce.publications
            FROM contact_enrichment ce WHERE ce.contact_id = :cid
        """), {'cid': str(contact_id)}).fetchone()

        social_data = {}
        if social_row:
            social_data = {
                'linkedin_profile_summary': social_row[0],
                'twitter_handle': social_row[1],
                'github_username': social_row[2],
                'speaking_engagements': social_row[3],
                'publications': social_row[4],
                'public_presence_level': None,
                'thought_leadership': None,
            }
        social_quality = assess_block_quality(social_data, 'social', confidence=0.5, extra_flags=[])

        # Career block
        career_row = db.session.execute(db.text("""
            SELECT ce.career_trajectory, ce.previous_companies, ce.education,
                   ce.certifications, ce.expertise_areas
            FROM contact_enrichment ce WHERE ce.contact_id = :cid
        """), {'cid': str(contact_id)}).fetchone()

        career_data = {}
        if career_row:
            career_data = {
                'career_highlights': career_row[0],  # career_trajectory -> career_highlights
                'previous_companies': career_row[1],
                'education': career_row[2],
                'certifications': career_row[3],
                'expertise_areas': career_row[4],
            }
        career_quality = assess_block_quality(career_data, 'career', confidence=0.5, extra_flags=[])

        # Contact details block
        contact_details_row = db.session.execute(db.text("""
            SELECT ct.email_address, ct.phone_number, ct.linkedin_url
            FROM contacts ct WHERE ct.id = :cid
        """), {'cid': str(contact_id)}).fetchone()

        cd_data = {}
        if contact_details_row:
            cd_data = {
                'email': contact_details_row[0],
                'phone': contact_details_row[1],
                'linkedin_url': contact_details_row[2],
                'profile_data_confidence': None,
            }
        cd_quality = assess_block_quality(cd_data, 'contact_details', confidence=0.5, extra_flags=[])

        # Build block_quality JSON
        block_quality = {
            'person': {
                'score': person_quality.quality_score,
                'confidence': person_quality.confidence,
                'flags': person_quality.qc_flags,
                'field_coverage': person_quality.field_coverage,
            },
            'social': {
                'score': social_quality.quality_score,
                'confidence': social_quality.confidence,
                'flags': social_quality.qc_flags,
                'field_coverage': social_quality.field_coverage,
            },
            'career': {
                'score': career_quality.quality_score,
                'confidence': career_quality.confidence,
                'flags': career_quality.qc_flags,
                'field_coverage': career_quality.field_coverage,
            },
            'contact_details': {
                'score': cd_quality.quality_score,
                'confidence': cd_quality.confidence,
                'flags': cd_quality.qc_flags,
                'field_coverage': cd_quality.field_coverage,
            },
        }

        # Compute overall contact quality score (avg of block scores)
        block_scores = [b['score'] for b in block_quality.values() if b['score'] is not None]
        overall_score = round(sum(block_scores) / len(block_scores)) if block_scores else None

        db.session.execute(db.text("""
            UPDATE contact_enrichment
            SET block_quality = CAST(:bq AS jsonb),
                quality_score = :qs,
                confidence = :conf
            WHERE contact_id = :cid
        """), {
            'bq': json.dumps(block_quality),
            'qs': overall_score,
            'conf': 0.5,
            'cid': str(contact_id),
        })

        print(f"  {name}: overall={overall_score}, person={person_quality.quality_score}({person_quality.field_coverage:.0%}), "
              f"social={social_quality.quality_score}({social_quality.field_coverage:.0%}), "
              f"career={career_quality.quality_score}({career_quality.field_coverage:.0%}), "
              f"contact_details={cd_quality.quality_score}({cd_quality.field_coverage:.0%})")

    db.session.commit()
    print("\n" + "=" * 70)
    print("Backfill complete!")
    print("=" * 70)
