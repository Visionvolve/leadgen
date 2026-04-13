"""Gmail scanner: background thread that extracts contacts from email headers and signatures.

Architecture:
1. Header extraction (deterministic): Parse From/To/CC/Reply-To fields
2. Signature extraction (AI): Claude Haiku extracts structured data from signature blocks
3. Aggregation: Merge by email, most recent info wins
"""

import email.utils
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from ..models import ImportJob, OAuthConnection, db
from .google_oauth import get_valid_token
from .phone_normalize import normalize_phone

logger = logging.getLogger(__name__)

# Domains to always exclude (service emails, mailing lists)
DEFAULT_EXCLUDE_DOMAINS = {
    "noreply",
    "no-reply",
    "donotreply",
    "notifications",
    "mailer-daemon",
    "postmaster",
    "bounce",
    "automated",
    "system",
}

# Patterns that indicate a service email (skip these)
SERVICE_EMAIL_PATTERNS = re.compile(
    r"(noreply|no-reply|donotreply|notifications?|mailer-daemon|"
    r"bounce|automated|system|support|info|feedback|news|digest|"
    r"updates?|calendar-notification|drive-shares)@",
    re.IGNORECASE,
)

# Signature block detection patterns
SIGNATURE_DELIMITERS = [
    re.compile(r"^--\s*$", re.MULTILINE),
    re.compile(r"^_{3,}$", re.MULTILINE),
    re.compile(r"^-{3,}$", re.MULTILINE),
    re.compile(
        r"^(Best|Kind|Warm)?\s*(Regards|regards|Wishes|wishes),?\s*$", re.MULTILINE
    ),
    re.compile(r"^(Thanks|Cheers|Sincerely|Yours),?\s*$", re.MULTILINE),
    re.compile(r"^Sent from my (iPhone|iPad|Android|Galaxy)", re.MULTILINE),
]

# Patterns suggesting a line is part of a signature
SIG_LINE_PATTERNS = [
    re.compile(r"\+?\d[\d\s\-().]{7,}"),  # phone number
    re.compile(r"linkedin\.com/in/", re.IGNORECASE),  # LinkedIn URL
    re.compile(r"https?://\S+", re.IGNORECASE),  # Any URL
    re.compile(r"\|"),  # pipe separator (common in sigs)
]


class GmailScanner:
    """Scans Gmail messages and extracts contact information."""

    def __init__(self, connection_id, job_id, config):
        self.connection_id = connection_id
        self.job_id = job_id
        self.config = config or {}
        self.contacts = {}  # email -> aggregated contact data
        self.messages_scanned = 0
        self.signatures_extracted = 0

    def run(self, app):
        """Main entry point -- runs in a daemon thread with app context."""
        with app.app_context():
            try:
                self._update_progress("scanning_headers", 0)
                self._scan_messages()
                self._update_progress("extracting_signatures", 50)
                self._extract_signatures(app)
                self._update_progress("aggregating", 90)
                self._aggregate_contacts()
                self._save_extracted()
                self._update_status("extracted")
                logger.info(
                    "Gmail scan %s complete: %d contacts from %d messages",
                    self.job_id,
                    len(self.contacts),
                    self.messages_scanned,
                )
            except Exception as e:
                logger.error("Gmail scan %s failed: %s", self.job_id, e)
                self._update_status("error", error=str(e))

    def _update_progress(self, phase, percent, contacts_found=None):
        """Update scan_progress JSONB on ImportJob."""
        from datetime import datetime, timezone

        job = db.session.get(ImportJob, self.job_id)
        if not job:
            return
        progress = {
            "phase": phase,
            "percent": percent,
            "messages_scanned": self.messages_scanned,
            "contacts_found": contacts_found or len(self.contacts),
        }
        job.scan_progress = json.dumps(progress)
        job.updated_at = datetime.now(timezone.utc)
        db.session.commit()

    def _update_status(self, status, error=None):
        """Update ImportJob status."""
        job = db.session.get(ImportJob, self.job_id)
        if not job:
            return
        job.status = status
        if error:
            job.error = error[:1000]
        db.session.commit()

    def _get_gmail_service(self):
        """Build Gmail API service with fresh token."""
        conn = db.session.get(OAuthConnection, self.connection_id)
        if not conn:
            raise RuntimeError(f"OAuth connection {self.connection_id} not found")
        access_token = get_valid_token(conn)
        db.session.commit()
        creds = Credentials(token=access_token)
        return build("gmail", "v1", credentials=creds)

    def _scan_messages(self):
        """Scan Gmail messages and extract contacts from headers."""
        service = self._get_gmail_service()
        exclude_domains = set(
            d.lower().strip() for d in self.config.get("exclude_domains", [])
        )
        max_messages = self.config.get("max_messages", 5000)
        date_range = self.config.get("date_range")

        # Build Gmail search query
        query_parts = []
        if date_range and date_range > 0:
            from datetime import timedelta

            after_date = datetime.now(timezone.utc) - timedelta(days=date_range)
            query_parts.append(f"after:{after_date.strftime('%Y/%m/%d')}")

        query = " ".join(query_parts) if query_parts else None
        page_token = None

        first_request = True
        while self.messages_scanned < max_messages:
            try:
                # List messages first, then get headers
                list_kwargs = {
                    "userId": "me",
                    "maxResults": min(100, max_messages - self.messages_scanned),
                }
                if query:
                    list_kwargs["q"] = query
                if page_token:
                    list_kwargs["pageToken"] = page_token

                results = service.users().messages().list(**list_kwargs).execute()
                first_request = False
                messages = results.get("messages", [])

                if not messages:
                    break

                # Get message headers individually
                for msg_stub in messages:
                    if self.messages_scanned >= max_messages:
                        break
                    try:
                        msg = (
                            service.users()
                            .messages()
                            .get(
                                userId="me",
                                id=msg_stub["id"],
                                format="metadata",
                                metadataHeaders=[
                                    "From",
                                    "To",
                                    "Cc",
                                    "Reply-To",
                                    "Date",
                                ],
                            )
                            .execute()
                        )
                        self._process_message_headers(msg, exclude_domains)
                        self.messages_scanned += 1
                    except Exception as e:
                        logger.debug("Failed to get message %s: %s", msg_stub["id"], e)
                        self.messages_scanned += 1

                page_token = results.get("nextPageToken")
                if not page_token:
                    break

                # Update progress periodically
                if self.messages_scanned % 20 == 0:
                    pct = min(45, int(self.messages_scanned / max_messages * 45))
                    self._update_progress("scanning_headers", pct)

            except Exception as e:
                logger.error("Gmail list error: %s", e)
                if first_request:
                    # First API call failed — likely auth/scope error, surface it
                    raise
                break

    def _process_message_headers(self, message, exclude_domains):
        """Extract contacts from a single message's headers."""
        headers = {
            h["name"]: h["value"] for h in message.get("payload", {}).get("headers", [])
        }

        # Parse date for recency tracking
        date_str = headers.get("Date", "")
        msg_date = self._parse_date(date_str)

        # Extract addresses from From, To, Cc, Reply-To
        for field in ["From", "To", "Cc", "Reply-To"]:
            value = headers.get(field, "")
            if not value:
                continue
            addresses = email.utils.getaddresses([value])
            for display_name, addr in addresses:
                addr = addr.strip().lower()
                if not addr or "@" not in addr:
                    continue

                domain = addr.split("@", 1)[1]

                # Skip excluded domains
                if domain in exclude_domains:
                    continue

                # Skip service emails
                if SERVICE_EMAIL_PATTERNS.match(addr):
                    continue

                # Skip local part matching common service patterns
                local = addr.split("@")[0]
                if local in DEFAULT_EXCLUDE_DOMAINS:
                    continue

                # Initialize or update contact
                if addr not in self.contacts:
                    first, last = self._split_display_name(display_name)
                    self.contacts[addr] = {
                        "email": addr,
                        "first_name": first,
                        "last_name": last,
                        "domain": domain,
                        "message_count": 0,
                        "last_message_date": None,
                        "message_id_for_sig": message.get("id"),
                    }

                contact = self.contacts[addr]
                contact["message_count"] += 1

                # Update with most recent data
                if msg_date and (
                    not contact["last_message_date"]
                    or msg_date > contact["last_message_date"]
                ):
                    contact["last_message_date"] = msg_date
                    contact["message_id_for_sig"] = message.get("id")
                    # Update name if we got a better one
                    if display_name and not contact["first_name"]:
                        first, last = self._split_display_name(display_name)
                        contact["first_name"] = first
                        contact["last_name"] = last

    def _extract_signatures(self, app):
        """For unique senders, fetch most recent email body and extract signature data."""
        if not self.contacts:
            return

        service = self._get_gmail_service()

        # Collect unique message IDs to fetch (one per sender)
        msg_ids_to_fetch = {}
        for addr, contact in self.contacts.items():
            mid = contact.get("message_id_for_sig")
            if mid and mid not in msg_ids_to_fetch:
                msg_ids_to_fetch[mid] = addr

        # Fetch message bodies and extract signature blocks
        signatures = {}  # email -> signature text
        for msg_id, addr in msg_ids_to_fetch.items():
            try:
                msg = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=msg_id,
                        format="full",
                    )
                    .execute()
                )
                body = self._extract_text_body(msg)
                if body:
                    sig = self._extract_signature_block(body)
                    if sig and len(sig) > 10:
                        signatures[addr] = sig
            except Exception as e:
                logger.debug("Failed to get body for %s: %s", msg_id, e)

        if not signatures:
            return

        # Batch Claude calls for signature extraction
        self._batch_extract_with_claude(app, signatures)

    def _batch_extract_with_claude(self, app, signatures):
        """Send signatures to Claude Haiku in batches for structured extraction."""
        from ..services.llm_logger import log_llm_usage

        try:
            import anthropic

            client = anthropic.Anthropic()
        except Exception:
            logger.warning(
                "Anthropic client not available, skipping signature extraction"
            )
            return

        sig_items = list(signatures.items())
        batch_size = 15
        job = db.session.get(ImportJob, self.job_id)

        for i in range(0, len(sig_items), batch_size):
            batch = sig_items[i : i + batch_size]

            # Build prompt
            prompt_parts = []
            for idx, (addr, sig_text) in enumerate(batch):
                prompt_parts.append(f"[{idx}] Email: {addr}\nSignature:\n{sig_text}\n")

            prompt = (
                "Extract structured contact information from these email signatures. "
                "For each numbered entry, return a JSON array with objects containing: "
                "index, name, job_title, company, phone, linkedin_url. "
                "Only include fields you can confidently extract. "
                "Return ONLY valid JSON, no other text.\n\n" + "\n".join(prompt_parts)
            )

            try:
                start_ms = int(time.time() * 1000)
                response = client.messages.create(
                    model="claude-haiku-3-5-20241022",
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                )
                duration_ms = int(time.time() * 1000) - start_ms

                # Log usage
                if job:
                    log_llm_usage(
                        tenant_id=str(job.tenant_id),
                        operation="gmail_signature_extraction",
                        model="claude-haiku-3-5-20241022",
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                        duration_ms=duration_ms,
                        metadata={
                            "import_job_id": str(self.job_id),
                            "batch_index": i // batch_size,
                            "signatures_in_batch": len(batch),
                        },
                    )
                    db.session.commit()

                # Parse response
                text_content = response.content[0].text
                try:
                    extracted = json.loads(text_content)
                except json.JSONDecodeError:
                    # Try to find JSON array in response
                    match = re.search(r"\[.*\]", text_content, re.DOTALL)
                    if match:
                        extracted = json.loads(match.group())
                    else:
                        continue

                # Apply extracted data to contacts
                for item in extracted:
                    idx = item.get("index", -1)
                    if 0 <= idx < len(batch):
                        addr = batch[idx][0]
                        if addr in self.contacts:
                            c = self.contacts[addr]
                            if item.get("job_title"):
                                c["job_title"] = item["job_title"]
                            if item.get("company"):
                                c["company_name"] = item["company"]
                            if item.get("phone"):
                                c["phone"] = item["phone"]
                            if item.get("linkedin_url"):
                                c["linkedin_url"] = item["linkedin_url"]
                            if item.get("name") and not c.get("first_name"):
                                parts = (item["name"] or "").split(None, 1)
                                c["first_name"] = parts[0] if parts else ""
                                c["last_name"] = parts[1] if len(parts) > 1 else ""
                            self.signatures_extracted += 1

            except Exception as e:
                logger.warning("Claude signature extraction batch failed: %s", e)

    def _aggregate_contacts(self):
        """Final aggregation pass -- build dedup-compatible rows."""
        # Already aggregated by email in self.contacts
        pass

    def _save_extracted(self):
        """Save extracted contacts to ImportJob.raw_csv as JSON rows."""
        rows = []
        for addr, c in self.contacts.items():
            first_name = c.get("first_name", "")
            if not first_name:
                first_name = addr.split("@")[0]

            contact_data = {
                "first_name": first_name,
                "last_name": c.get("last_name", ""),
                "email_address": addr,
                "contact_source": "gmail_scan",
            }
            if c.get("job_title"):
                contact_data["job_title"] = c["job_title"]
            if c.get("phone"):
                contact_data["phone_number"] = normalize_phone(c["phone"])
            if c.get("linkedin_url"):
                contact_data["linkedin_url"] = c["linkedin_url"]

            company_data = {}
            if c.get("company_name"):
                company_data["name"] = c["company_name"]
            if c.get("domain"):
                company_data["domain"] = c["domain"]

            rows.append(
                {
                    "contact": contact_data,
                    "company": company_data,
                }
            )

        job = db.session.get(ImportJob, self.job_id)
        if job:
            job.raw_csv = json.dumps(rows)
            job.total_rows = len(rows)
            progress = {
                "phase": "complete",
                "percent": 100,
                "messages_scanned": self.messages_scanned,
                "contacts_found": len(rows),
                "signatures_extracted": self.signatures_extracted,
            }
            job.scan_progress = json.dumps(progress)
            db.session.commit()

    # ---- Utility methods ----

    @staticmethod
    def _split_display_name(name):
        """Split email display name into first + last."""
        if not name:
            return "", ""
        # Remove quotes
        name = name.strip().strip('"').strip("'")
        parts = name.split(None, 1)
        first = parts[0] if parts else ""
        last = parts[1] if len(parts) > 1 else ""
        return first, last

    @staticmethod
    def _parse_date(date_str):
        """Parse email Date header to datetime."""
        if not date_str:
            return None
        try:
            parsed = email.utils.parsedate_to_datetime(date_str)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            return None

    @staticmethod
    def _extract_text_body(message):
        """Extract plain text body from Gmail message payload."""
        import base64

        payload = message.get("payload", {})

        # Direct body
        if payload.get("mimeType", "").startswith("text/plain"):
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        # Multipart -- find text/plain part
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode(
                        "utf-8", errors="replace"
                    )
            # Nested multipart
            for sub in part.get("parts", []):
                if sub.get("mimeType") == "text/plain":
                    data = sub.get("body", {}).get("data", "")
                    if data:
                        return base64.urlsafe_b64decode(data).decode(
                            "utf-8", errors="replace"
                        )

        return None

    @staticmethod
    def _extract_signature_block(body):
        """Heuristic extraction of email signature from body text."""
        if not body:
            return None

        lines = body.split("\n")

        # Try delimiter-based extraction
        for pattern in SIGNATURE_DELIMITERS:
            for i, line in enumerate(lines):
                if pattern.search(line):
                    sig = "\n".join(lines[i:])
                    if 10 < len(sig) < 1000:
                        return sig.strip()

        # Fallback: look for signature patterns in last 15 lines
        tail = lines[-15:]
        sig_lines = []
        for line in tail:
            for p in SIG_LINE_PATTERNS:
                if p.search(line):
                    sig_lines.append(line)
                    break

        if sig_lines:
            # Include surrounding context
            start_idx = max(0, len(lines) - 15)
            return "\n".join(lines[start_idx:]).strip()

        return None


def start_gmail_scan(app, oauth_connection, job_id, config):
    """Spawn a background thread to run the Gmail scan."""
    scanner = GmailScanner(str(oauth_connection.id), job_id, config)
    t = threading.Thread(
        target=scanner.run,
        args=(app._get_current_object(),),
        daemon=True,
        name=f"gmail-scan-{job_id}",
    )
    t.start()
    return t


def quick_scan(oauth_connection, config):
    """Synchronous Gmail scan — fast, headers only, no AI. For preview.

    Returns (contacts_dict, messages_scanned).
    """
    from .google_oauth import get_valid_token

    access_token = get_valid_token(oauth_connection)
    db.session.commit()

    creds = Credentials(token=access_token)
    service = build("gmail", "v1", credentials=creds)

    exclude_domains = set(d.lower().strip() for d in config.get("exclude_domains", []))
    max_messages = config.get("max_messages", 200)
    date_range = config.get("date_range")

    # Build query
    query_parts = []
    if date_range and date_range > 0:
        from datetime import timedelta

        after_date = datetime.now(timezone.utc) - timedelta(days=date_range)
        query_parts.append(f"after:{after_date.strftime('%Y/%m/%d')}")
    query = " ".join(query_parts) if query_parts else None

    # List message IDs (fast — just IDs, no content)
    msg_ids = []
    page_token = None
    while len(msg_ids) < max_messages:
        list_kwargs = {
            "userId": "me",
            "maxResults": min(100, max_messages - len(msg_ids)),
        }
        if query:
            list_kwargs["q"] = query
        if page_token:
            list_kwargs["pageToken"] = page_token
        results = service.users().messages().list(**list_kwargs).execute()
        for m in results.get("messages", []):
            msg_ids.append(m["id"])
        page_token = results.get("nextPageToken")
        if not page_token:
            break

    # Batch-fetch headers (up to 100 per batch request)
    contacts = {}
    messages_scanned = 0

    def _batch_callback(request_id, response, exception):
        nonlocal messages_scanned
        messages_scanned += 1
        if exception:
            return
        headers = {
            h["name"]: h["value"]
            for h in response.get("payload", {}).get("headers", [])
        }
        for field in ["From", "To", "Cc", "Reply-To"]:
            value = headers.get(field, "")
            if not value:
                continue
            addresses = email.utils.getaddresses([value])
            for display_name, addr in addresses:
                addr = addr.strip().lower()
                if not addr or "@" not in addr:
                    continue
                domain = addr.split("@", 1)[1]
                if domain in exclude_domains:
                    continue
                if SERVICE_EMAIL_PATTERNS.match(addr):
                    continue
                local = addr.split("@")[0]
                if local in DEFAULT_EXCLUDE_DOMAINS:
                    continue
                if addr not in contacts:
                    first, last = GmailScanner._split_display_name(display_name)
                    contacts[addr] = {
                        "email": addr,
                        "first_name": first,
                        "last_name": last,
                        "domain": domain,
                        "message_count": 0,
                    }
                contacts[addr]["message_count"] += 1

    # Execute in batches of 100
    for i in range(0, len(msg_ids), 100):
        batch = service.new_batch_http_request(callback=_batch_callback)
        for mid in msg_ids[i : i + 100]:
            batch.add(
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=mid,
                    format="metadata",
                    metadataHeaders=["From", "To", "Cc", "Reply-To"],
                )
            )
        batch.execute()

    return contacts, messages_scanned
