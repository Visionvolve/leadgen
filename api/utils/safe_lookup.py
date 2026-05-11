"""Shared safe-lookup helpers for untrusted URL parameters.

Use these instead of ``db.session.get`` when the id/token comes from a
URL path parameter or query string. They catch ``SQLAlchemyError``
(e.g. ``InvalidTextRepresentation`` on PostgreSQL when a malformed UUID
or out-of-range varchar is passed) and return ``None`` instead of
raising — so the request lands as a clean 400/404 rather than a 500.

This module is the canonical fix for the "500 on bad input" anti-pattern
that has bitten v25 multiple times (PR #175 fixed it for
``/api/unsubscribe``; this hardens the rest of the new endpoints).
"""

from __future__ import annotations

import logging
import re
from typing import Type, TypeVar
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from ..models import db

logger = logging.getLogger(__name__)

T = TypeVar("T")

# UUID accepts both hyphenated (36 char) and unhyphenated (32 char) forms.
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{32,36}$")

# Ref-tokens (and other CHAR(32) tokens generated via ``base64.b32encode``)
# are 32 uppercase base32 characters with no padding. We intentionally
# allow ``A-Z0-9`` rather than strict ``A-Z2-7`` to also pass through
# test fixtures and any historical tokens that may have been seeded
# with the broader alphabet — the goal is to reject obviously malformed
# inputs (lengths != 32, lowercase, punctuation) before they hit the DB,
# not to perfectly police the alphabet.
_REF_TOKEN_RE = re.compile(r"^[A-Z0-9]{32}$")


def is_valid_uuid(value: str | None) -> bool:
    """Return True if *value* parses as a UUID — never raises."""
    if not value or not isinstance(value, str):
        return False
    if not _UUID_RE.match(value):
        return False
    try:
        UUID(value)
        return True
    except (ValueError, TypeError):
        return False


def is_valid_ref_token(value: str | None) -> bool:
    """Return True if *value* matches the 32-char base32 ref-token shape."""
    if not value or not isinstance(value, str):
        return False
    return bool(_REF_TOKEN_RE.match(value))


def safe_get(model: Type[T], pk: str | None) -> T | None:
    """Return the row or None — never raises.

    On any ``SQLAlchemyError`` (the common one being PostgreSQL's
    ``InvalidTextRepresentation`` for a malformed UUID or out-of-range
    varchar) we roll back so the session isn't poisoned for subsequent
    requests on the same connection, log a warning, and return None.
    The caller treats this the same as "row not found".
    """
    if pk is None:
        return None
    try:
        return db.session.get(model, pk)
    except SQLAlchemyError:
        logger.warning(
            "safe_get: DB lookup failed for model=%s pk=%r",
            getattr(model, "__name__", model),
            pk,
            exc_info=True,
        )
        try:
            db.session.rollback()
        except SQLAlchemyError:
            logger.exception("safe_get: session rollback also failed")
        return None


def safe_first(query):
    """Execute ``query.first()`` and swallow SQLAlchemyError → None.

    Use this for ``Model.query.filter_by(...).first()`` paths that take
    untrusted input — same rationale as ``safe_get``.
    """
    try:
        return query.first()
    except SQLAlchemyError:
        logger.warning("safe_first: DB query failed", exc_info=True)
        try:
            db.session.rollback()
        except SQLAlchemyError:
            logger.exception("safe_first: session rollback also failed")
        return None
