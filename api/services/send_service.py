"""Email send service for campaign outreach.

Handles dispatching approved email messages via the Resend API or
Gmail API, with idempotent send tracking via EmailSendLog.

Safety rails:
- Daily + hourly send quotas (tenant-configurable)
- Warm-up schedule for new sending domains
- Configurable delay with jitter between sends
- List-Unsubscribe header (CAN-SPAM compliance)
- Pre-send email validation
- Gmail API sending with conservative rate limits
"""

from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime, timedelta, timezone

from ..models import (
    Campaign,
    CampaignContact,
    Contact,
    EmailSendLog,
    Message,
    OAuthConnection,
    Tenant,
    db,
)

logger = logging.getLogger(__name__)

# Conservative defaults — overridable via tenant.settings.send_limits
DEFAULT_DAILY_LIMIT = 100
DEFAULT_HOURLY_LIMIT = 30
DEFAULT_DELAY_SECONDS = 30
DEFAULT_DELAY_JITTER = 5  # +/- seconds

# Warm-up schedule: (day_number, max_emails_that_day)
WARMUP_SCHEDULE = [
    (1, 20),
    (2, 30),
    (3, 50),
    (4, 75),
    (5, 100),
    (7, 150),
    (14, 300),
    (30, 500),
]

# Basic email regex for pre-send validation
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def _mark_prior_failures_superseded(
    tenant_id: str, message_id: str, winning_log_id: str
) -> int:
    """BL-1029: mark any earlier failed send-log rows for this message as
    superseded by the winning (successful) row.

    Called after a successful send so audit queries stop double-counting
    abort-then-retry attempts. Returns the number of rows marked.

    Only rows with status='failed' and superseded_at IS NULL are touched —
    idempotent and safe to call after every success.
    """
    now = datetime.now(timezone.utc)
    prior_failures = (
        db.session.query(EmailSendLog)
        .filter(
            EmailSendLog.tenant_id == tenant_id,
            EmailSendLog.message_id == message_id,
            EmailSendLog.id != winning_log_id,
            EmailSendLog.status == "failed",
            EmailSendLog.superseded_at.is_(None),
        )
        .all()
    )
    for row in prior_failures:
        row.superseded_at = now
        row.superseded_by = winning_log_id
    return len(prior_failures)


# Gmail-specific rate limits (more conservative — reputation is harder to recover)
# GSuite Workspace: 2,000/day.  Free Gmail: 500/day.
GMAIL_DELAY_SECONDS = 45  # ~80 emails/hour, well under limits
GMAIL_DAILY_LIMIT = 100
GMAIL_HOURLY_LIMIT = 20


def _get_send_limits(tenant_settings: dict) -> dict:
    """Extract send limits from tenant settings with safe defaults."""
    limits = (tenant_settings or {}).get("send_limits", {})
    return {
        "daily": limits.get("daily", DEFAULT_DAILY_LIMIT),
        "hourly": limits.get("hourly", DEFAULT_HOURLY_LIMIT),
        "delay_seconds": limits.get("delay_seconds", DEFAULT_DELAY_SECONDS),
        "warmup_enabled": limits.get("warmup_enabled", True),
    }


def _count_sent_today(tenant_id: str) -> int:
    """Count emails sent today for this tenant (sent, delivered, or queued)."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    row = db.session.execute(
        db.text("""
            SELECT COUNT(*) FROM email_send_log
            WHERE tenant_id = :tid
            AND status IN ('sent', 'delivered', 'queued')
            AND created_at >= :today_start
        """),
        {"tid": tenant_id, "today_start": today_start},
    ).scalar()
    return row or 0


def _count_sent_this_hour(tenant_id: str) -> int:
    """Count emails sent in the current hour for this tenant."""
    hour_start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    row = db.session.execute(
        db.text("""
            SELECT COUNT(*) FROM email_send_log
            WHERE tenant_id = :tid
            AND status IN ('sent', 'delivered', 'queued')
            AND created_at >= :hour_start
        """),
        {"tid": tenant_id, "hour_start": hour_start},
    ).scalar()
    return row or 0


def _get_warmup_day(tenant_id: str) -> int:
    """Determine the warm-up day by finding the earliest send for this tenant.

    Returns the number of days since the first email was sent (1-based).
    If no emails have ever been sent, returns 1.
    """
    first_send = db.session.execute(
        db.text("""
            SELECT MIN(created_at) FROM email_send_log
            WHERE tenant_id = :tid
            AND status IN ('sent', 'delivered')
        """),
        {"tid": tenant_id},
    ).scalar()

    if not first_send:
        return 1

    # SQLite returns strings; PostgreSQL returns datetime — handle both
    if isinstance(first_send, str):
        first_send = datetime.fromisoformat(first_send.replace("Z", "+00:00"))
    # Ensure timezone-aware comparison
    if first_send.tzinfo is None:
        first_send = first_send.replace(tzinfo=timezone.utc)
    days_since = (datetime.now(timezone.utc) - first_send).days
    return max(1, days_since + 1)  # 1-based


def _get_warmup_limit(warmup_day: int) -> int:
    """Get the max daily sends allowed for the given warm-up day."""
    limit = WARMUP_SCHEDULE[0][1]  # Default to day 1 limit
    for day_threshold, day_limit in WARMUP_SCHEDULE:
        if warmup_day >= day_threshold:
            limit = day_limit
        else:
            break
    return limit


def get_quota_status(tenant_id: str, tenant_settings: dict | None = None) -> dict:
    """Get current quota status for a tenant.

    Returns dict with daily/hourly remaining, warmup info.
    """
    if tenant_settings is None:
        tenant = db.session.get(Tenant, tenant_id)
        tenant_settings = tenant.settings if tenant else {}
        if isinstance(tenant_settings, str):
            import json

            tenant_settings = json.loads(tenant_settings)
        tenant_settings = tenant_settings or {}

    limits = _get_send_limits(tenant_settings)
    sent_today = _count_sent_today(tenant_id)
    sent_this_hour = _count_sent_this_hour(tenant_id)
    warmup_day = _get_warmup_day(tenant_id)
    warmup_limit = _get_warmup_limit(warmup_day)

    # Effective daily limit is the lower of configured and warm-up
    if limits["warmup_enabled"]:
        effective_daily = min(limits["daily"], warmup_limit)
    else:
        effective_daily = limits["daily"]

    return {
        "daily_limit": effective_daily,
        "daily_sent": sent_today,
        "daily_remaining": max(0, effective_daily - sent_today),
        "hourly_limit": limits["hourly"],
        "hourly_sent": sent_this_hour,
        "hourly_remaining": max(0, limits["hourly"] - sent_this_hour),
        "warmup_enabled": limits["warmup_enabled"],
        "warmup_day": warmup_day,
        "warmup_limit": warmup_limit,
    }


def _check_quota(tenant_id: str, limits: dict) -> tuple[bool, str]:
    """Check if sending is allowed under current quotas.

    Returns (allowed: bool, reason: str).
    """
    sent_today = _count_sent_today(tenant_id)
    sent_this_hour = _count_sent_this_hour(tenant_id)

    # Check warm-up limit
    if limits["warmup_enabled"]:
        warmup_day = _get_warmup_day(tenant_id)
        warmup_limit = _get_warmup_limit(warmup_day)
        effective_daily = min(limits["daily"], warmup_limit)
        if sent_today >= effective_daily:
            return False, (
                f"Daily warm-up limit reached ({effective_daily} emails on warm-up "
                f"day {warmup_day}). Sent today: {sent_today}."
            )
    else:
        if sent_today >= limits["daily"]:
            return False, (
                f"Daily send limit reached ({limits['daily']}). "
                f"Sent today: {sent_today}."
            )

    if sent_this_hour >= limits["hourly"]:
        return False, (
            f"Hourly send limit reached ({limits['hourly']}). "
            f"Sent this hour: {sent_this_hour}."
        )

    return True, ""


def _validate_recipients(
    messages_data: list[tuple],
) -> tuple[list[tuple], list[dict]]:
    """Validate recipient emails before sending.

    Args:
        messages_data: list of (message, contact, campaign_contact) tuples

    Returns:
        (valid, warnings) where valid is filtered list and warnings is list of dicts
    """
    valid = []
    warnings = []
    seen_emails: set[str] = set()

    for message, contact, cc in messages_data:
        email = contact.email_address
        if not email:
            warnings.append(
                {
                    "message_id": str(message.id),
                    "contact_id": str(contact.id),
                    "issue": "no_email",
                    "detail": f"Contact {contact.first_name} {contact.last_name} has no email address",
                }
            )
            continue

        if not EMAIL_RE.match(email):
            warnings.append(
                {
                    "message_id": str(message.id),
                    "contact_id": str(contact.id),
                    "issue": "invalid_email",
                    "detail": f"Invalid email format: {email}",
                }
            )
            continue

        if email.lower() in seen_emails:
            warnings.append(
                {
                    "message_id": str(message.id),
                    "contact_id": str(contact.id),
                    "issue": "duplicate",
                    "detail": f"Duplicate recipient: {email}",
                }
            )
            continue

        seen_emails.add(email.lower())
        valid.append((message, contact, cc))

    return valid, warnings


def send_campaign_emails(campaign_id: str, tenant_id: str) -> dict:
    """Send all approved email messages for a campaign via Resend.

    Idempotent: skips messages that already have a non-failed EmailSendLog entry.
    Enforces daily/hourly quotas and warm-up schedule.

    Args:
        campaign_id: UUID of the campaign
        tenant_id: UUID of the tenant

    Returns:
        dict with sent_count, failed_count, skipped_count, total,
        validation_warnings, quota_stopped
    """
    import resend

    # 1. Load campaign and validate sender_config
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign or str(campaign.tenant_id) != str(tenant_id):
        raise ValueError("Campaign not found")

    sender_config = campaign.sender_config
    if isinstance(sender_config, str):
        import json

        sender_config = json.loads(sender_config)
    sender_config = sender_config or {}

    from_email = sender_config.get("from_email")
    from_name = sender_config.get("from_name")
    reply_to = sender_config.get("reply_to")

    if not from_email:
        raise ValueError("Campaign sender_config missing from_email")

    # Extract sender domain for List-Unsubscribe header
    sender_domain = from_email.split("@")[-1] if "@" in from_email else ""

    # 2. Configure Resend API key from tenant settings
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("Tenant not found")

    tenant_settings = tenant.settings
    if isinstance(tenant_settings, str):
        import json

        tenant_settings = json.loads(tenant_settings)
    tenant_settings = tenant_settings or {}

    api_key = tenant_settings.get("resend_api_key")
    if not api_key:
        raise ValueError("Tenant settings missing resend_api_key")

    resend.api_key = api_key

    # 3. Get send limits
    limits = _get_send_limits(tenant_settings)

    # 4. Pre-send quota check
    allowed, reason = _check_quota(tenant_id, limits)
    if not allowed:
        logger.warning("Send blocked for campaign %s: %s", campaign_id, reason)
        return {
            "sent_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "total": 0,
            "quota_stopped": True,
            "quota_message": reason,
            "validation_warnings": [],
        }

    # 5. Load approved email messages not yet sent (idempotent check).
    # BL-1105: hard-filter Contact.is_suppressed so unsubscribed /
    # hard-bounced / complained contacts never re-enter the send queue.
    messages_data = (
        db.session.query(Message, Contact, CampaignContact)
        .join(CampaignContact, Message.campaign_contact_id == CampaignContact.id)
        .join(Contact, Message.contact_id == Contact.id)
        .filter(
            CampaignContact.campaign_id == campaign_id,
            CampaignContact.tenant_id == tenant_id,
            Message.status == "approved",
            Message.channel == "email",
            Contact.is_suppressed.is_(False),
        )
        .all()
    )

    # 6. Pre-send validation
    valid_messages, validation_warnings = _validate_recipients(messages_data)

    # Log validation summary
    if validation_warnings:
        logger.warning(
            "Pre-send validation for campaign %s: %d warnings out of %d messages",
            campaign_id,
            len(validation_warnings),
            len(messages_data),
        )

    # Calculate delay with jitter
    base_delay = limits["delay_seconds"]
    jitter = DEFAULT_DELAY_JITTER

    # Estimate completion time
    estimated_seconds = len(valid_messages) * base_delay
    estimated_completion = datetime.now(timezone.utc) + timedelta(
        seconds=estimated_seconds
    )
    logger.info(
        "Starting send for campaign %s: %d valid emails, "
        "est. completion at %s (delay=%ds)",
        campaign_id,
        len(valid_messages),
        estimated_completion.isoformat(),
        base_delay,
    )

    sent_count = 0
    failed_count = 0
    skipped_count = 0
    quota_stopped = False
    quota_message = ""

    for message, contact, cc in valid_messages:
        # Idempotent: check if already sent (non-failed log exists)
        existing_log = (
            db.session.query(EmailSendLog)
            .filter(
                EmailSendLog.message_id == message.id,
                EmailSendLog.tenant_id == tenant_id,
                EmailSendLog.status != "failed",
            )
            .first()
        )
        if existing_log:
            skipped_count += 1
            continue

        # Re-check quota before each send
        allowed, reason = _check_quota(tenant_id, limits)
        if not allowed:
            logger.warning(
                "Quota reached mid-send for campaign %s after %d emails: %s",
                campaign_id,
                sent_count,
                reason,
            )
            quota_stopped = True
            quota_message = reason
            break

        to_email = contact.email_address

        # Create queued log entry
        log = EmailSendLog(
            tenant_id=tenant_id,
            message_id=message.id,
            status="queued",
            from_email=from_email,
            to_email=to_email,
        )
        db.session.add(log)
        db.session.flush()

        # Build the email body as HTML
        body_html = _render_body_html(message.body)
        subject = message.subject or "(no subject)"

        # Template variable replacement (EventFest and future template campaigns)
        tpl_vars = _build_template_variables(contact, cc, campaign)
        if tpl_vars:
            # BL-1110: language-aware rendering. When the campaign uses a
            # known template_type, the registry produces the right-language
            # body+subject from scratch; this replaces the stored-body
            # placeholder substitution for those campaigns.
            templated = _resolve_templated_body(
                campaign=campaign,
                contact=contact,
                template_variables=tpl_vars,
            )
            if templated is not None:
                body_html = templated["html"]
                subject = templated["subject"]
                log.template_language = templated["language_used"]
                log.template_language_fallback = templated["fallback_used"]
            else:
                # Legacy / non-registry templated campaigns: substitute
                # placeholders into the stored Message.body as before.
                body_html = _replace_template_variables(body_html, tpl_vars)

        sender = f"{from_name} <{from_email}>" if from_name else from_email

        # BL-1103: include the per-contact HTTPS unsubscribe URL alongside
        # the mailto fallback so List-Unsubscribe is RFC 8058-compliant
        # in modern Gmail/Outlook clients (one-click without a mail draft).
        unsubscribe_url = _build_unsubscribe_url(contact)

        try:
            result = _send_single_email(
                to_email=to_email,
                sender=sender,
                reply_to=reply_to,
                subject=subject,
                body_html=body_html,
                sender_domain=sender_domain,
                unsubscribe_url=unsubscribe_url,
            )

            # Update log with success
            log.resend_message_id = result.get("id")
            log.status = "sent"
            log.sent_at = datetime.now(timezone.utc)

            # Update message sent_at
            message.sent_at = datetime.now(timezone.utc)

            # BL-1029: mark any earlier failed attempts for this message as
            # superseded so audit queries count the delivery once.
            _mark_prior_failures_superseded(tenant_id, message.id, log.id)

            db.session.commit()
            sent_count += 1

        except Exception as e:
            logger.error("Failed to send email for message %s: %s", message.id, str(e))
            log.status = "failed"
            log.error = str(e)[:500]
            db.session.commit()
            failed_count += 1

        # Rate limit delay with jitter
        actual_delay = base_delay + random.uniform(-jitter, jitter)
        actual_delay = max(0.1, actual_delay)  # Never go below 100ms
        time.sleep(actual_delay)

    # Count validation failures (no email) that were handled as failed logs
    # by the old code path — now they're just warnings
    for warning in validation_warnings:
        if warning["issue"] == "no_email":
            # Create a failed log for contacts without email
            log = EmailSendLog(
                tenant_id=tenant_id,
                message_id=warning["message_id"],
                status="failed",
                from_email=from_email,
                error=f"Pre-send validation: {warning['detail']}",
            )
            db.session.add(log)
            failed_count += 1

    if validation_warnings:
        db.session.commit()

    result = {
        "sent_count": sent_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "total": sent_count + failed_count + skipped_count,
        "quota_stopped": quota_stopped,
        "validation_warnings": validation_warnings,
    }
    if quota_message:
        result["quota_message"] = quota_message

    return result


def _send_single_email(
    *,
    to_email: str,
    sender: str,
    reply_to: str | None,
    subject: str,
    body_html: str,
    sender_domain: str = "",
    unsubscribe_url: str | None = None,
) -> dict:
    """Send a single email via the Resend API.

    Includes List-Unsubscribe header for CAN-SPAM compliance.

    Args:
        to_email: recipient email address
        sender: formatted sender (e.g. "Name <email>" or just "email")
        reply_to: optional reply-to address
        subject: email subject line
        body_html: HTML body content
        sender_domain: domain for List-Unsubscribe header (mailto fallback)
        unsubscribe_url: optional HTTPS URL for RFC 8058 one-click
            unsubscribe (BL-1103). When provided, included alongside the
            mailto fallback so modern Gmail/Outlook clients can present
            the native "Unsubscribe" button.

    Returns:
        dict with Resend response (includes 'id')

    Raises:
        Exception on API error
    """
    import resend

    # Open + click tracking is *not* configured here — Resend has no
    # per-send tracking flags. Tracking lives at the *domain* layer
    # (``PATCH /domains/{id}`` with ``open_tracking`` + ``click_tracking``
    # + ``tracking_subdomain``) and only activates once the tracking
    # CNAME is verified at the DNS provider. See ADR-011 and
    # ``scripts/configure_resend_tracking.py``.
    params = {
        "from": sender,
        "to": [to_email],
        "subject": subject,
        "html": body_html,
    }
    if reply_to:
        params["reply_to"] = [reply_to]

    # CAN-SPAM: List-Unsubscribe header
    # BL-1103: prefer the HTTPS URL variant (RFC 8058) when available,
    # but keep the mailto fallback for legacy clients.
    if sender_domain or unsubscribe_url:
        variants = []
        if unsubscribe_url:
            variants.append(f"<{unsubscribe_url}>")
        if sender_domain:
            variants.append(f"<mailto:unsubscribe@{sender_domain}?subject=unsubscribe>")
        params["headers"] = {
            "List-Unsubscribe": ", ".join(variants),
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }

    response = resend.Emails.send(params)

    # resend SDK returns an object with .id, convert to dict
    if hasattr(response, "id"):
        return {"id": response.id}
    if isinstance(response, dict):
        return response
    return {"id": str(response)}


def _replace_template_variables(html: str, variables: dict) -> str:
    """Replace ``{{variable}}`` placeholders in email HTML/text.

    Used by the EventFest (and future) template campaigns to inject
    per-contact values (vocative name, invite link, etc.) at send time.
    """
    for key, value in variables.items():
        html = html.replace("{{" + key + "}}", value or "")
    return html


def _template_type_for(campaign: "Campaign") -> str | None:
    """Extract the ``template_type`` from a campaign's generation_config."""
    cfg = campaign.generation_config or {}
    if isinstance(cfg, str):
        import json

        try:
            cfg = json.loads(cfg)
        except (ValueError, TypeError):
            return None
    if not isinstance(cfg, dict):
        return None
    value = cfg.get("template_type")
    return value if isinstance(value, str) and value else None


# Map from campaign template_type to template_registry key. Keeps the
# DB-stored ``template_type`` decoupled from internal registry naming so
# either side can evolve independently.
_TEMPLATE_TYPE_TO_REGISTRY_KEY: dict[str, str] = {
    "eventfest": "eventfest_invitation",
}


def _registry_key_for(template_type: str | None) -> str | None:
    """Map a campaign ``template_type`` to a template_registry key."""
    if not template_type:
        return None
    return _TEMPLATE_TYPE_TO_REGISTRY_KEY.get(template_type)


def _resolve_templated_body(
    *,
    campaign: "Campaign",
    contact: "Contact",
    template_variables: dict[str, str],
) -> dict | None:
    """Render the language-appropriate body for a templated campaign.

    Returns ``None`` when the campaign is not a templated campaign or no
    registry key is registered for its ``template_type``. In that case
    the caller should fall back to the legacy stored-body code path.

    Returns a dict with ``subject``, ``html``, ``text``, ``language_used``
    and ``fallback_used`` otherwise.
    """
    from . import template_registry as _tr

    template_type = _template_type_for(campaign)
    registry_key = _registry_key_for(template_type)
    if registry_key is None:
        return None

    # Pull the contact's language; ``None`` / empty / unsupported codes
    # let the registry fall back to its DEFAULT_LANGUAGE.
    language = (contact.language or "").strip() or None

    try:
        return _tr.render(registry_key, language, **template_variables)
    except KeyError:
        logger.exception(
            "template_registry: no renderer for campaign template_type=%s "
            "(registry_key=%s)",
            template_type,
            registry_key,
        )
        return None


def _build_template_variables(
    contact: "Contact",
    campaign_contact: "CampaignContact",
    campaign: "Campaign",
) -> dict[str, str]:
    """Build template variable dict for a contact in a template campaign.

    Returns an empty dict when no template variables are applicable
    (i.e. the campaign does not use a template_type).
    """
    from .campaign_attribution import add_campaign_attribution
    from .czech_vocative import to_vocative
    from .microsite_invites import get_or_create_invite

    template_type = _template_type_for(campaign)
    if not template_type:
        return {}

    first_name = contact.first_name or ""
    # to_vocative returns (vocative_form, source_tag) — unpack the form only.
    # Without this, str.replace() crashes with TypeError because the tuple
    # flows into _replace_template_variables. See Phase 4 TestSend validation.
    vocative_form, _source = to_vocative(first_name)

    # Per-recipient token feeds the ?t={{recipient_token}} placeholder that
    # the EventFest thumbnail grid bakes into each featured-act href.
    # Empty string when the campaign_contact has no token yet (e.g. UA
    # microsite was unreachable during provisioning); template degrades
    # to broken links but the send still goes out.
    recipient_token = getattr(campaign_contact, "microsite_partner_token", "") or ""

    variables: dict[str, str] = {
        "vocative_name": vocative_form,
        "first_name": first_name,
        "recipient_token": recipient_token,
    }

    # BL-1103: every template campaign gets the per-contact unsubscribe
    # URL injected as ``{{unsubscribe_url}}`` so the footer "Odhlasit se"
    # link points at the one-click flow with a valid HMAC token. Falls
    # back to a mailto so the footer is never broken.
    fallback = "mailto:unsubscribe@example.com?subject=unsubscribe"
    try:
        unsub_url = _build_unsubscribe_url(contact)
    except Exception:
        unsub_url = None
    variables["unsubscribe_url"] = unsub_url or fallback

    # Per-contact tone (Vy/Ty) switching — EventFest list contains ~6/357
    # tykat contacts; the rest are vykat (DB default on contacts.address_style).
    # Pull the tone map from the template module so both are authored in
    # one place; unknown/None values fall back to vykat inside tone_variables.
    if template_type == "eventfest":
        from .eventfest_template import tone_variables

        tone = getattr(contact, "address_style", None) or "vykat"
        variables.update(tone_variables(tone))

    # Microsite invite link — cached in campaign_contact metadata-like field
    # We store it on the Message or regenerate (idempotent by email)
    if template_type == "eventfest":
        import os

        from .eventfest_campaign import _extract_token

        microsite_url = os.environ.get("UA_MICROSITE_URL", "")
        api_key = os.environ.get("UA_INVITE_API_KEY", "")
        # Raw invite/fallback URL before campaign attribution is applied.
        raw_link = ""
        if microsite_url and api_key and contact.email_address:
            full_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
            try:
                invite_url = get_or_create_invite(
                    email=contact.email_address,
                    name=full_name,
                    microsite_url=microsite_url,
                    api_key=api_key,
                )
                raw_link = invite_url or microsite_url

                # Phase 4 Fix B: persist the partner token on the
                # campaign_contact row if missing, so the tracking ingest
                # path can resolve events back to this (campaign, contact)
                # pair. The send loop calls db.session.commit() after each
                # send, so just staging the change here is sufficient.
                if invite_url and not getattr(
                    campaign_contact, "microsite_partner_token", None
                ):
                    token = _extract_token(invite_url)
                    if token:
                        campaign_contact.microsite_partner_token = token
                        # Also surface it through the per-recipient variable
                        # now that we have it, rather than waiting for the
                        # NEXT send to pick it up from the DB.
                        variables["recipient_token"] = token
                        db.session.add(campaign_contact)
            except Exception:
                logger.warning(
                    "Failed to get invite for %s, using fallback",
                    contact.email_address,
                )
                raw_link = microsite_url
        elif microsite_url:
            raw_link = microsite_url

        # BL-1036: tag every microsite link with campaign attribution so
        # PostHog events can be filtered by `properties.campaign_id` +
        # `properties.recipient_id`. Using campaign_contact.id as the
        # recipient ID because it is durable across re-sends and
        # tenant-scoped. Non-microsite URLs are returned unchanged.
        variables["microsite_link"] = add_campaign_attribution(
            raw_link,
            campaign_id=str(campaign.id) if campaign and campaign.id else None,
            recipient_id=str(campaign_contact.id)
            if campaign_contact and campaign_contact.id
            else None,
            microsite_base_url=microsite_url or None,
        )

    return variables


def _build_unsubscribe_url(contact: "Contact") -> str | None:
    """Build the per-contact RFC 8058 HTTPS unsubscribe URL (BL-1103).

    Returns ``None`` when the request context or contact metadata makes
    URL construction impossible — callers treat that as "fall back to
    the mailto-only List-Unsubscribe header".

    The base URL is taken from (in order):
    1. ``FRONTEND_BASE_URL`` config — the customer-facing dashboard host.
    2. ``UNSUBSCRIBE_BASE_URL`` env override — escape hatch for staging.
    Falls back to ``https://leadgen.visionvolve.com`` to keep the URL
    actionable even in misconfigured dev runs.
    """
    if not contact or not contact.id or not contact.tenant_id:
        return None

    try:
        from ..routes.unsubscribe_routes import generate_unsubscribe_token

        token = generate_unsubscribe_token(contact)
    except Exception:
        logger.warning(
            "Unable to mint unsubscribe token for contact %s",
            getattr(contact, "id", None),
        )
        return None

    import os

    from flask import current_app

    base = (
        os.environ.get("UNSUBSCRIBE_BASE_URL")
        or current_app.config.get("FRONTEND_BASE_URL")
        or "https://leadgen.visionvolve.com"
    )
    base = base.rstrip("/")
    return f"{base}/api/unsubscribe?contact_id={contact.id}&token={token}"


def send_unsubscribe_confirmation(contact: "Contact", tenant: "Tenant | None") -> bool:
    """Send the one-shot "you've been unsubscribed" email (BL-1103).

    Called from the public POST /api/unsubscribe handler AFTER the
    contact has been flagged ``is_suppressed=True``. This must bypass
    the suppression gate (we just flipped it) — so we go straight to
    Resend rather than the campaign-send path.

    Returns ``True`` on success, ``False`` on any failure (logged). The
    caller never relies on this for correctness — the suppression is
    already persisted by the time we get here. A missed confirmation is
    a UX paper cut, not a compliance failure.
    """
    if not contact or not contact.email_address:
        return False

    if not tenant:
        tenant = db.session.get(Tenant, contact.tenant_id)
    tenant_settings = (tenant.settings if tenant else {}) or {}
    if isinstance(tenant_settings, str):
        import json

        try:
            tenant_settings = json.loads(tenant_settings)
        except Exception:
            tenant_settings = {}

    api_key = tenant_settings.get("resend_api_key")
    if not api_key:
        logger.warning(
            "send_unsubscribe_confirmation: tenant %s has no resend_api_key; skipping",
            contact.tenant_id,
        )
        return False

    sender_config = tenant_settings.get("sender_config") or {}
    from_email = sender_config.get("from_email") or sender_config.get("from") or ""
    from_name = sender_config.get("from_name") or (tenant.name if tenant else "")
    if not from_email:
        # No configured sender — fall back to a noreply alias on the
        # tenant's send domain if we can guess it from a previous send.
        from ..models import EmailSendLog

        last_send = (
            db.session.query(EmailSendLog)
            .filter(
                EmailSendLog.tenant_id == contact.tenant_id,
                EmailSendLog.from_email.isnot(None),
                EmailSendLog.status == "sent",
            )
            .order_by(EmailSendLog.sent_at.desc().nullslast())
            .first()
        )
        if last_send and last_send.from_email:
            from_email = last_send.from_email
            from_name = from_name or ""
    if not from_email:
        logger.warning(
            "send_unsubscribe_confirmation: no sender for tenant %s; skipping",
            contact.tenant_id,
        )
        return False

    tenant_name = (tenant.name if tenant else "") or "the team"
    first_name = (contact.first_name or "there").strip() or "there"
    subject = f"Unsubscribed from {tenant_name}"
    body_html = (
        "<!doctype html><html><body style='font-family:sans-serif;"
        "max-width:520px;margin:24px auto;color:#222;line-height:1.55;'>"
        f"<p>Hi {first_name},</p>"
        f"<p>You've been unsubscribed from emails sent by {tenant_name}. "
        "You won't receive further messages from us.</p>"
        "<p>If this was a mistake, just reply to this email and we'll "
        "restore your subscription.</p>"
        "</body></html>"
    )

    try:
        import resend

        resend.api_key = api_key
        sender = f"{from_name} <{from_email}>" if from_name else from_email
        result = _send_single_email(
            to_email=contact.email_address,
            sender=sender,
            reply_to=None,
            subject=subject,
            body_html=body_html,
            sender_domain="",  # no further unsubscribe header on a confirmation
            unsubscribe_url=None,
        )
        logger.info(
            "Sent unsubscribe confirmation to %s (tenant=%s, resend_id=%s)",
            contact.email_address,
            contact.tenant_id,
            (result or {}).get("id"),
        )
        return True
    except Exception:
        logger.exception(
            "Failed to send unsubscribe confirmation to %s (tenant=%s)",
            contact.email_address,
            contact.tenant_id,
        )
        return False


def _render_body_html(body: str) -> str:
    """Render message body as HTML.

    For now, wraps plain text in basic HTML with proper formatting.
    Phase 2 will add template support.
    """
    if not body:
        return "<p></p>"

    # If body already contains HTML tags, return as-is
    if "<" in body and ">" in body:
        return body

    # Convert plain text to HTML paragraphs
    paragraphs = body.strip().split("\n\n")
    html_parts = []
    for para in paragraphs:
        # Convert single newlines to <br>
        para_html = para.strip().replace("\n", "<br>")
        html_parts.append(f"<p>{para_html}</p>")

    return "\n".join(html_parts)


def get_send_status(campaign_id: str, tenant_id: str) -> dict:
    """Get email send status summary for a campaign.

    Returns:
        dict with total, queued, sent, delivered, failed, bounced counts
        plus quota information.
    """
    # Get all email send logs for this campaign's messages
    rows = db.session.execute(
        db.text("""
            SELECT esl.status, COUNT(*) AS cnt
            FROM email_send_log esl
            JOIN messages m ON esl.message_id = m.id
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
            GROUP BY esl.status
        """),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()

    status_counts = {r[0]: r[1] for r in rows}

    # Get quota info
    quota = get_quota_status(tenant_id)

    return {
        "total": sum(status_counts.values()),
        "queued": status_counts.get("queued", 0),
        "sent": status_counts.get("sent", 0),
        "delivered": status_counts.get("delivered", 0),
        "failed": status_counts.get("failed", 0),
        "bounced": status_counts.get("bounced", 0),
        "daily_remaining": quota["daily_remaining"],
        "hourly_remaining": quota["hourly_remaining"],
        "warmup_day": quota["warmup_day"],
        "warmup_limit": quota["warmup_limit"],
        "warmup_enabled": quota["warmup_enabled"],
    }


def send_campaign_emails_gmail(campaign_id: str, tenant_id: str) -> dict:
    """Send all approved email messages for a campaign via Gmail API.

    Uses the user's Gmail/GSuite account — emails appear in their Sent folder
    and come from their real email address.

    Idempotent: skips messages that already have a non-failed EmailSendLog entry.
    Enforces Gmail-specific daily/hourly quotas.

    Args:
        campaign_id: UUID of the campaign
        tenant_id: UUID of the tenant

    Returns:
        dict with sent_count, failed_count, skipped_count, total,
        validation_warnings, quota_stopped
    """
    from .gmail_send_service import send_via_gmail

    # 1. Load campaign and validate sender_config
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign or str(campaign.tenant_id) != str(tenant_id):
        raise ValueError("Campaign not found")

    sender_config = campaign.sender_config
    if isinstance(sender_config, str):
        import json

        sender_config = json.loads(sender_config)
    sender_config = sender_config or {}

    oauth_connection_id = sender_config.get("oauth_connection_id")
    if not oauth_connection_id:
        raise ValueError(
            "Campaign sender_config missing oauth_connection_id for Gmail sending"
        )

    reply_to = sender_config.get("reply_to")

    # 2. Load and validate OAuth connection
    oauth_conn = db.session.get(OAuthConnection, oauth_connection_id)
    if not oauth_conn:
        raise ValueError(f"OAuth connection {oauth_connection_id} not found")
    if oauth_conn.status != "active":
        raise ValueError(
            f"OAuth connection {oauth_connection_id} is {oauth_conn.status}, not active"
        )
    if str(oauth_conn.tenant_id) != str(tenant_id):
        raise ValueError("OAuth connection does not belong to this tenant")

    from_email = oauth_conn.provider_email

    # 3. Check Gmail-specific daily/hourly quotas
    sent_today = _count_sent_today(tenant_id)
    if sent_today >= GMAIL_DAILY_LIMIT:
        return {
            "sent_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "total": 0,
            "quota_stopped": True,
            "quota_message": (
                f"Gmail daily limit reached ({GMAIL_DAILY_LIMIT}). "
                f"Sent today: {sent_today}."
            ),
            "validation_warnings": [],
        }

    sent_this_hour = _count_sent_this_hour(tenant_id)
    if sent_this_hour >= GMAIL_HOURLY_LIMIT:
        return {
            "sent_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "total": 0,
            "quota_stopped": True,
            "quota_message": (
                f"Gmail hourly limit reached ({GMAIL_HOURLY_LIMIT}). "
                f"Sent this hour: {sent_this_hour}."
            ),
            "validation_warnings": [],
        }

    # 4. Load approved email messages not yet sent.
    # BL-1105: hard-filter Contact.is_suppressed so unsubscribed /
    # hard-bounced / complained contacts never receive a Gmail send.
    messages_data = (
        db.session.query(Message, Contact, CampaignContact)
        .join(CampaignContact, Message.campaign_contact_id == CampaignContact.id)
        .join(Contact, Message.contact_id == Contact.id)
        .filter(
            CampaignContact.campaign_id == campaign_id,
            CampaignContact.tenant_id == tenant_id,
            Message.status == "approved",
            Message.channel == "email",
            Contact.is_suppressed.is_(False),
        )
        .all()
    )

    # 5. Pre-send validation
    valid_messages, validation_warnings = _validate_recipients(messages_data)

    if validation_warnings:
        logger.warning(
            "Gmail pre-send validation for campaign %s: %d warnings out of %d messages",
            campaign_id,
            len(validation_warnings),
            len(messages_data),
        )

    logger.info(
        "Starting Gmail send for campaign %s: %d valid emails (delay=%ds)",
        campaign_id,
        len(valid_messages),
        GMAIL_DELAY_SECONDS,
    )

    sent_count = 0
    failed_count = 0
    skipped_count = 0
    quota_stopped = False
    quota_message = ""

    for message, contact, cc in valid_messages:
        # Idempotent check
        existing_log = (
            db.session.query(EmailSendLog)
            .filter(
                EmailSendLog.message_id == message.id,
                EmailSendLog.tenant_id == tenant_id,
                EmailSendLog.status != "failed",
            )
            .first()
        )
        if existing_log:
            skipped_count += 1
            continue

        # Re-check quotas before each send
        current_today = _count_sent_today(tenant_id)
        if current_today >= GMAIL_DAILY_LIMIT:
            quota_stopped = True
            quota_message = f"Gmail daily limit reached ({GMAIL_DAILY_LIMIT})."
            break

        current_hour = _count_sent_this_hour(tenant_id)
        if current_hour >= GMAIL_HOURLY_LIMIT:
            quota_stopped = True
            quota_message = f"Gmail hourly limit reached ({GMAIL_HOURLY_LIMIT})."
            break

        to_email = contact.email_address

        # Create queued log entry
        log = EmailSendLog(
            tenant_id=tenant_id,
            message_id=message.id,
            status="queued",
            from_email=from_email,
            to_email=to_email,
        )
        db.session.add(log)
        db.session.flush()

        body_html = _render_body_html(message.body)
        subject = message.subject or "(no subject)"

        # Template variable replacement (EventFest and future template campaigns)
        tpl_vars = _build_template_variables(contact, cc, campaign)
        if tpl_vars:
            # BL-1110: language-aware rendering via template registry.
            templated = _resolve_templated_body(
                campaign=campaign,
                contact=contact,
                template_variables=tpl_vars,
            )
            if templated is not None:
                body_html = templated["html"]
                subject = templated["subject"]
                log.template_language = templated["language_used"]
                log.template_language_fallback = templated["fallback_used"]
            else:
                body_html = _replace_template_variables(body_html, tpl_vars)

        try:
            gmail_message_id = send_via_gmail(
                oauth_connection=oauth_conn,
                to_email=to_email,
                subject=subject,
                body_html=body_html,
                reply_to=reply_to,
            )

            # Store Gmail message ID in resend_message_id field (reuse column)
            log.resend_message_id = gmail_message_id
            log.status = "sent"
            log.sent_at = datetime.now(timezone.utc)

            message.sent_at = datetime.now(timezone.utc)

            # BL-1029: mark any earlier failed attempts for this message as
            # superseded so audit queries count the delivery once.
            _mark_prior_failures_superseded(tenant_id, message.id, log.id)

            db.session.commit()
            sent_count += 1

        except Exception as e:
            logger.error("Gmail send failed for message %s: %s", message.id, str(e))
            log.status = "failed"
            log.error = str(e)[:500]
            db.session.commit()
            failed_count += 1

        # Gmail-specific delay (longer than Resend)
        time.sleep(GMAIL_DELAY_SECONDS)

    # Handle validation failures
    for warning in validation_warnings:
        if warning["issue"] == "no_email":
            log = EmailSendLog(
                tenant_id=tenant_id,
                message_id=warning["message_id"],
                status="failed",
                from_email=from_email,
                error=f"Pre-send validation: {warning['detail']}",
            )
            db.session.add(log)
            failed_count += 1

    if validation_warnings:
        db.session.commit()

    result = {
        "sent_count": sent_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "total": sent_count + failed_count + skipped_count,
        "quota_stopped": quota_stopped,
        "validation_warnings": validation_warnings,
    }
    if quota_message:
        result["quota_message"] = quota_message

    return result
