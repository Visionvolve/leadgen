"""Unit tests for api.services.name_normalize.normalize_company_name.

Locked algorithm per .planning/phases/12-…/12-CONTEXT.md:
  1. trim + collapse internal whitespace
  2. lowercase
  3. NFKD + strip combining marks
  4. punctuation → space (, . & ( ) [ ] ' " / \\ - _)
  5. iteratively strip trailing legal suffixes (longest-first)
  6. final whitespace collapse + trim
"""

import pytest

from api.services.name_normalize import normalize_company_name


@pytest.mark.parametrize(
    "raw,expected",
    [
        # EMPTY / WHITESPACE
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("\t\n ", ""),
        # ASCII BASIC
        ("Acme", "acme"),
        ("  ACME  ", "acme"),
        ("Acme   Corp", "acme"),
        ("Acme, Inc.", "acme"),
        # CZECH DIACRITICS
        ("Škoda", "skoda"),
        ("Žižkov a.s.", "zizkov"),
        # CZECH LEGAL SUFFIXES
        ("Foo s.r.o.", "foo"),
        ("Foo s. r. o.", "foo"),
        ("Foo sro", "foo"),
        ("Foo S.R.O.", "foo"),
        ("Foo a.s.", "foo"),
        ("Foo as", "foo"),
        ("Foo spol. s r.o.", "foo"),
        ("Foo spol s r o", "foo"),
        ("Foo v.o.s.", "foo"),
        ("Foo k.s.", "foo"),
        # DE LEGAL SUFFIXES
        ("Foo GmbH", "foo"),
        ("Foo AG", "foo"),
        ("Foo mbH", "foo"),
        ("Foo KG", "foo"),
        # EN LEGAL SUFFIXES
        ("Foo Ltd", "foo"),
        ("Foo Limited", "foo"),
        ("Foo LLC", "foo"),
        ("Foo Inc", "foo"),
        ("Foo Inc.", "foo"),
        ("Foo Corp", "foo"),
        ("Foo Co.", "foo"),
        ("Foo Company", "foo"),
        # MID-STRING SUFFIX (MUST NOT STRIP MID-NAME — only trailing token)
        ("Limited Edition Ltd", "limited edition"),
        ("GmbH Holdings Inc", "gmbh holdings"),
        # PUNCTUATION
        ("A & B", "a b"),
        ("A-B Co", "a b"),
        ("A_B", "a b"),
        ("(Foo) [Bar]", "foo bar"),
        ("Foo/Bar", "foo bar"),
        # ALL-SUFFIX EDGE CASE
        ("s.r.o.", ""),
        ("GmbH", ""),
    ],
)
def test_normalize_company_name_table(raw, expected):
    assert normalize_company_name(raw) == expected


def test_legal_suffixes_exported():
    from api.services.name_normalize import LEGAL_SUFFIXES

    assert isinstance(LEGAL_SUFFIXES, list)
    assert len(LEGAL_SUFFIXES) > 0
    # Spot-checks for required entries
    for must in ("s r o", "sro", "a s", "as", "gmbh", "ltd", "inc", "llc"):
        assert must in LEGAL_SUFFIXES


def test_idempotent():
    """Re-normalizing already-normalized output is a no-op."""
    raw = "Černý a Synové s.r.o."
    once = normalize_company_name(raw)
    twice = normalize_company_name(once)
    assert once == twice
