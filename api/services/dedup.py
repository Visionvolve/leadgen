"""Contact and company deduplication service.

Dedup hierarchy (checked in priority order):
  Contact: LinkedIn URL → Email → Full name + company name
  Company: Domain → Name (case-insensitive)

Strategies:
  skip       - skip duplicate rows (default)
  update     - fill empty fields on the existing record
  create_new - always create new record (ignore duplicates)

Companies always link to existing when matched (never duplicate).
"""

from sqlalchemy import func

from ..models import Company, Contact, db
from .phone_normalize import normalize_phone


def normalize_domain(url):
    """Normalize a domain/URL for comparison: strip protocol, www, trailing path."""
    if not url:
        return None
    url = url.strip().lower()
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            url = url[len(prefix) :]
            break
    if url.startswith("www."):
        url = url[4:]
    url = url.split("/")[0].split("?")[0].split("#")[0]
    return url if url else None


def find_existing_company(tenant_id, name=None, domain=None):
    """Find an existing company by domain (priority) or name.

    Returns (Company, match_type) or (None, None).
    """
    if domain:
        norm = normalize_domain(domain)
        if norm:
            match = Company.query.filter(
                Company.tenant_id == str(tenant_id),
                func.lower(Company.domain) == norm,
            ).first()
            if match:
                return match, "domain"

    if name:
        match = Company.query.filter(
            Company.tenant_id == str(tenant_id),
            func.lower(Company.name) == name.strip().lower(),
        ).first()
        if match:
            return match, "name"

    return None, None


def find_existing_contact(
    tenant_id,
    linkedin_url=None,
    email=None,
    first_name=None,
    last_name=None,
    company_name=None,
):
    """Find an existing contact by LinkedIn URL, email, or name+company.

    Returns (Contact, match_type) or (None, None).
    """
    if linkedin_url:
        url = linkedin_url.strip().lower().rstrip("/")
        match = Contact.query.filter(
            Contact.tenant_id == str(tenant_id),
            func.lower(Contact.linkedin_url) == url,
        ).first()
        if match:
            return match, "linkedin_url"

    if email:
        email_lower = email.strip().lower()
        match = Contact.query.filter(
            Contact.tenant_id == str(tenant_id),
            func.lower(Contact.email_address) == email_lower,
        ).first()
        if match:
            return match, "email"

    if first_name and company_name:
        match = (
            Contact.query.filter(
                Contact.tenant_id == str(tenant_id),
                func.lower(Contact.first_name) == first_name.strip().lower(),
                func.lower(Contact.last_name) == (last_name or "").strip().lower(),
            )
            .join(Company, Contact.company_id == Company.id)
            .filter(
                func.lower(Company.name) == company_name.strip().lower(),
            )
            .first()
        )
        if match:
            return match, "name_company"

    return None, None


def update_empty_fields(existing, new_data, fields):
    """Fill empty fields on an existing record from new_data dict.

    Only updates fields that are currently NULL/empty on the existing record.
    Also merges _custom_fields if present.
    Returns (updated_fields, conflicts) where:
      - updated_fields: list of field names that were updated
      - conflicts: list of {field, existing, incoming} dicts for non-empty mismatches
    """
    updated = []
    conflicts = []
    for field in fields:
        if field not in new_data or not new_data[field]:
            continue
        current = getattr(existing, field, None)
        if not current:
            setattr(existing, field, new_data[field])
            updated.append(field)
        elif str(current).strip().lower() != str(new_data[field]).strip().lower():
            conflicts.append(
                {
                    "field": field,
                    "existing": str(current),
                    "incoming": str(new_data[field]),
                }
            )

    # Merge custom fields
    if "_custom_fields" in new_data and new_data["_custom_fields"]:
        import json

        existing_cf = getattr(existing, "custom_fields", None) or {}
        if isinstance(existing_cf, str):
            existing_cf = json.loads(existing_cf)
        for k, v in new_data["_custom_fields"].items():
            if k not in existing_cf or not existing_cf[k]:
                existing_cf[k] = v
        existing.custom_fields = existing_cf
        updated.append("custom_fields")

    return updated, conflicts


CONTACT_UPDATABLE_FIELDS = [
    "job_title",
    "email_address",
    "linkedin_url",
    "phone_number",
    "location_city",
    "location_country",
    "seniority_level",
    "department",
    "contact_source",
    "language",
]

COMPANY_UPDATABLE_FIELDS = [
    "domain",
    "industry",
    "hq_city",
    "hq_country",
    "company_size",
    "business_model",
]


def dedup_preview(tenant_id, parsed_rows):
    """Preview dedup results for a set of parsed rows.

    Args:
        tenant_id: tenant UUID string
        parsed_rows: list of dicts with 'contact' and 'company' sub-dicts

    Returns:
        list of dicts, each with:
          - contact: mapped contact fields
          - company: mapped company fields
          - contact_status: 'new' | 'duplicate'
          - contact_match_type: None | 'linkedin_url' | 'email' | 'name_company'
          - company_status: 'new' | 'existing'
          - company_match_type: None | 'domain' | 'name'
    """
    results = []
    # Track companies/contacts seen within this import to detect intra-file dups
    seen_domains = {}  # normalized_domain → index
    seen_names = {}  # lower(name) → index
    seen_linkedin = {}  # lower(url) → index
    seen_emails = {}  # lower(email) → index

    for i, row in enumerate(parsed_rows):
        contact_data = row.get("contact", {})
        company_data = row.get("company", {})

        result = {
            "contact": contact_data,
            "company": company_data,
            "contact_status": "new",
            "contact_match_type": None,
            "company_status": "new",
            "company_match_type": None,
        }

        # Company dedup
        co_domain = normalize_domain(company_data.get("domain"))
        co_name = (company_data.get("name") or "").strip().lower()

        if co_domain or co_name:
            existing_co, match_type = find_existing_company(
                tenant_id,
                name=company_data.get("name"),
                domain=company_data.get("domain"),
            )
            if existing_co:
                result["company_status"] = "existing"
                result["company_match_type"] = match_type
            elif co_domain and co_domain in seen_domains:
                result["company_status"] = "existing"
                result["company_match_type"] = "domain_intra"
            elif co_name and co_name in seen_names:
                result["company_status"] = "existing"
                result["company_match_type"] = "name_intra"

        if co_domain:
            seen_domains[co_domain] = i
        if co_name:
            seen_names[co_name] = i

        # Contact dedup
        linkedin = (contact_data.get("linkedin_url") or "").strip().lower().rstrip("/")
        email = (contact_data.get("email_address") or "").strip().lower()

        existing_ct, match_type = find_existing_contact(
            tenant_id,
            linkedin_url=contact_data.get("linkedin_url"),
            email=contact_data.get("email_address"),
            first_name=contact_data.get("first_name"),
            last_name=contact_data.get("last_name"),
            company_name=company_data.get("name"),
        )
        if existing_ct:
            result["contact_status"] = "duplicate"
            result["contact_match_type"] = match_type
        elif linkedin and linkedin in seen_linkedin:
            result["contact_status"] = "duplicate"
            result["contact_match_type"] = "linkedin_intra"
        elif email and email in seen_emails:
            result["contact_status"] = "duplicate"
            result["contact_match_type"] = "email_intra"

        if linkedin:
            seen_linkedin[linkedin] = i
        if email:
            seen_emails[email] = i

        results.append(result)

    return results


def execute_import(
    tenant_id, parsed_rows, tag_id, owner_id, import_job_id, strategy="skip"
):
    """Execute the actual import of parsed rows into DB.

    Args:
        tenant_id: tenant UUID string
        parsed_rows: list of dicts with 'contact' and 'company' sub-dicts
        tag_id: tag UUID string
        owner_id: owner UUID string or None
        import_job_id: import job UUID string
        strategy: 'skip' | 'update' | 'create_new'

    Returns:
        dict with:
          counts: contacts_created, contacts_updated, contacts_skipped,
                  companies_created, companies_linked
          dedup_rows: list of per-row detail dicts (non-"created" rows for large imports)
    """
    counts = {
        "contacts_created": 0,
        "contacts_updated": 0,
        "contacts_skipped": 0,
        "companies_created": 0,
        "companies_linked": 0,
    }
    dedup_rows = []
    large_import = len(parsed_rows) > 1000

    # Cache companies created within this import: normalized_domain → Company, lower(name) → Company
    import_company_cache_domain = {}
    import_company_cache_name = {}

    for row_idx, row in enumerate(parsed_rows):
        contact_data = row.get("contact", {})
        company_data = row.get("company", {})

        # Normalize phone number at import time
        if contact_data.get("phone_number"):
            contact_data["phone_number"] = normalize_phone(contact_data["phone_number"])

        contact_name = contact_data.get("full_name", "") or (
            f"{contact_data.get('first_name', '')} {contact_data.get('last_name', '')}".strip()
        )
        company_name_display = company_data.get("name", "")

        # --- Resolve or create company ---
        company_id = None
        co_name = company_data.get("name")
        co_domain = company_data.get("domain")

        if co_name or co_domain:
            # Check DB
            existing_co, _ = find_existing_company(
                tenant_id, name=co_name, domain=co_domain
            )

            if existing_co:
                company_id = existing_co.id
                # Always fill empty fields on matched company
                updated, _co_conflicts = update_empty_fields(
                    existing_co, company_data, COMPANY_UPDATABLE_FIELDS
                )
                if updated:
                    existing_co.import_job_id = import_job_id
                counts["companies_linked"] += 1
            else:
                # Check intra-import cache
                norm_domain = normalize_domain(co_domain)
                norm_name = (co_name or "").strip().lower()
                cached = None
                if norm_domain and norm_domain in import_company_cache_domain:
                    cached = import_company_cache_domain[norm_domain]
                elif norm_name and norm_name in import_company_cache_name:
                    cached = import_company_cache_name[norm_name]

                if cached:
                    company_id = cached.id
                    counts["companies_linked"] += 1
                else:
                    # Create new company
                    new_co = Company(
                        tenant_id=str(tenant_id),
                        name=co_name or (co_domain or "Unknown"),
                        domain=normalize_domain(co_domain) if co_domain else None,
                        tag_id=str(tag_id),
                        owner_id=str(owner_id) if owner_id else None,
                        status="new",
                        industry=company_data.get("industry"),
                        hq_city=company_data.get("hq_city"),
                        hq_country=company_data.get("hq_country"),
                        company_size=company_data.get("company_size"),
                        business_model=company_data.get("business_model"),
                        custom_fields=company_data.get("_custom_fields") or {},
                        import_job_id=str(import_job_id),
                    )
                    db.session.add(new_co)
                    db.session.flush()
                    company_id = new_co.id
                    counts["companies_created"] += 1
                    if norm_domain:
                        import_company_cache_domain[norm_domain] = new_co
                    if norm_name:
                        import_company_cache_name[norm_name] = new_co

        # --- Resolve or create contact ---
        first_name = contact_data.get("first_name")
        if not first_name:
            counts["contacts_skipped"] += 1
            dedup_rows.append(
                {
                    "row_idx": row_idx,
                    "action": "error",
                    "contact_name": contact_name,
                    "company_name": company_name_display,
                    "reason": "no_name",
                }
            )
            continue

        existing_ct, match_type = find_existing_contact(
            tenant_id,
            linkedin_url=contact_data.get("linkedin_url"),
            email=contact_data.get("email_address"),
            first_name=first_name,
            last_name=contact_data.get("last_name"),
            company_name=co_name,
        )

        if existing_ct:
            if strategy == "skip":
                counts["contacts_skipped"] += 1
                dedup_rows.append(
                    {
                        "row_idx": row_idx,
                        "action": "skipped",
                        "contact_name": contact_name,
                        "company_name": company_name_display,
                        "match_type": match_type,
                        "matched_contact_id": str(existing_ct.id),
                        "matched_contact_name": existing_ct.full_name,
                    }
                )
            elif strategy == "update":
                updated, ct_conflicts = update_empty_fields(
                    existing_ct, contact_data, CONTACT_UPDATABLE_FIELDS
                )
                if company_id and not existing_ct.company_id:
                    existing_ct.company_id = company_id
                if owner_id and not existing_ct.owner_id:
                    existing_ct.owner_id = str(owner_id)
                if not existing_ct.tag_id:
                    existing_ct.tag_id = str(tag_id)
                existing_ct.import_job_id = str(import_job_id)
                counts["contacts_updated"] += 1
                dedup_rows.append(
                    {
                        "row_idx": row_idx,
                        "action": "updated",
                        "contact_name": contact_name,
                        "company_name": company_name_display,
                        "fields_updated": updated,
                        "conflicts": ct_conflicts,
                    }
                )
            elif strategy == "create_new":
                _create_contact(
                    tenant_id,
                    contact_data,
                    company_id,
                    tag_id,
                    owner_id,
                    import_job_id,
                )
                counts["contacts_created"] += 1
                if not large_import:
                    dedup_rows.append(
                        {
                            "row_idx": row_idx,
                            "action": "created",
                            "contact_name": contact_name,
                            "company_name": company_name_display,
                        }
                    )
        else:
            _create_contact(
                tenant_id,
                contact_data,
                company_id,
                tag_id,
                owner_id,
                import_job_id,
            )
            counts["contacts_created"] += 1
            if not large_import:
                dedup_rows.append(
                    {
                        "row_idx": row_idx,
                        "action": "created",
                        "contact_name": contact_name,
                        "company_name": company_name_display,
                    }
                )

    db.session.flush()
    return {
        "counts": counts,
        "dedup_rows": dedup_rows,
    }


def _create_contact(
    tenant_id, contact_data, company_id, tag_id, owner_id, import_job_id
):
    """Create a new contact record."""
    ct = Contact(
        tenant_id=str(tenant_id),
        company_id=str(company_id) if company_id else None,
        owner_id=str(owner_id) if owner_id else None,
        tag_id=str(tag_id),
        first_name=contact_data["first_name"],
        last_name=contact_data.get("last_name", ""),
        job_title=contact_data.get("job_title"),
        email_address=contact_data.get("email_address"),
        linkedin_url=contact_data.get("linkedin_url"),
        phone_number=normalize_phone(contact_data.get("phone_number")),
        location_city=contact_data.get("location_city"),
        location_country=contact_data.get("location_country"),
        seniority_level=contact_data.get("seniority_level"),
        department=contact_data.get("department"),
        contact_source=contact_data.get("contact_source"),
        language=contact_data.get("language"),
        custom_fields=contact_data.get("_custom_fields") or {},
        import_job_id=str(import_job_id),
    )
    db.session.add(ct)
    return ct
