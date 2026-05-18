"""Helpers for contact / company editing flows.

Split out of `api.routes.contact_routes` so the same logic (salutation
derivation, email validation, field-change audit writes) can be reused by
import pipelines and other server-side mutation paths without dragging in
HTTP framework objects.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy import text as sa_text

from ..models import db
from .czech_vocative import to_vocative

# RFC-5322 is overkill for an inline-edit gate; reject only obvious garbage
# (no `@`, whitespace inside, missing TLD). The mailbox itself is verified by
# the send pipeline downstream.
_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(value: str | None) -> bool:
    """True if *value* superficially looks like an email address.

    Empty / null is permitted -- clearing an email is a valid edit.
    """
    if value is None or value == "":
        return True
    return bool(_EMAIL_REGEX.match(value.strip()))


def derive_salutation(first_name: str | None) -> str | None:
    """Compute the auto-derived salutation for *first_name*.

    Returns ``None`` when no first name is available. Uses the Czech vocative
    engine (`api.services.czech_vocative.to_vocative`), which is safe to call
    with non-Czech names: it falls back to nominative.
    """
    if not first_name or not str(first_name).strip():
        return None
    vocative, _source = to_vocative(str(first_name).strip())
    return vocative or None


def write_field_change(
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    field_name: str,
    old_value: Any,
    new_value: Any,
    changed_by: str | None,
    source: str = "user_patch",
    metadata: dict | None = None,
) -> None:
    """Append an audit row to `contact_field_changes`.

    Caller is responsible for committing the surrounding transaction. The
    insert is intentionally written via raw SQL so the function is identical
    on PostgreSQL and the SQLite test backend (which patches `gen_random_uuid`
    out via the `_uuid_default` shim in `tests/conftest.py`).

    The optional ``metadata`` kwarg (BL-1203 / migration 074) is JSON-encoded
    and persisted in the ``metadata`` JSONB column. On SQLite (test backend)
    the column is mapped to TEXT, so we pass a JSON string in both dialects;
    Postgres implicitly casts a string literal to JSONB on insert.
    """

    def _coerce(v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            return v
        return str(v)

    db.session.execute(
        sa_text(
            """
            INSERT INTO contact_field_changes
                (id, tenant_id, entity_type, entity_id, field_name,
                 old_value, new_value, changed_by, source, metadata)
            VALUES
                (:id, :tenant_id, :entity_type, :entity_id, :field_name,
                 :old_value, :new_value, :changed_by, :source, :metadata)
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "field_name": field_name,
            "old_value": _coerce(old_value),
            "new_value": _coerce(new_value),
            "changed_by": changed_by,
            "source": source,
            "metadata": json.dumps(metadata or {}),
        },
    )
