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

    # 5. Load approved email messages not yet sent (idempotent check)
    messages_data = (
        db.session.query(Message, Contact, CampaignContact)
        .join(CampaignContact, Message.campaign_contact_id == CampaignContact.id)
        .join(Contact, Message.contact_id == Contact.id)
        .filter(
            CampaignContact.campaign_id == campaign_id,
            CampaignContact.tenant_id == tenant_id,
            Message.status == "approved",
            Message.channel == "email",
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

        # Template variable replacement (EventFest and future template campaigns)
        tpl_vars = _build_template_variables(contact, cc, campaign)
        if tpl_vars:
            body_html = _replace_template_variables(body_html, tpl_vars)

        sender = f"{from_name} <{from_email}>" if from_name else from_email

        try:
            result = _send_single_email(
                to_email=to_email,
                sender=sender,
                reply_to=reply_to,
                subject=message.subject or "(no subject)",
                body_html=body_html,
                sender_domain=sender_domain,
            )

            # Update log with success
            log.resend_message_id = result.get("id")
            log.status = "sent"
            log.sent_at = datetime.now(timezone.utc)

            # Update message sent_at
            message.sent_at = datetime.now(timezone.utc)

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
) -> dict:
    """Send a single email via the Resend API.

    Includes List-Unsubscribe header for CAN-SPAM compliance.

    Args:
        to_email: recipient email address
        sender: formatted sender (e.g. "Name <email>" or just "email")
        reply_to: optional reply-to address
        subject: email subject line
        body_html: HTML body content
        sender_domain: domain for List-Unsubscribe header

    Returns:
        dict with Resend response (includes 'id')

    Raises:
        Exception on API error
    """
    import resend

    params = {
        "from_": sender,
        "to": [to_email],
        "subject": subject,
        "html": body_html,
    }
    if reply_to:
        params["reply_to"] = [reply_to]

    # CAN-SPAM: List-Unsubscribe header
    if sender_domain:
        params["headers"] = {
            "List-Unsubscribe": (
                f"<mailto:unsubscribe@{sender_domain}?subject=unsubscribe>"
            ),
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


def _build_template_variables(
    contact: "Contact",
    campaign_contact: "CampaignContact",
    campaign: "Campaign",
) -> dict[str, str]:
    """Build template variable dict for a contact in a template campaign.

    Returns an empty dict when no template variables are applicable
    (i.e. the campaign does not use a template_type).
    """
    from .czech_vocative import to_vocative
    from .microsite_invites import get_or_create_invite

    template_type = (campaign.generation_config or {}).get("template_type")
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
    recipient_token = (
        getattr(campaign_contact, "microsite_partner_token", "") or ""
    )

    variables: dict[str, str] = {
        "vocative_name": vocative_form,
        "first_name": first_name,
        "recipient_token": recipient_token,
    }

    # Per-contact tone (Vy/Ty) switching — EventFest list contains ~6/357
    # tykat contacts; the rest are vykat (DB default on contacts.address_style).
    # Pull the tone map from the template module so both are authored in
    # one place; unknown/None values fall back to vykat inside tone_variables.
    if template_type == "eventfest":
        from .eventfest_template import tone_variables

        tone = (getattr(contact, "address_style", None) or "vykat")
        variables.update(tone_variables(tone))

    # Microsite invite link — cached in campaign_contact metadata-like field
    # We store it on the Message or regenerate (idempotent by email)
    if template_type == "eventfest":
        import os

        microsite_url = os.environ.get("UA_MICROSITE_URL", "")
        api_key = os.environ.get("UA_INVITE_API_KEY", "")
        if microsite_url and api_key and contact.email_address:
            full_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
            try:
                invite_url = get_or_create_invite(
                    email=contact.email_address,
                    name=full_name,
                    microsite_url=microsite_url,
                    api_key=api_key,
                )
                variables["microsite_link"] = invite_url
            except Exception:
                logger.warning(
                    "Failed to get invite for %s, using fallback",
                    contact.email_address,
                )
                variables["microsite_link"] = microsite_url
        elif microsite_url:
            variables["microsite_link"] = microsite_url
        else:
            variables["microsite_link"] = ""

    return variables


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

    # 4. Load approved email messages not yet sent
    messages_data = (
        db.session.query(Message, Contact, CampaignContact)
        .join(CampaignContact, Message.campaign_contact_id == CampaignContact.id)
        .join(Contact, Message.contact_id == Contact.id)
        .filter(
            CampaignContact.campaign_id == campaign_id,
            CampaignContact.tenant_id == tenant_id,
            Message.status == "approved",
            Message.channel == "email",
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

        # Template variable replacement (EventFest and future template campaigns)
        tpl_vars = _build_template_variables(contact, cc, campaign)
        if tpl_vars:
            body_html = _replace_template_variables(body_html, tpl_vars)

        try:
            gmail_message_id = send_via_gmail(
                oauth_connection=oauth_conn,
                to_email=to_email,
                subject=message.subject or "(no subject)",
                body_html=body_html,
                reply_to=reply_to,
            )

            # Store Gmail message ID in resend_message_id field (reuse column)
            log.resend_message_id = gmail_message_id
            log.status = "sent"
            log.sent_at = datetime.now(timezone.utc)

            message.sent_at = datetime.now(timezone.utc)

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
