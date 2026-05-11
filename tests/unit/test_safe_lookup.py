"""Unit tests for ``api/utils/safe_lookup.py``.

These cover the pure validators (no DB needed) plus ``safe_get`` happy
paths against the in-memory SQLite test database. The SQLAlchemyError
branch is exercised indirectly by the route-level bad-input tests in
``test_ref_tokens.py``, ``test_smart_lists.py``, etc. — under SQLite
the dialect tolerates string-shaped UUIDs so we can't trip the same
error PostgreSQL raises in production, but the format guards in the
route handlers stop garbage well before the driver ever sees it.
"""

from __future__ import annotations

import uuid

from api.utils.safe_lookup import (
    is_valid_ref_token,
    is_valid_uuid,
    safe_first,
    safe_get,
)


class TestIsValidUuid:
    def test_valid_hyphenated_uuid_returns_true(self):
        assert is_valid_uuid(str(uuid.uuid4())) is True

    def test_valid_unhyphenated_uuid_returns_true(self):
        assert is_valid_uuid(uuid.uuid4().hex) is True

    def test_empty_string_returns_false(self):
        assert is_valid_uuid("") is False

    def test_none_returns_false(self):
        assert is_valid_uuid(None) is False

    def test_non_string_returns_false(self):
        assert is_valid_uuid(12345) is False  # type: ignore[arg-type]

    def test_bogus_string_returns_false(self):
        assert is_valid_uuid("bogus") is False

    def test_sql_injection_attempt_returns_false(self):
        assert is_valid_uuid("'; DROP TABLE contacts; --") is False

    def test_almost_uuid_returns_false(self):
        # Too short.
        assert is_valid_uuid("12345") is False
        # Wrong chars in otherwise valid shape.
        assert is_valid_uuid("zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz") is False


class TestIsValidRefToken:
    def test_32_uppercase_base32_returns_true(self):
        assert is_valid_ref_token("A" * 32) is True
        assert is_valid_ref_token("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567") is True

    def test_lowercase_returns_false(self):
        # Generator emits uppercase, so we only accept uppercase.
        assert is_valid_ref_token("a" * 32) is False

    def test_too_short_returns_false(self):
        assert is_valid_ref_token("ABC") is False

    def test_too_long_returns_false(self):
        assert is_valid_ref_token("A" * 33) is False

    def test_empty_returns_false(self):
        assert is_valid_ref_token("") is False
        assert is_valid_ref_token(None) is False

    def test_digits_in_alphabet_returns_true(self):
        # We intentionally accept the broader ``A-Z0-9`` set so historical
        # test fixtures and any tokens seeded with ``0/1`` pass through.
        assert is_valid_ref_token("0" * 32) is True
        assert is_valid_ref_token("EXPIRED" + "0" * 25) is True

    def test_punctuation_returns_false(self):
        assert is_valid_ref_token("!" * 32) is False
        assert is_valid_ref_token("-" * 32) is False

    def test_bogus_returns_false(self):
        assert is_valid_ref_token("bogus") is False


class TestSafeGet:
    def test_returns_row_when_found(self, db, seed_tenant):
        from api.models import Tenant

        row = safe_get(Tenant, seed_tenant.id)
        assert row is not None
        assert row.id == seed_tenant.id

    def test_returns_none_for_unknown_id(self, db, seed_tenant):
        from api.models import Tenant

        # A well-formed but not-present id. Under SQLite this is a plain
        # SELECT-no-row; the helper just returns None.
        row = safe_get(Tenant, str(uuid.uuid4()))
        assert row is None

    def test_returns_none_for_none_pk(self, db, seed_tenant):
        from api.models import Tenant

        assert safe_get(Tenant, None) is None


class TestSafeFirst:
    def test_returns_row_when_found(self, db, seed_tenant):
        from api.models import Tenant

        q = Tenant.query.filter_by(id=seed_tenant.id)
        row = safe_first(q)
        assert row is not None
        assert row.id == seed_tenant.id

    def test_returns_none_when_not_found(self, db, seed_tenant):
        from api.models import Tenant

        q = Tenant.query.filter_by(slug="definitely-not-a-slug-xyz")
        assert safe_first(q) is None
