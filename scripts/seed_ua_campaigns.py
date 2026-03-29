"""Seed 6 UA demand-gen campaign templates with step sequences.

Usage:
    python scripts/seed_ua_campaigns.py

Requires DATABASE_URL env var pointing to the target database.
Creates campaigns under the 'united-arts' tenant. If the tenant
does not exist, falls back to the first available tenant.
"""

import json
import os
import sys

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import create_app
from api.models import Campaign, CampaignStep, Tenant, db

# ---------------------------------------------------------------------------
# Campaign definitions from the UA demand-gen strategy
# ---------------------------------------------------------------------------

CAMPAIGNS = [
    {
        "name": "P1-A Reactivace aktivnich agentur",
        "description": (
            "Active Agency Reactivation — up-sell from animations to "
            "catalogue/custom shows for agencies with collaboration within last 18 months."
        ),
        "language": "cs",
        "channel": "email",
        "status": "draft",
        "generation_config": {
            "recommended_products": [
                "Glamour in Red",
                "Flying Welcome Drink",
                "Katalogove show 30min",
            ],
            "segment": "agentura",
            "language": "cs",
        },
        "target_criteria": {
            "segment": "agentura",
            "language": "cs",
            "collaboration": "active_18m",
        },
        "steps": [
            {
                "position": 1,
                "day_offset": 0,
                "channel": "email",
                "label": "Osobni podekovaní",
                "condition": "always",
                "config": {
                    "template_subject": "Nové programy od Losers Cirque Company",
                    "template_body": (
                        "Dekujeme za spolupráci na {{last_event}}. "
                        "Pro letošek máme nové animacní programy — "
                        "Glamour in Red a Flying Welcome Drink. "
                        "Krátká ukázka: {{showreel_link}}."
                    ),
                    "tone": "professional",
                    "language": "cs",
                    "personalization_vars": [
                        "last_event",
                        "contact_name",
                        "company_name",
                        "showreel_link",
                    ],
                },
            },
            {
                "position": 2,
                "day_offset": 7,
                "channel": "email",
                "label": "Case study",
                "condition": "always",
                "config": {
                    "template_subject": "Jak jsme oživili akci pro {{similar_client}}",
                    "template_body": (
                        "Konkrétní príklad akce pro podobný typ klienta. "
                        "Co jsme dodali, jak to vypadalo, co rekl klient."
                    ),
                    "tone": "professional",
                    "language": "cs",
                    "personalization_vars": [
                        "similar_client",
                        "contact_name",
                        "company_name",
                    ],
                },
            },
            {
                "position": 3,
                "day_offset": 14,
                "channel": "email",
                "label": "Exkluzivní nabídka",
                "condition": "no_response",
                "config": {
                    "template_subject": "Pozvánka na preview nového show",
                    "template_body": (
                        "Rádi vám ukážeme, co nového umíme — u kávy nebo na naší show."
                    ),
                    "tone": "professional",
                    "language": "cs",
                    "personalization_vars": ["contact_name", "company_name"],
                },
            },
        ],
    },
    {
        "name": "P1-B Reaktivace spícich kontaktu",
        "description": (
            "Sleeping Contact Reactivation — re-engage contacts with 18+ months "
            "without interaction using entry products."
        ),
        "language": "cs",
        "channel": "email",
        "status": "draft",
        "generation_config": {
            "recommended_products": ["Animacní programy", "Živé Sochy"],
            "segment": "agentura",
            "language": "cs",
        },
        "target_criteria": {
            "segment": "agentura",
            "language": "cs",
            "collaboration": "sleeping_18m",
        },
        "steps": [
            {
                "position": 1,
                "day_offset": 0,
                "channel": "email",
                "label": "Co je nového",
                "condition": "always",
                "config": {
                    "template_subject": "Novinky od Losers Cirque Company",
                    "template_body": (
                        "Od ledna vede eventovou komunikaci Hanka Faková. "
                        "Tým se rozrostl, repertoár taky. "
                        "Krátký prehled novinek: {{highlight_reel_link}}."
                    ),
                    "tone": "friendly",
                    "language": "cs",
                    "personalization_vars": [
                        "contact_name",
                        "company_name",
                        "highlight_reel_link",
                    ],
                },
            },
            {
                "position": 2,
                "day_offset": 10,
                "channel": "email",
                "label": "Sezónní nabídka",
                "condition": "always",
                "config": {
                    "template_subject": "Programy pro letní akce",
                    "template_body": (
                        "Pro letní akce: Chudaci od 9.000 Kc/osoba, "
                        "Hrající Chudac od 10.000 Kc."
                    ),
                    "tone": "friendly",
                    "language": "cs",
                    "personalization_vars": ["contact_name", "company_name"],
                },
            },
            {
                "position": 3,
                "day_offset": 21,
                "channel": "email",
                "label": "Poslední pokus",
                "condition": "no_response",
                "config": {
                    "template_subject": "Stále se venujete eventum?",
                    "template_body": (
                        "Stále se venujete eventum? "
                        "Rádi pošleme aktuální nabídku. "
                        "Pokud ne, dejte vedet."
                    ),
                    "tone": "friendly",
                    "language": "cs",
                    "personalization_vars": ["contact_name"],
                },
            },
        ],
    },
    {
        "name": "P2-A Obce — formální outreach",
        "description": (
            "Municipality Formal Outreach — target cultural committees of "
            "municipalities with 5,000+ inhabitants."
        ),
        "language": "cs",
        "channel": "email",
        "status": "draft",
        "generation_config": {
            "recommended_products": ["Chudaci", "Hrající Chudac"],
            "product_prices": {
                "Chudaci": "18,000 Kc (2 os.)",
                "Hrající Chudac": "10,000 Kc",
            },
            "segment": "obec",
            "language": "cs",
            "seasonal_context": "letní akce (kveten-zárí)",
        },
        "target_criteria": {
            "segment": "obec",
            "language": "cs",
            "min_population": 5000,
        },
        "steps": [
            {
                "position": 1,
                "day_offset": 0,
                "channel": "email",
                "label": "Úvodní oslovení",
                "condition": "always",
                "config": {
                    "template_subject": "Program pro {{event_name}} — od 10.000 Kc",
                    "template_body": (
                        "Videli jsme, že {{municipality}} organizuje "
                        "{{event_name}}. Máme program, který vaši akci "
                        "posune na jinou úroven — od 10.000 Kc. "
                        "{{showreel_link}}"
                    ),
                    "tone": "formal",
                    "language": "cs",
                    "personalization_vars": [
                        "municipality",
                        "event_name",
                        "contact_name",
                        "showreel_link",
                    ],
                },
            },
            {
                "position": 2,
                "day_offset": 5,
                "channel": "email",
                "label": "One-pager v príloze",
                "condition": "always",
                "config": {
                    "template_subject": "Nabídka programu pro dny mest",
                    "template_body": (
                        "V príloze posílám one-pager 'Pro dny mest' — "
                        "Chudaci + Hrající Chudac s cenami, reference, fotky."
                    ),
                    "tone": "formal",
                    "language": "cs",
                    "personalization_vars": ["contact_name", "municipality"],
                    "attachments": ["one-pager-pro-dny-mest"],
                },
            },
            {
                "position": 3,
                "day_offset": 10,
                "channel": "call",
                "label": "Telefonát",
                "condition": "always",
                "config": {
                    "template_body": (
                        "Posílal jsem e-mail s nabídkou programu pro "
                        "vaše dny mesta. Mel/a jste možnost se podívat?"
                    ),
                    "tone": "formal",
                    "language": "cs",
                    "personalization_vars": ["contact_name", "municipality"],
                },
            },
            {
                "position": 4,
                "day_offset": 14,
                "channel": "email",
                "label": "Cenová nabídka",
                "condition": "no_response",
                "config": {
                    "template_subject": "Cenová nabídka pro {{event_name}}",
                    "template_body": (
                        "Konkrétní cenová nabídka pro vaši akci + "
                        "nabídka nezávazného callu s Hankou."
                    ),
                    "tone": "formal",
                    "language": "cs",
                    "personalization_vars": [
                        "contact_name",
                        "municipality",
                        "event_name",
                    ],
                },
            },
            {
                "position": 5,
                "day_offset": 21,
                "channel": "email",
                "label": "Follow-up záverecný",
                "condition": "no_response",
                "config": {
                    "template_subject": "Plánujete program na {{season}}?",
                    "template_body": (
                        "Plánujete program na {{season}}? "
                        "Rádi pomužeme. Nechte nám kontakt."
                    ),
                    "tone": "formal",
                    "language": "cs",
                    "personalization_vars": ["contact_name", "season"],
                },
            },
        ],
    },
    {
        "name": "P2-B Spolky — neformální outreach",
        "description": (
            "Clubs/Associations Informal Outreach — target Sokol, Orel, "
            "fire brigades, Rotary/Lions, cultural clubs."
        ),
        "language": "cs",
        "channel": "call",
        "status": "draft",
        "generation_config": {
            "recommended_products": ["Živé Sochy", "Glamour in Red"],
            "product_prices": {
                "Živé Sochy": "10,000 Kc (2 os.)",
                "Glamour in Red": "12,000 Kc (2 os.)",
            },
            "segment": "spolek",
            "language": "cs",
        },
        "target_criteria": {
            "segment": "spolek",
            "language": "cs",
        },
        "steps": [
            {
                "position": 1,
                "day_offset": 0,
                "channel": "call",
                "label": "Úvodní telefonát",
                "condition": "always",
                "config": {
                    "template_body": (
                        "Organizujete letos ples / slavnost? "
                        "Máme program, který jste ješte nevideli — "
                        "elegantní živé sochy nebo akrobatky "
                        "od 10.000 Kc za celý vecer."
                    ),
                    "tone": "informal",
                    "language": "cs",
                    "personalization_vars": ["contact_name", "company_name"],
                },
            },
            {
                "position": 2,
                "day_offset": 1,
                "channel": "email",
                "label": "Follow-up po telefonu",
                "condition": "always",
                "config": {
                    "template_subject": "Nabídka pro váš ples — Živé Sochy a Glamour in Red",
                    "template_body": (
                        "Showreel + one-pager 'Pro spolecenské plesy' "
                        "s Živé Sochy a Glamour in Red."
                    ),
                    "tone": "informal",
                    "language": "cs",
                    "personalization_vars": ["contact_name", "company_name"],
                    "attachments": ["one-pager-pro-plesy"],
                },
            },
            {
                "position": 3,
                "day_offset": 7,
                "channel": "email",
                "label": "Case study",
                "condition": "always",
                "config": {
                    "template_subject": "Jak vypadal ples s naším programem",
                    "template_body": (
                        "Case study z podobné akce (ples, slavnost) + "
                        "konkrétní cena pro váš typ akce."
                    ),
                    "tone": "informal",
                    "language": "cs",
                    "personalization_vars": ["contact_name", "company_name"],
                },
            },
            {
                "position": 4,
                "day_offset": 14,
                "channel": "call",
                "label": "Druhý telefonát",
                "condition": "no_response",
                "config": {
                    "template_body": (
                        "Meli jste cas se podívat? Muzu odpovedět na otázky."
                    ),
                    "tone": "informal",
                    "language": "cs",
                    "personalization_vars": ["contact_name"],
                },
            },
            {
                "position": 5,
                "day_offset": 21,
                "channel": "email",
                "label": "Sleva pro nové",
                "condition": "no_response",
                "config": {
                    "template_subject": "15 % sleva pro nové klienty",
                    "template_body": (
                        "První spolupráce se slevou 15 % "
                        "pro nové klienty z vašeho regionu."
                    ),
                    "tone": "informal",
                    "language": "cs",
                    "personalization_vars": ["contact_name", "company_name"],
                },
            },
        ],
    },
    {
        "name": "P2-C Školy — maturitní plesy",
        "description": (
            "Schools Prom Outreach — target high schools and universities "
            "for January-March prom season. Outreach September-October."
        ),
        "language": "cs",
        "channel": "email",
        "status": "draft",
        "generation_config": {
            "recommended_products": ["Živé Sochy", "Glamour in Red"],
            "product_prices": {"Živé Sochy": "10,000 Kc (2 os.)"},
            "segment": "skola",
            "language": "cs",
            "seasonal_context": "maturitní plesy (leden-brezen)",
        },
        "target_criteria": {
            "segment": "skola",
            "language": "cs",
        },
        "steps": [
            {
                "position": 1,
                "day_offset": 0,
                "channel": "email",
                "label": "Úvodní e-mail",
                "condition": "always",
                "config": {
                    "template_subject": "Program pro váš maturitní ples — od 10.000 Kc",
                    "template_body": (
                        "Plánujete maturitní ples? "
                        "Máme elegantní program pro slavnostní vecer — "
                        "živé sochy od 10.000 Kc. "
                        "Podívejte se: {{showreel_indoor_link}}"
                    ),
                    "tone": "friendly",
                    "language": "cs",
                    "personalization_vars": [
                        "contact_name",
                        "school_name",
                        "showreel_indoor_link",
                    ],
                },
            },
            {
                "position": 2,
                "day_offset": 5,
                "channel": "email",
                "label": "Reference + cena",
                "condition": "always",
                "config": {
                    "template_subject": "Reference z podobných plesu",
                    "template_body": (
                        "Reference z podobných plesu + konkrétní cenová nabídka."
                    ),
                    "tone": "friendly",
                    "language": "cs",
                    "personalization_vars": ["contact_name", "school_name"],
                },
            },
            {
                "position": 3,
                "day_offset": 12,
                "channel": "call",
                "label": "Telefonát",
                "condition": "no_response",
                "config": {
                    "template_body": (
                        "Posílal jsem nabídku pro váš ples. "
                        "Mel/a jste možnost se podívat?"
                    ),
                    "tone": "friendly",
                    "language": "cs",
                    "personalization_vars": ["contact_name"],
                },
            },
            {
                "position": 4,
                "day_offset": 18,
                "channel": "email",
                "label": "Pozvánka na ukázku",
                "condition": "no_response",
                "config": {
                    "template_subject": "Pozvánka na živou ukázku",
                    "template_body": (
                        "Rádi vám ukážeme naše umení naživo — "
                        "pozvánka na nejbližší predstavení."
                    ),
                    "tone": "friendly",
                    "language": "cs",
                    "personalization_vars": ["contact_name"],
                },
            },
        ],
    },
    {
        "name": "P3 DACH Pilot — Event Agenturen",
        "description": (
            "German-Language Agency Outreach — target event agencies "
            "in Munich, Vienna, Frankfurt, Stuttgart."
        ),
        "language": "de",
        "channel": "email",
        "status": "draft",
        "generation_config": {
            "recommended_products": [
                "Katalogshow (2,500-4,000 EUR)",
                "Massgeschneidertes Abendprogramm (8,000-18,000 EUR)",
            ],
            "segment": "dach_agentura",
            "language": "de",
        },
        "target_criteria": {
            "segment": "dach_agentura",
            "language": "de",
            "geo_region": "DACH",
        },
        "steps": [
            {
                "position": 1,
                "day_offset": 0,
                "channel": "email",
                "label": "Intro",
                "condition": "always",
                "config": {
                    "template_subject": "Einzigartige Gruppenakrobatik fuer Ihre Events",
                    "template_body": (
                        "Wir sind eine tschechische Zirkuscompagnie "
                        "mit Kunden wie Mercedes-Benz und Bosch. "
                        "Unsere Gruppenakrobatik mit 10-14 Performern "
                        "ist einzigartig in der DACH-Region. "
                        "Showreel: {{showreel_link}}"
                    ),
                    "tone": "professional",
                    "language": "de",
                    "personalization_vars": [
                        "contact_name",
                        "company_name",
                        "showreel_link",
                    ],
                },
            },
            {
                "position": 2,
                "day_offset": 4,
                "channel": "linkedin_connect",
                "label": "LinkedIn Connect",
                "condition": "always",
                "config": {
                    "template_body": (
                        "Hallo {{contact_name}}, wir bieten einzigartige "
                        "Live-Entertainment-Konzepte fuer Events in der "
                        "DACH-Region. Ich wuerde mich ueber eine "
                        "Vernetzung freuen!"
                    ),
                    "tone": "professional",
                    "language": "de",
                    "personalization_vars": ["contact_name", "company_name"],
                },
            },
            {
                "position": 3,
                "day_offset": 8,
                "channel": "email",
                "label": "Showreel + Preise",
                "condition": "always",
                "config": {
                    "template_subject": "Video Showreel + Preisrahmen",
                    "template_body": (
                        "Video showreel + konkreter Preisrahmen fuer "
                        "erste Veranstaltung (Katalogshow ab 2.500 EUR)."
                    ),
                    "tone": "professional",
                    "language": "de",
                    "personalization_vars": ["contact_name", "company_name"],
                },
            },
            {
                "position": 4,
                "day_offset": 14,
                "channel": "email",
                "label": "Case Study",
                "condition": "no_response",
                "config": {
                    "template_subject": "Case Study: Mercedes-Benz Event",
                    "template_body": (
                        "Case study von internationaler Veranstaltung "
                        "(Mercedes, Bosch, etc.)."
                    ),
                    "tone": "professional",
                    "language": "de",
                    "personalization_vars": ["contact_name", "company_name"],
                },
            },
            {
                "position": 5,
                "day_offset": 21,
                "channel": "call",
                "label": "Follow-up Anruf",
                "condition": "no_response",
                "config": {
                    "template_body": ("Persoenlicher Kontakt — in DACH unersetzlich."),
                    "tone": "professional",
                    "language": "de",
                    "personalization_vars": ["contact_name", "company_name"],
                },
            },
        ],
    },
]


def seed_campaigns():
    """Insert UA campaigns and their steps into the database."""
    app = create_app()
    with app.app_context():
        # Find united-arts tenant, fall back to first tenant
        tenant = Tenant.query.filter_by(slug="united-arts").first()
        if not tenant:
            tenant = Tenant.query.first()
        if not tenant:
            print("ERROR: No tenant found. Create a tenant first.")
            sys.exit(1)

        print(f"Using tenant: {tenant.name} (slug={tenant.slug}, id={tenant.id})")

        created = 0
        skipped = 0
        for cdef in CAMPAIGNS:
            # Check if campaign already exists by name
            existing = Campaign.query.filter_by(
                tenant_id=tenant.id, name=cdef["name"]
            ).first()
            if existing:
                print(f"  SKIP: {cdef['name']} (already exists, id={existing.id})")
                skipped += 1
                continue

            campaign = Campaign(
                tenant_id=tenant.id,
                name=cdef["name"],
                description=cdef["description"],
                language=cdef["language"],
                channel=cdef["channel"],
                status=cdef["status"],
                generation_config=json.dumps(cdef["generation_config"]),
                target_criteria=json.dumps(cdef["target_criteria"]),
            )
            db.session.add(campaign)
            db.session.flush()  # get campaign.id

            for sdef in cdef["steps"]:
                step = CampaignStep(
                    campaign_id=campaign.id,
                    tenant_id=tenant.id,
                    position=sdef["position"],
                    day_offset=sdef["day_offset"],
                    channel=sdef["channel"],
                    label=sdef["label"],
                    condition=sdef["condition"],
                    config=json.dumps(sdef["config"]),
                )
                db.session.add(step)

            print(
                f"  CREATE: {cdef['name']} "
                f"({len(cdef['steps'])} steps, lang={cdef['language']})"
            )
            created += 1

        db.session.commit()
        print(f"\nDone: {created} created, {skipped} skipped.")


if __name__ == "__main__":
    seed_campaigns()
