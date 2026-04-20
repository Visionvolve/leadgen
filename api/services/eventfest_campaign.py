"""EventFest campaign provisioning service.

Turns a curated list of contact emails into a ready-to-send EventFest
Campaign. Idempotent end-to-end:

- Reuses existing Contacts by email (case-insensitive within tenant).
- Reuses existing Campaign by (tenant_id, name).
- Reuses existing CampaignContact rows (UniqueConstraint on
  campaign_id/contact_id).
- Reuses existing Message rows for a given campaign_contact_id.
- Persists each recipient's UA microsite partner token on the
  CampaignContact for later cross-repo event attribution.

The service does NOT dispatch emails — it leaves Messages in
``status='approved'`` so the existing
``api.services.send_service.send_campaign_emails`` will pick them up.

Required environment variables (validated at call time):

- ``UA_MAILING_FROM_EMAIL`` — sender email address
- ``UA_MAILING_FROM_NAME`` — sender display name
- ``UA_MAILING_REPLY_TO`` — reply-to address
- ``UA_MICROSITE_URL`` — microsite base URL (e.g. https://demo.visionvolve.com)
- ``UA_INVITE_API_KEY`` — shared secret for UA /api/invites endpoint
"""

from __future__ import annotations

import json
import logging
import os

from ..models import (
    Campaign,
    CampaignContact,
    Contact,
    Message,
    db,
)
from .eventfest_template import (
    EVENTFEST_SUBJECT,
    TONE_PASSTHROUGH,
    render_eventfest_email,
)
from .microsite_invites import get_or_create_invite

logger = logging.getLogger(__name__)


REQUIRED_ENV_VARS = (
    "UA_MAILING_FROM_EMAIL",
    "UA_MAILING_FROM_NAME",
    "UA_MAILING_REPLY_TO",
    "UA_MICROSITE_URL",
    "UA_INVITE_API_KEY",
)


def _read_env() -> dict[str, str]:
    """Read required env vars; raise RuntimeError if any are missing."""
    values = {key: os.environ.get(key, "").strip() for key in REQUIRED_ENV_VARS}
    missing = [key for key, val in values.items() if not val]
    if missing:
        raise RuntimeError(
            f"eventfest_campaign: missing required env vars: {', '.join(missing)}"
        )
    return values


def _coerce_jsonb(value) -> dict:
    """Return a dict from a JSONB column value (PG dict, SQLite TEXT, or None)."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _extract_token(invite_url: str) -> str:
    """Extract the partner token from a full invite URL.

    ``https://demo.visionvolve.com/invite/abc123`` -> ``abc123``.
    Falls back to the URL itself if it does not contain ``/``.
    """
    if not invite_url:
        return ""
    return invite_url.rsplit("/", 1)[-1]


def _load_featured_acts() -> list[dict]:
    """Load the 4 featured-act thumbnail records from UA_FEATURED_ACTS_JSON env.

    Returns an empty list when the env var is unset or malformed so the
    template falls back to text-only (thumbnail section omitted entirely).

    Expected JSON shape::

        [
          {"name": "Complicité", "slug": "complicite",
           "image_url": "https://...", "category": "performances"},
          ...
        ]

    Up to 4 entries are used; extras are silently ignored.
    """
    raw = os.environ.get("UA_FEATURED_ACTS_JSON", "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.warning(
            "UA_FEATURED_ACTS_JSON is not valid JSON (%s) — rendering without thumbnails",
            exc,
        )
        return []
    if not isinstance(data, list):
        logger.warning(
            "UA_FEATURED_ACTS_JSON must be a JSON array — rendering without thumbnails"
        )
        return []
    out: list[dict] = []
    for entry in data[:4]:
        if not isinstance(entry, dict):
            continue
        if not entry.get("slug") or not entry.get("image_url"):
            continue
        out.append(
            {
                "name": str(entry.get("name") or entry.get("slug")),
                "slug": str(entry["slug"]),
                "image_url": str(entry["image_url"]),
                "category": str(entry.get("category") or "performances"),
            }
        )
    return out


def _render_storable_body(
    featured_acts: list[dict] | None = None,
    site_url: str = "",
) -> tuple[str, str]:
    """Return the EventFest HTML + plain-text bodies with template placeholders intact.

    Three kinds of placeholders are embedded in the returned body and are
    substituted per-recipient at send time by
    ``send_service._build_template_variables``:

    - ``{{vocative_name}}`` and ``{{microsite_link}}`` — per-recipient text
      values.
    - ``{{recipient_token}}`` — per-recipient token baked into each
      featured-act thumbnail href (``?t={{recipient_token}}``) so arrival
      on the UA detail page sets the partner cookie.
    - ``{{you_acc}}``, ``{{you_look_verb}}``, ``{{you_can_verb}}``,
      ``{{stop_by_imper}}`` — tone (Vy/Ty) variants picked from
      ``contact.address_style``. Using ``tone=TONE_PASSTHROUGH`` below keeps
      these literal in the stored body.

    Args:
        featured_acts: Optional list of act dicts (see ``_load_featured_acts``).
            When empty/None the thumbnail grid is omitted entirely.
        site_url: UA microsite origin used to build absolute detail-page
            URLs. Ignored when ``featured_acts`` is empty.

    Returns:
        ``(html_body, plain_body)`` — both strings contain the placeholders
        above in literal form so per-recipient substitution at send time
        produces the final content.
    """
    _, html, plain = render_eventfest_email(
        vocative_name="{{vocative_name}}",
        microsite_link="{{microsite_link}}",
        recipient_token="{{recipient_token}}",
        site_url=site_url,
        featured_acts=featured_acts or None,
        tone=TONE_PASSTHROUGH,
    )
    return html, plain


def provision_eventfest_campaign(
    name: str,
    contact_emails: list[str],
    tenant_id: str,
) -> str:
    """Provision a ready-to-send EventFest campaign.

    Idempotent: re-running with the same ``(name, tenant_id)`` returns the
    same Campaign id and does NOT duplicate any CampaignContact or Message
    rows.

    Args:
        name: Human-readable campaign name (also the idempotency key
            within ``tenant_id``).
        contact_emails: List of recipient email addresses. Empty strings
            and duplicates are filtered out.
        tenant_id: Owning tenant UUID.

    Returns:
        The Campaign UUID as a string.

    Raises:
        RuntimeError: if required env vars are missing or the UA microsite
            invite API is unreachable. The transaction is rolled back so
            no partial Campaign is left in the DB.
    """
    if not name or not name.strip():
        raise ValueError("provision_eventfest_campaign: name is required")
    if not tenant_id:
        raise ValueError("provision_eventfest_campaign: tenant_id is required")

    # Validate env up front so we fail before opening a transaction.
    env = _read_env()

    # Normalise/dedupe emails (case-insensitive).
    seen: set[str] = set()
    emails: list[str] = []
    for raw in contact_emails or []:
        email = (raw or "").strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        emails.append(email)

    if not emails:
        raise ValueError("provision_eventfest_campaign: no valid emails supplied")

    featured_acts = _load_featured_acts()
    storable_body, _storable_plain = _render_storable_body(
        featured_acts=featured_acts,
        site_url=env["UA_MICROSITE_URL"],
    )

    try:
        # 1. Find or create Campaign (idempotent by (tenant_id, name)).
        campaign = (
            db.session.query(Campaign)
            .filter(
                Campaign.tenant_id == tenant_id,
                Campaign.name == name,
            )
            .first()
        )
        if campaign is None:
            campaign = Campaign(
                tenant_id=tenant_id,
                name=name,
                status="draft",
                language="cs",
                template_config=[],
                generation_config={"template_type": "eventfest"},
                sender_config={
                    "from_email": env["UA_MAILING_FROM_EMAIL"],
                    "from_name": env["UA_MAILING_FROM_NAME"],
                    "reply_to": env["UA_MAILING_REPLY_TO"],
                },
            )
            db.session.add(campaign)
            db.session.flush()
        else:
            # Ensure the existing campaign carries the EventFest config.
            gen_cfg = _coerce_jsonb(campaign.generation_config)
            if gen_cfg.get("template_type") != "eventfest":
                gen_cfg["template_type"] = "eventfest"
                campaign.generation_config = gen_cfg
            sender_cfg = _coerce_jsonb(campaign.sender_config)
            if not sender_cfg.get("from_email"):
                sender_cfg.update(
                    {
                        "from_email": env["UA_MAILING_FROM_EMAIL"],
                        "from_name": env["UA_MAILING_FROM_NAME"],
                        "reply_to": env["UA_MAILING_REPLY_TO"],
                    }
                )
                campaign.sender_config = sender_cfg

        # 2. Per-email loop: get_or_create Contact + CampaignContact + Message.
        for email in emails:
            contact = (
                db.session.query(Contact)
                .filter(
                    Contact.tenant_id == tenant_id,
                    db.func.lower(Contact.email_address) == email,
                )
                .first()
            )
            if contact is None:
                # Default first_name to the email local-part so we satisfy
                # the NOT NULL constraint on contacts.first_name. The
                # operator can rename later via the dashboard.
                local_part = email.split("@", 1)[0]
                contact = Contact(
                    tenant_id=tenant_id,
                    first_name=local_part,
                    last_name="",
                    email_address=email,
                )
                db.session.add(contact)
                db.session.flush()

            cc = (
                db.session.query(CampaignContact)
                .filter(
                    CampaignContact.campaign_id == campaign.id,
                    CampaignContact.contact_id == contact.id,
                )
                .first()
            )
            if cc is None:
                cc = CampaignContact(
                    campaign_id=campaign.id,
                    contact_id=contact.id,
                    tenant_id=tenant_id,
                    status="pending",
                )
                db.session.add(cc)
                db.session.flush()

            # Fetch / refresh microsite partner token only if missing.
            if not cc.microsite_partner_token:
                full_name = (
                    f"{contact.first_name or ''} {contact.last_name or ''}".strip()
                    or email.split("@", 1)[0]
                )
                invite_url = get_or_create_invite(
                    email=email,
                    name=full_name,
                    microsite_url=env["UA_MICROSITE_URL"],
                    api_key=env["UA_INVITE_API_KEY"],
                )
                if not invite_url:
                    raise RuntimeError(
                        f"eventfest_campaign: microsite invite unreachable for {email}"
                    )
                cc.microsite_partner_token = _extract_token(invite_url)

            # Find or create the approved email Message for this CC.
            existing_msg = (
                db.session.query(Message)
                .filter(
                    Message.campaign_contact_id == cc.id,
                    Message.channel == "email",
                )
                .first()
            )
            if existing_msg is None:
                msg = Message(
                    tenant_id=tenant_id,
                    contact_id=contact.id,
                    channel="email",
                    sequence_step=1,
                    variant="a",
                    subject=EVENTFEST_SUBJECT,
                    body=storable_body,
                    status="approved",
                    language="cs",
                    campaign_contact_id=cc.id,
                )
                db.session.add(msg)

        # 3. Update total_contacts.
        total = (
            db.session.query(CampaignContact)
            .filter(CampaignContact.campaign_id == campaign.id)
            .count()
        )
        campaign.total_contacts = total

        db.session.commit()
        return str(campaign.id)

    except Exception:
        db.session.rollback()
        raise


def regenerate_messages_for_campaign(campaign_id: str) -> int:
    """Re-render approved EventFest Message bodies for a campaign.

    Useful when the EventFest template changes and you want existing
    draft campaigns to pick up the new copy. Returns the count of
    Messages rewritten.

    Skips Messages that have already been sent (i.e. have any
    EmailSendLog rows attached) — re-rendering after dispatch would be
    misleading.
    """
    from sqlalchemy import select

    from ..models import EmailSendLog

    env = _read_env()
    featured_acts = _load_featured_acts()
    storable_body, _storable_plain = _render_storable_body(
        featured_acts=featured_acts,
        site_url=env["UA_MICROSITE_URL"],
    )
    rewritten = 0

    cc_ids_subq = (
        select(CampaignContact.id)
        .where(CampaignContact.campaign_id == campaign_id)
        .scalar_subquery()
    )

    msgs = (
        db.session.query(Message)
        .filter(
            Message.campaign_contact_id.in_(cc_ids_subq),
            Message.channel == "email",
        )
        .all()
    )

    for msg in msgs:
        already_sent = (
            db.session.query(EmailSendLog)
            .filter(EmailSendLog.message_id == msg.id)
            .first()
        )
        if already_sent:
            continue
        msg.body = storable_body
        msg.subject = EVENTFEST_SUBJECT
        msg.status = "approved"
        rewritten += 1

    db.session.commit()
    return rewritten
