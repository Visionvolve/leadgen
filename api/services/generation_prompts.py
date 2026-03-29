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

SYSTEM_PROMPT = """You are an expert B2B outreach copywriter. You write personalized, \
concise outreach messages that feel human-written, not AI-generated. \
You avoid cliches, buzzwords, and generic pitches. Every message references \
specific details about the recipient and their company to show genuine research.

When a STRATEGY section is provided, you MUST incorporate its messaging angles, \
value propositions, and tone guidelines into the message. The strategy represents \
the sender's GTM positioning — your message should feel like it comes from someone \
who deeply understands their own product's value and the prospect's pain points. \
Never contradict the strategy's positioning or use messaging angles not aligned \
with it.

CRITICAL: When ENRICHMENT data is provided (company intel, recent news, pain \
points, tech stack, hiring signals, growth signals, etc.), you MUST reference \
at least one specific fact from the enrichment in your message. Generic messages \
that ignore available enrichment data are unacceptable. Use concrete details like \
company size, recent initiatives, technology choices, or hiring patterns to show \
the sender has done genuine research. Avoid vague references — cite specifics."""


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


def _build_enrichment_section(enrichment_data: dict) -> str:
    """Format enrichment data (L1/L2/Person) as a comprehensive section.

    BL-173: Enhanced to include growth signals, M&A activity, and
    AI champion indicators for enrichment-grounded personalization.
    """
    if not enrichment_data:
        return ""

    lines = []

    # L2 deep research
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
    if l2.get("digital_initiatives"):
        lines.append(f"Digital Initiatives: {l2['digital_initiatives']}")
    if l2.get("hiring_signals"):
        lines.append(f"Hiring Signals: {l2['hiring_signals']}")
    # BL-173: Additional L2 fields for richer personalization
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
    if person.get("ai_champion_score") and int(person["ai_champion_score"] or 0) >= 7:
        lines.append(
            "AI Champion: High likelihood — this person actively promotes AI/tech adoption."
        )
    if person.get("authority_score") and int(person["authority_score"] or 0) >= 8:
        lines.append(
            "Authority: Senior decision-maker with high organizational influence."
        )

    return "\n".join(lines) if lines else ""


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

    # Build context sections
    contact_section = _build_contact_section(contact_data, enrichment_data)
    company_section = _build_company_section(company_data, enrichment_data)

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
    enrichment_section = _build_enrichment_section(enrichment_data)
    if enrichment_section:
        parts.extend(
            [
                "",
                "--- ENRICHMENT ---",
                enrichment_section,
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


def _build_contact_section(contact_data: dict, enrichment_data: dict) -> str:
    lines = []
    name = f"{contact_data.get('first_name', '')} {contact_data.get('last_name', '')}".strip()
    if name:
        lines.append(f"Name: {name}")
    if contact_data.get("job_title"):
        lines.append(f"Title: {contact_data['job_title']}")
    if contact_data.get("email_address"):
        lines.append(f"Email: {contact_data['email_address']}")
    if contact_data.get("linkedin_url"):
        lines.append(f"LinkedIn: {contact_data['linkedin_url']}")
    if contact_data.get("seniority_level"):
        lines.append(f"Seniority: {contact_data['seniority_level']}")
    if contact_data.get("department"):
        lines.append(f"Department: {contact_data['department']}")

    # Person enrichment data
    person = enrichment_data.get("person", {})
    if person.get("person_summary"):
        lines.append(f"Person Summary: {person['person_summary']}")
    if person.get("relationship_synthesis"):
        lines.append(f"Relationship: {person['relationship_synthesis']}")

    return "\n".join(lines) if lines else "No contact details available."


def _build_company_section(company_data: dict, enrichment_data: dict) -> str:
    """BL-173: Enhanced with enrichment-grounded fields (size, revenue, business model)."""
    lines = []
    if company_data.get("name"):
        lines.append(f"Company: {company_data['name']}")
    if company_data.get("domain"):
        lines.append(f"Domain: {company_data['domain']}")
    if company_data.get("industry"):
        lines.append(f"Industry: {company_data['industry']}")
    if company_data.get("hq_country"):
        lines.append(f"Country: {company_data['hq_country']}")
    # BL-173: Add company size and employee/revenue data for grounded personalization
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

    # L2 enrichment data
    l2 = enrichment_data.get("l2", {})
    if l2.get("company_intel"):
        lines.append(f"Intel: {l2['company_intel']}")
    if l2.get("recent_news"):
        lines.append(f"Recent News: {l2['recent_news']}")
    if l2.get("ai_opportunities"):
        lines.append(f"AI Opportunities: {l2['ai_opportunities']}")
    # BL-173: Add pitch framing from L2 for message grounding
    if l2.get("pitch_framing"):
        lines.append(f"Recommended Approach: {l2['pitch_framing']}")
    if l2.get("expansion"):
        lines.append(f"Growth/Expansion: {l2['expansion']}")

    return "\n".join(lines) if lines else "No company details available."
