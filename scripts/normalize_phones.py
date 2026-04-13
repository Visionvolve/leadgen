#!/usr/bin/env python3
"""One-time script to normalize phone numbers for the united-arts tenant.

Run via: docker exec leadgen-api python /app/scripts/normalize_phones.py
Or locally: python scripts/normalize_phones.py
"""

import os
import sys
import re

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def normalize_phone(raw):
    """Normalize a phone number string (standalone copy for script use)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # Strip trailing .0 from float-like values
    s = re.sub(r"\.0+$", "", s)
    has_plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None
    if has_plus:
        result = f"+{digits}"
    elif digits.startswith("00420"):
        result = f"+{digits[2:]}"
    elif digits.startswith("420") and len(digits) >= 12:
        result = f"+{digits}"
    elif len(digits) == 9 and digits[0] in "234567":
        result = f"+420{digits}"
    else:
        if len(digits) >= 10:
            result = f"+{digits}"
        else:
            result = digits
    return result


def main():
    import psycopg2

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    # Find the united-arts tenant
    cur.execute("SELECT id FROM tenants WHERE slug = 'united-arts'")
    row = cur.fetchone()
    if not row:
        print("Tenant 'united-arts' not found, checking all tenants...")
        cur.execute("SELECT id, slug FROM tenants")
        tenants = cur.fetchall()
        for t in tenants:
            print(f"  {t[0]} = {t[1]}")
        print("\nRunning for ALL tenants with phone numbers.")
        tenant_filter = ""
        params = ()
    else:
        tenant_id = row[0]
        print(f"Found united-arts tenant: {tenant_id}")
        tenant_filter = "AND tenant_id = %s"
        params = (tenant_id,)

    # Fetch all contacts with phone numbers
    cur.execute(
        f"SELECT id, phone_number FROM contacts WHERE phone_number IS NOT NULL AND phone_number != '' {tenant_filter}",
        params,
    )
    rows = cur.fetchall()
    print(f"Found {len(rows)} contacts with phone numbers")

    updated = 0
    samples = []

    for contact_id, old_phone in rows:
        new_phone = normalize_phone(old_phone)
        if new_phone and new_phone != old_phone:
            cur.execute(
                "UPDATE contacts SET phone_number = %s WHERE id = %s",
                (new_phone, contact_id),
            )
            updated += 1
            if len(samples) < 10:
                samples.append((old_phone, new_phone))

    conn.commit()
    cur.close()
    conn.close()

    print(f"\nUpdated {updated} of {len(rows)} phone numbers")
    if samples:
        print("\nSample changes:")
        for old, new in samples:
            print(f"  {old!r:30s} -> {new!r}")
    else:
        print("No changes needed — all phone numbers already normalized.")


if __name__ == "__main__":
    main()
