"""Company-name normalization for duplicate detection (BL-1203 / Phase 12).

Pure function: deterministic, no side effects, idempotent. Stored output
lives in `companies.normalized_name` and is indexed for exact-match
lookups in `find_name_collisions`.

Algorithm (locked in 12-CONTEXT.md):
  1. trim leading/trailing whitespace; collapse internal whitespace runs.
  2. lowercase.
  3. NFKD normalize and remove combining marks (diacritic strip).
  4. Replace punctuation `,.&()[]'"/\\-_` with a single space.
  5. Iteratively strip trailing legal suffixes (longest-first match)
     until none match. Suffixes are stripped only as standalone trailing
     tokens (preceded by space or covering the whole string).
  6. Collapse whitespace runs again; final trim.

Empty/None input or input that normalizes to an empty string returns "".
"""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy import event

# Canonical lowercased forms. ORDER MATTERS: the iterative stripper checks
# each suffix in turn and removes the first match it finds. Place longer /
# more specific suffixes BEFORE the shorter ones they contain, so
# "spol s r o" gets stripped before just "s r o" / "s o".
LEGAL_SUFFIXES: list[str] = [
    "spol s r o",
    "spol s ro",
    "s r o",
    "sro",
    "v o s",
    "vos",
    "k s",
    "ks",
    "company",
    "limited",
    "gmbh",
    "mbh",
    "ltd",
    "corp",
    "llc",
    "inc",
    "co",
    "a s",
    "as",
    "ag",
    "kg",
]

# Punctuation we map to whitespace. Hyphen + underscore are included so
# "A-B" / "A_B" normalize to "a b".
_PUNCT_TO_SPACE_RE = re.compile(r"[,.&()\[\]'\"/\\\-_]")
_WS_RE = re.compile(r"\s+")


def normalize_company_name(s: str | None) -> str:
    """Return the deterministic normalized form of a company name."""
    if s is None:
        return ""
    s = s.strip()
    if not s:
        return ""
    # 2. lowercase
    s = s.lower()
    # 3. NFKD + strip combining marks
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    # 4. punctuation → space (incl. hyphen + underscore)
    s = _PUNCT_TO_SPACE_RE.sub(" ", s)
    # 5a. collapse whitespace before suffix stripping
    s = _WS_RE.sub(" ", s).strip()
    # 5b. iteratively strip trailing legal suffixes
    while True:
        stripped = False
        for suf in LEGAL_SUFFIXES:
            if s == suf:
                s = ""
                stripped = True
                break
            if s.endswith(" " + suf):
                s = s[: -(len(suf) + 1)].rstrip()
                stripped = True
                break
        if not stripped:
            break
    # 6. final collapse + trim
    s = _WS_RE.sub(" ", s).strip()
    return s


def _sync_normalized(mapper, connection, target):
    """SQLAlchemy listener: keep `normalized_name` in sync with `name`.

    Runs on every Company INSERT/UPDATE through the ORM. Raw-SQL writes
    still need to set normalized_name themselves (see PATCH handler).
    """
    if hasattr(target, "name"):
        target.normalized_name = normalize_company_name(target.name)


def register_listeners() -> None:
    """Wire the SQLAlchemy listeners. Idempotent."""
    # Late import to avoid circular import at module load time
    from ..models import Company

    if not event.contains(Company, "before_insert", _sync_normalized):
        event.listen(Company, "before_insert", _sync_normalized)
    if not event.contains(Company, "before_update", _sync_normalized):
        event.listen(Company, "before_update", _sync_normalized)
