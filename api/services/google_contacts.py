"""Google Contacts service: fetch from People API and map to import format."""

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from .google_oauth import get_valid_token
from .phone_normalize import normalize_phone


def fetch_google_contacts(oauth_connection):
    """Fetch all contacts from Google People API.

    Args:
        oauth_connection: OAuthConnection instance with valid tokens

    Returns:
        list of raw person resources from People API
    """
    access_token = get_valid_token(oauth_connection)

    creds = Credentials(token=access_token)
    service = build("people", "v1", credentials=creds)

    all_contacts = []
    page_token = None

    while True:
        results = (
            service.people()
            .connections()
            .list(
                resourceName="people/me",
                pageSize=1000,
                personFields="names,emailAddresses,organizations,phoneNumbers",
                pageToken=page_token,
            )
            .execute()
        )

        connections = results.get("connections", [])
        all_contacts.extend(connections)

        page_token = results.get("nextPageToken")
        if not page_token:
            break

    return all_contacts


def _extract_domain(email):
    """Extract domain from email address."""
    if not email or "@" not in email:
        return None
    return email.split("@", 1)[1].lower()


def _split_name(display_name):
    """Split display name into first + last. Handles edge cases."""
    if not display_name:
        return "", ""
    parts = display_name.strip().split(None, 1)
    first = parts[0] if parts else ""
    last = parts[1] if len(parts) > 1 else ""
    return first, last


def parse_contacts_to_rows(raw_contacts):
    """Map People API contacts to the dedup-compatible format.

    Args:
        raw_contacts: list of person resources from People API

    Returns:
        list of {"contact": {...}, "company": {...}} dicts
        matching dedup.dedup_preview() / execute_import() input format.
    """
    rows = []

    for person in raw_contacts:
        # Extract primary or first name
        names = person.get("names", [])
        first_name = ""
        last_name = ""
        if names:
            primary = names[0]
            first_name = primary.get("givenName", "")
            last_name = primary.get("familyName", "")
            if not first_name and not last_name:
                display = primary.get("displayName", "")
                first_name, last_name = _split_name(display)

        # Extract primary email
        emails = person.get("emailAddresses", [])
        email = emails[0].get("value", "") if emails else ""

        # Extract organization (first one)
        orgs = person.get("organizations", [])
        company_name = ""
        job_title = ""
        if orgs:
            company_name = orgs[0].get("name", "")
            job_title = orgs[0].get("title", "")

        # Extract phone
        phones = person.get("phoneNumbers", [])
        phone = phones[0].get("value", "") if phones else ""

        # Skip contacts with no name and no email
        if not first_name and not email:
            continue

        # If we have email but no name, use email prefix as first_name
        if not first_name and email:
            first_name = email.split("@")[0]

        # Build domain from email
        domain = _extract_domain(email)

        contact_data = {
            "first_name": first_name,
            "last_name": last_name,
            "email_address": email,
            "job_title": job_title,
            "phone_number": normalize_phone(phone),
            "contact_source": "google_contacts",
        }

        company_data = {}
        if company_name:
            company_data["name"] = company_name
        if domain:
            company_data["domain"] = domain

        rows.append(
            {
                "contact": contact_data,
                "company": company_data,
            }
        )

    return rows
