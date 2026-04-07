"""Gmail API email sending service.

Sends outreach emails through a user's Gmail/GSuite account via the
Gmail API. Emails appear in the user's Sent folder and come from their
real email address.
"""

from __future__ import annotations

import base64
import logging
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .google_oauth import get_valid_token, has_send_scope

logger = logging.getLogger(__name__)

# ── Gmail rate limits (conservative) ─────────────────────
# GSuite Workspace: 2,000/day.  Free Gmail: 500/day.
# We stay well under to protect sender reputation.

GMAIL_DELAY_SECONDS = 45  # ~80 emails/hour
GMAIL_DAILY_LIMIT = 100
GMAIL_HOURLY_LIMIT = 20


def _strip_html(html: str) -> str:
    """Convert HTML to plain text (basic)."""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def send_via_gmail(
    oauth_connection,
    to_email: str,
    subject: str,
    body_html: str,
    reply_to: str | None = None,
) -> str:
    """Send an email through the user's Gmail account via Gmail API.

    Args:
        oauth_connection: OAuthConnection model instance (must have gmail.send scope)
        to_email: Recipient email address
        subject: Email subject line
        body_html: HTML body content
        reply_to: Optional reply-to address

    Returns:
        Gmail message ID string

    Raises:
        ValueError: If connection lacks send scope or is not active
        Exception: On Gmail API errors
    """
    if oauth_connection.status != "active":
        raise ValueError("OAuth connection is not active")

    if not has_send_scope(oauth_connection):
        raise ValueError(
            "OAuth connection does not have gmail.send scope. "
            "User must re-authorize with send permission."
        )

    # Get a valid (auto-refreshed) access token
    access_token = get_valid_token(oauth_connection)

    # Build MIME message with both plain text and HTML parts
    from_email = oauth_connection.provider_email
    msg = MIMEMultipart("alternative")
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["From"] = from_email
    if reply_to:
        msg["Reply-To"] = reply_to

    # Plain text fallback + HTML
    text_part = MIMEText(_strip_html(body_html), "plain")
    html_part = MIMEText(body_html, "html")
    msg.attach(text_part)
    msg.attach(html_part)

    # Encode for Gmail API
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    # Send via Gmail API
    creds = Credentials(token=access_token)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    result = service.users().messages().send(userId="me", body={"raw": raw}).execute()

    gmail_message_id = result.get("id", "")
    logger.info(
        "Gmail send OK: to=%s, gmail_id=%s, from=%s",
        to_email,
        gmail_message_id,
        from_email,
    )
    return gmail_message_id
