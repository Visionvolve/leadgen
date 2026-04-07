"""Prompt templates for message generation.

Each channel has constraints and a prompt template that gets filled with
enrichment data and generation config.
"""

from __future__ import annotations

# Channel-specific constraints
CHANNEL_CONSTRAINTS = {
    "linkedin_connect": {
        "max_chars": 300,
        "has_subject": False,
        "description": "LinkedIn connection request message (max 300 characters)",
    },
    "linkedin_message": {
        "max_chars": 2000,
        "has_subject": False,
        "description": "LinkedIn direct message",
    },
    "email": {
        "max_chars": 5000,
        "has_subject": True,
        "description": "Email with subject line and body",
    },
    "call": {
        "max_chars": 2000,
        "has_subject": False,
        "description": "Phone call script",
    },
}

SYSTEM_PROMPT = """You are writing short outreach emails for Losers Cirque Company / United Arts.

CRITICAL RULES — follow these exactly:

1. CZECH VOCATIVE CASE: When writing in Czech, ALWAYS use the vocative form of the \
recipient's first name in the greeting. Examples: Jana→Jano, Marianna→Marianno, \
Petr→Petře, Hana→Hanko, Martin→Martine, Jakub→Jakube, Eliška→Eliško, \
Renáta→Renáto, Helena→Heleno, Štěpánka→Štěpánko, Lenka→Lenko, Andrea→Andreo, \
Silvie→Silvie (stays same for -ie endings). Apply standard Czech declension rules \
for any name not listed here.

2. NO HALLUCINATION: This is COLD outreach. DO NOT invent or imply any prior \
interaction, conversation, meeting, or relationship. Never write "děkujeme za zájem", \
"na základě našeho rozhovoru", "jak jsme se bavili", "thanks for reaching out", \
or anything suggesting prior contact — unless there IS documented interaction history \
in the ENRICHMENT section.

3. KEEP IT SHORT: Maximum 150-200 words. Get to the point quickly.

4. PRODUCT MENTIONS: When RECOMMENDED PRODUCTS are provided, mention only 1-2 specific \
products by name with their price. Keep it natural — weave the product into the message \
as a concrete suggestion, not a product spec sheet.

5. TONE: Friendly professional — like a colleague recommending something. Not salesy, \
not corporate. Write naturally as a real person would.

6. SIGNATURE: Always sign as:
Hanka Faková
Event Producer
hana@unitedarts.cz | +420 737 853 490

7. STRATEGY & ENRICHMENT: When provided, incorporate strategy messaging angles and \
reference specific enrichment facts (company details, industry, segment). But keep it \
light — one or two relevant details, not a research report.

8. Write the entire message in the language specified (default: Czech). Subject lines \
should also be in that language."""


FORMALITY_INSTRUCTIONS = {
    "cs": {
        "formal": "Use formal address (vykání – Vy).",
        "informal": "Use informal address (tykání – ty).",
    },
    "de": {
        "formal": "Use formal address (Sie).",
        "informal": "Use informal address (du).",
    },
    "fr": {
        "formal": "Use formal address (vous).",
        "informal": "Use informal address (tu).",
    },
    "es": {
        "formal": "Use formal address (usted).",
        "informal": "Use informal address (tú).",
    },
    "it": {
        "formal": "Use formal address (Lei).",
        "informal": "Use informal address (tu).",
    },
    "pt": {
        "formal": "Use formal address (o senhor/a senhora).",
        "informal": "Use informal address (você/tu).",
    },
    "pl": {
        "formal": "Use formal address (Pan/Pani).",
        "informal": "Use informal address (ty).",
    },
    "nl": {
        "formal": "Use formal address (u).",
        "informal": "Use informal address (je/jij).",
    },
}


def _build_strategy_section(strategy_data: dict) -> str:
    """Format playbook extracted_data for the generation prompt.

    Extracts ICP, value proposition, messaging framework, competitive
    positioning, and buyer personas from the playbook's extracted_data
    and formats them as a readable section for the LLM.
    """
    if not strategy_data:
        return ""

    lines = []

    # ICP
    icp = strategy_data.get("icp")
    if icp:
        if isinstance(icp, dict):
            icp_parts = []
            if icp.get("industries"):
                icp_parts.append(f"Industries: {', '.join(icp['industries'])}")
            if icp.get("company_size"):
                size = icp["company_size"]
                if isinstance(size, dict):
                    icp_parts.append(
                        f"Company Size: {size.get('min', '?')}-{size.get('max', '?')} employees"
                    )
                else:
                    icp_parts.append(f"Company Size: {size}")
            if icp.get("geographies"):
                icp_parts.append(f"Geographies: {', '.join(icp['geographies'])}")
            if icp.get("tech_signals"):
                icp_parts.append(f"Tech Signals: {', '.join(icp['tech_signals'])}")
            if icp.get("triggers"):
                icp_parts.append(f"Triggers: {', '.join(icp['triggers'])}")
            if icp_parts:
                lines.append("ICP: " + "; ".join(icp_parts))
        else:
            lines.append(f"ICP: {icp}")

    # Value proposition
    vp = strategy_data.get("value_proposition")
    if not vp:
        # Also check messaging.themes as a fallback
        messaging = strategy_data.get("messaging", {})
        if isinstance(messaging, dict) and messaging.get("themes"):
            vp = ", ".join(messaging["themes"])
    if vp:
        if isinstance(vp, dict):
            lines.append(
                f"Value Proposition: {', '.join(str(v) for v in vp.values() if v)}"
            )
        else:
            lines.append(f"Value Proposition: {vp}")

    # Messaging framework
    messaging = strategy_data.get("messaging")
    if messaging and isinstance(messaging, dict):
        msg_parts = []
        if messaging.get("tone"):
            msg_parts.append(f"Tone: {messaging['tone']}")
        if messaging.get("themes"):
            msg_parts.append(f"Themes: {', '.join(messaging['themes'])}")
        if messaging.get("angles"):
            msg_parts.append(f"Angles: {', '.join(messaging['angles'])}")
        if messaging.get("proof_points"):
            msg_parts.append(f"Proof Points: {', '.join(messaging['proof_points'])}")
        if msg_parts:
            lines.append("Messaging Framework: " + "; ".join(msg_parts))
    elif messaging:
        lines.append(f"Messaging Framework: {messaging}")

    # Competitive positioning
    comp = strategy_data.get("competitive_positioning")
    if comp:
        if isinstance(comp, list):
            lines.append(f"Competitive Position: {', '.join(str(c) for c in comp)}")
        else:
            lines.append(f"Competitive Position: {comp}")

    # Buyer personas
    personas = strategy_data.get("personas")
    if personas and isinstance(personas, list):
        persona_parts = []
        for p in personas[:3]:  # Limit to top 3
            if isinstance(p, dict):
                titles = p.get("title_patterns", [])
                pains = p.get("pain_points", [])
                title_str = ", ".join(titles) if titles else "Unknown"
                pain_str = ", ".join(pains) if pains else ""
                entry = title_str
                if pain_str:
                    entry += f" (pains: {pain_str})"
                persona_parts.append(entry)
        if persona_parts:
            lines.append("Buyer Personas: " + " | ".join(persona_parts))

    # Channels
    channels = strategy_data.get("channels")
    if channels and isinstance(channels, dict):
        ch_parts = []
        if channels.get("primary"):
            ch_parts.append(f"Primary: {channels['primary']}")
        if channels.get("cadence"):
            ch_parts.append(f"Cadence: {channels['cadence']}")
        if ch_parts:
            lines.append("Channel Strategy: " + "; ".join(ch_parts))

    # Strategy document content (richer context from the playbook markdown)
    strategy_content = strategy_data.get("strategy_content")
    if strategy_content:
        lines.append("")
        lines.append("Strategy Document Excerpts:")
        lines.append(strategy_content)

    return "\n".join(lines) if lines else ""


def _build_enrichment_section(enrichment_data: dict, level: int = 4) -> str:
    """Format enrichment data (L1/L2/Person) as a comprehensive section.

    BL-173: Enhanced to include growth signals, M&A activity, and
    AI champion indicators for enrichment-grounded personalization.

    Levels:
        1-2: No enrichment context (return empty)
        3: L2 tech_stack, pain_hypothesis, key_products, competitors,
           customer_segments
        4: All of level 3 + digital_initiatives, hiring_signals,
           growth_signals, ma_activity + person career_trajectory,
           speaking_engagements, publications, ai_champion, authority
    """
    if not enrichment_data or level < 3:
        return ""

    lines = []

    # Level 3+: core L2 research
    l2 = enrichment_data.get("l2", {})
    if l2.get("tech_stack"):
        lines.append(f"Tech Stack: {l2['tech_stack']}")
    if l2.get("pain_hypothesis"):
        lines.append(f"Pain Points: {l2['pain_hypothesis']}")
    if l2.get("key_products"):
        lines.append(f"Products: {l2['key_products']}")
    if l2.get("customer_segments"):
        lines.append(f"Customer Segments: {l2['customer_segments']}")
    if l2.get("competitors"):
        lines.append(f"Competitors: {l2['competitors']}")

    if level >= 4:
        # Additional L2 signals
        if l2.get("digital_initiatives"):
            lines.append(f"Digital Initiatives: {l2['digital_initiatives']}")
        if l2.get("hiring_signals"):
            lines.append(f"Hiring Signals: {l2['hiring_signals']}")
        if l2.get("growth_signals"):
            lines.append(f"Growth Signals: {l2['growth_signals']}")
        if l2.get("ma_activity"):
            lines.append(f"M&A Activity: {l2['ma_activity']}")

        # Person enrichment extras (beyond what _build_contact_section covers)
        person = enrichment_data.get("person", {})
        if person.get("career_trajectory"):
            lines.append(f"Career Trajectory: {person['career_trajectory']}")
        if person.get("speaking_engagements"):
            lines.append(f"Speaking: {person['speaking_engagements']}")
        if person.get("publications"):
            lines.append(f"Publications: {person['publications']}")
        # BL-173: AI champion / authority signals for personalization
        if (
            person.get("ai_champion_score")
            and int(person["ai_champion_score"] or 0) >= 7
        ):
            lines.append(
                "AI Champion: High likelihood — this person actively promotes AI/tech adoption."
            )
        if person.get("authority_score") and int(person["authority_score"] or 0) >= 8:
            lines.append(
                "Authority: Senior decision-maker with high organizational influence."
            )

    return "\n".join(lines) if lines else ""


def _build_product_section(
    recommended_products: list[dict],
    language: str = "cs",
    catalog_context: dict | None = None,
) -> str:
    """Format recommended products for the generation prompt.

    Includes product name, price, best-for description, and catalog selling
    points so the LLM can weave specific product recommendations into the
    message with accurate details from the PDF catalog.
    """
    if not recommended_products:
        return ""

    # Build a lookup from catalog_context for selling_points by product name
    catalog_lookup: dict[str, dict] = {}
    if catalog_context:
        for section_key in (
            "animation_programs",
            "catalogue_shows",
            "music",
        ):
            for item in catalog_context.get(section_key, []):
                name_cs = item.get("name_cs", "")
                catalog_lookup[name_cs.lower()] = item

    lines = []
    entry_products = [
        p for p in recommended_products if p.get("recommendation_type") == "entry"
    ]
    upsell_products = [
        p for p in recommended_products if p.get("recommendation_type") == "upsell"
    ]

    if entry_products:
        lines.append("Recommended entry product(s) for this segment:")
        for p in entry_products:
            price_str = ""
            if language == "de" and p.get("price_eur"):
                price_str = f" ({p['price_eur']:,.0f} EUR/{p['price_unit']})"
            elif p.get("price_czk"):
                price_str = f" ({p['price_czk']:,.0f} CZK/{p['price_unit']})"
            desc = p.get("description_cs") or p.get("best_for") or ""
            line = f"- {p['name']}{price_str}: {desc}"
            # Append selling points from catalog if available
            cat_item = catalog_lookup.get(p["name"].lower(), {})
            if cat_item.get("selling_points"):
                line += f"\n  Selling point: {cat_item['selling_points']}"
            if cat_item.get("price_notes"):
                line += f"\n  Price note: {cat_item['price_notes']}"
            lines.append(line)

    if upsell_products:
        lines.append("Upsell option(s):")
        for p in upsell_products:
            price_str = ""
            if language == "de" and p.get("price_eur"):
                price_str = f" ({p['price_eur']:,.0f} EUR/{p['price_unit']})"
            elif p.get("price_czk"):
                price_str = f" ({p['price_czk']:,.0f} CZK/{p['price_unit']})"
            desc = p.get("description_cs") or p.get("best_for") or ""
            lines.append(f"- {p['name']}{price_str}: {desc}")

    # Append segment-specific pitch from catalog context
    # Match the segment with the highest overlap of entry product names
    if catalog_context and entry_products:
        seg_recs = catalog_context.get("segment_recommendations", {})
        entry_product_names = {p["name"].lower() for p in entry_products}
        best_seg = None
        best_overlap = 0
        for seg_key, seg_data in seg_recs.items():
            seg_entry_names = {n.lower() for n in seg_data.get("entry", [])}
            overlap = len(entry_product_names & seg_entry_names)
            if overlap > best_overlap:
                best_overlap = overlap
                best_seg = seg_data
        if best_seg and best_overlap > 0:
            pitch_key = "pitch_cs" if language != "en" else "pitch_en"
            pitch = best_seg.get(pitch_key) or best_seg.get("pitch_cs", "")
            if pitch:
                lines.append(f"\nSegment pitch: {pitch}")

    # General info from catalog
    if catalog_context and catalog_context.get("general_info"):
        info = catalog_context["general_info"]
        refs = info.get("references", [])
        if refs:
            lines.append(f"References: {', '.join(refs)}")

    return "\n".join(lines)


def build_generation_prompt(
    *,
    channel: str,
    step_label: str,
    contact_data: dict,
    company_data: dict,
    enrichment_data: dict,
    generation_config: dict,
    step_number: int,
    total_steps: int,
    strategy_data: dict | None = None,
    formality: str | None = None,
    per_message_instruction: str | None = None,
    example_messages: list | None = None,
    max_length: int | None = None,
    reference_assets: list | None = None,
    feedback_signals: dict | None = None,
    recommended_products: list | None = None,
    catalog_context: dict | None = None,
) -> str:
    """Build the user prompt for generating a single message step.

    Args:
        strategy_data: Optional playbook extracted_data (ICP, value props,
            messaging framework, competitive positioning, buyer personas).

    Returns the prompt string to send to Claude.
    """
    constraints = CHANNEL_CONSTRAINTS.get(channel, CHANNEL_CONSTRAINTS["email"])
    tone = generation_config.get("tone", "professional")
    language = generation_config.get("language", "en")
    custom_instructions = generation_config.get("custom_instructions", "")

    # Personalization level gates how much context is included (1=minimal, 4=full)
    personalization_level = generation_config.get("personalization_level", 4)

    # Build context sections
    contact_section = _build_contact_section(
        contact_data, enrichment_data, level=personalization_level
    )
    company_section = _build_company_section(
        company_data, enrichment_data, level=personalization_level
    )

    # Build format instructions
    if constraints["has_subject"]:
        format_instructions = (
            "Return JSON with two fields: "
            '{"subject": "...", "body": "..."}\n'
            f"Keep the subject under 60 characters.\n"
            f"Keep the body under {constraints['max_chars']} characters."
        )
    else:
        format_instructions = (
            "Return JSON with one field: "
            '{"body": "..."}\n'
            f"Keep the body under {constraints['max_chars']} characters."
        )

    parts = [
        f"Generate a {constraints['description']} for the following contact.",
        "",
        "--- CONTACT ---",
        contact_section,
        "",
        "--- COMPANY ---",
        company_section,
    ]

    # Strategy section from playbook (between COMPANY and SEQUENCE CONTEXT)
    if strategy_data:
        strategy_section = _build_strategy_section(strategy_data)
        if strategy_section:
            parts.extend(
                [
                    "",
                    "--- STRATEGY ---",
                    strategy_section,
                ]
            )

    # Enrichment deep-dive section (tech stack, pain points, etc.)
    enrichment_section = _build_enrichment_section(
        enrichment_data, level=personalization_level
    )
    if enrichment_section:
        parts.extend(
            [
                "",
                "--- ENRICHMENT ---",
                enrichment_section,
            ]
        )

    # Product recommendations (segment-driven) with catalog context
    if recommended_products:
        language = generation_config.get("language", "cs")
        # catalog_context comes from campaign generation_config or is passed directly
        effective_catalog = catalog_context or generation_config.get("catalog_context")
        product_section = _build_product_section(
            recommended_products, language, effective_catalog
        )
        if product_section:
            parts.extend(
                [
                    "",
                    "--- RECOMMENDED PRODUCTS ---",
                    "Mention the recommended entry product by name and price in the message. "
                    "Keep it natural — don't list specs, just mention the product as a concrete suggestion. "
                    "Do NOT mention upsell products — they are for internal reference only.",
                    product_section,
                ]
            )

    # Reference assets (uploaded files with summaries)
    if reference_assets:
        ref_lines = [
            "",
            "--- REFERENCE MATERIALS ---",
            "The following assets are provided as context. Reference key points naturally in the message:",
        ]
        for asset in reference_assets:
            ref_lines.append(
                f"\n### {asset['filename']} ({asset['content_type']})\n{asset['summary']}"
            )
        parts.extend(ref_lines)

    parts.extend(
        [
            "",
            "--- SEQUENCE CONTEXT ---",
            f"This is step {step_number} of {total_steps}: {step_label}",
            f"Channel: {channel.replace('_', ' ')}",
            f"Tone: {tone}",
            f"Language: {language}",
        ]
    )

    # Formality instruction (language-specific address form)
    effective_formality = formality or generation_config.get("formality")
    if effective_formality and language in FORMALITY_INSTRUCTIONS:
        fi = FORMALITY_INSTRUCTIONS[language].get(effective_formality, "")
        if fi:
            parts.append(f"Formality: {fi}")

    # Reference examples from campaign step config
    if example_messages:
        examples_lines = [
            "",
            "--- REFERENCE EXAMPLES ---",
            "Use these as style/tone reference (do NOT copy verbatim):",
        ]
        for i, ex in enumerate(example_messages, 1):
            examples_lines.append(
                f"\nExample {i}:\n{ex.get('body') or ex.get('text', '')}"
            )
            if ex.get("note"):
                examples_lines.append(f"(Note: {ex['note']})")
        parts.extend(examples_lines)

    # Max length constraint from campaign step config
    if max_length:
        parts.extend(
            [
                "",
                "--- LENGTH LIMIT ---",
                f"Maximum {max_length} characters. Be concise.",
            ]
        )

    # Feedback learning signals from previous generation rounds
    if feedback_signals:
        learning_parts = []
        if feedback_signals.get("approved_examples"):
            learning_parts.append("Messages like these were approved by the user:")
            for i, ex in enumerate(feedback_signals["approved_examples"][:3], 1):
                learning_parts.append(f"\nApproved {i}:\n{ex}")
        if feedback_signals.get("common_edits"):
            learning_parts.append("\nThe user frequently corrects these issues:")
            for reason, count in feedback_signals["common_edits"][:3]:
                learning_parts.append(f"- {reason} ({count}x)")
        if feedback_signals.get("rejected_patterns"):
            learning_parts.append(
                "\nAvoid messages similar to these (they were rejected):"
            )
            for i, ex in enumerate(feedback_signals["rejected_patterns"][:2], 1):
                learning_parts.append(f"\nRejected {i}:\n{ex}")
        if learning_parts:
            parts.extend(
                [
                    "",
                    "--- LEARNING ---",
                    *learning_parts,
                ]
            )

    parts.extend(
        [
            "",
            "--- OUTPUT FORMAT ---",
            format_instructions,
            "Return ONLY the JSON object, no markdown fencing or explanation.",
        ]
    )

    if custom_instructions:
        parts.extend(
            [
                "",
                "--- ADDITIONAL INSTRUCTIONS ---",
                custom_instructions[:2000],
            ]
        )

    if per_message_instruction:
        parts.extend(
            [
                "",
                "--- PER-MESSAGE INSTRUCTION ---",
                per_message_instruction[:200],
            ]
        )

    return "\n".join(parts)


def _build_contact_section(
    contact_data: dict, enrichment_data: dict, level: int = 4
) -> str:
    """Build contact context section with graduated personalization.

    Levels:
        1: first_name, last_name only
        2: + job_title, seniority_level
        3-4: + email, linkedin_url, department, person_summary, relationship_synthesis
    """
    lines = []
    # Level 1+: name
    name = f"{contact_data.get('first_name', '')} {contact_data.get('last_name', '')}".strip()
    if name:
        lines.append(f"Name: {name}")

    if level >= 2:
        if contact_data.get("job_title"):
            lines.append(f"Title: {contact_data['job_title']}")
        if contact_data.get("seniority_level"):
            lines.append(f"Seniority: {contact_data['seniority_level']}")

    if level >= 3:
        if contact_data.get("email_address"):
            lines.append(f"Email: {contact_data['email_address']}")
        if contact_data.get("linkedin_url"):
            lines.append(f"LinkedIn: {contact_data['linkedin_url']}")
        if contact_data.get("department"):
            lines.append(f"Department: {contact_data['department']}")

        # Person enrichment data
        person = enrichment_data.get("person", {})
        if person.get("person_summary"):
            lines.append(f"Person Summary: {person['person_summary']}")
        if person.get("relationship_synthesis"):
            lines.append(f"Relationship: {person['relationship_synthesis']}")

    return "\n".join(lines) if lines else "No contact details available."


def _build_company_section(
    company_data: dict, enrichment_data: dict, level: int = 4
) -> str:
    """Build company context section with graduated personalization.

    Levels:
        1: No company context
        2: name, industry, hq_country only
        3: + domain, company_size, employee_count, revenue, business_model,
           summary, L2 company_intel, recent_news
        4: All of level 3 + ai_opportunities, pitch_framing, expansion
    """
    if level < 2:
        return "No company context at this personalization level."

    lines = []
    # Level 2+: basic company info
    if company_data.get("name"):
        lines.append(f"Company: {company_data['name']}")
    if company_data.get("industry"):
        lines.append(f"Industry: {company_data['industry']}")
    if company_data.get("hq_country"):
        lines.append(f"Country: {company_data['hq_country']}")

    if level >= 3:
        if company_data.get("domain"):
            lines.append(f"Domain: {company_data['domain']}")
        if company_data.get("company_size"):
            lines.append(f"Company Size: {company_data['company_size']}")
        if company_data.get("employee_count"):
            lines.append(f"Employees: ~{company_data['employee_count']}")
        if company_data.get("revenue_eur_m"):
            lines.append(f"Revenue: ~{company_data['revenue_eur_m']}M EUR")
        if company_data.get("business_model"):
            lines.append(f"Business Model: {company_data['business_model']}")
        if company_data.get("summary"):
            lines.append(f"Summary: {company_data['summary']}")

        # L2 enrichment data (level 3+)
        l2 = enrichment_data.get("l2", {})
        if l2.get("company_intel"):
            lines.append(f"Intel: {l2['company_intel']}")
        if l2.get("recent_news"):
            lines.append(f"Recent News: {l2['recent_news']}")

    if level >= 4:
        l2 = enrichment_data.get("l2", {})
        if l2.get("ai_opportunities"):
            lines.append(f"AI Opportunities: {l2['ai_opportunities']}")
        if l2.get("pitch_framing"):
            lines.append(f"Recommended Approach: {l2['pitch_framing']}")
        if l2.get("expansion"):
            lines.append(f"Growth/Expansion: {l2['expansion']}")

    return "\n".join(lines) if lines else "No company details available."
