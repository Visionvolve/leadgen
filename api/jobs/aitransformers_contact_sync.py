"""AITransformers contact sync (BL-1200).

Scheduled job that pulls authenticated AITransformers users out of the
cases-api ``GET /admin/leads-export`` endpoint and lands them as contacts
in the Visionvolve namespace of leadgen-pipeline, tagged with
``AITransformers`` so the campaign layer can target them as an audience.

Design spec
-----------
``docs/superpowers/specs/2026-05-13-aitransformers-contact-sync-design.md``.

Key invariants
--------------
- **Strictly additive merge** — ``fill_if_empty`` never overwrites a
  non-empty leadgen value. Manual dashboard edits survive every resync.
- **Stable identity** — the AITransformers ``iam_id`` is stored in
  ``Contact.custom_fields["aitransformers"]["iam_id"]`` and is the
  primary upsert key. Falls back to ``email_address`` so legacy contacts
  that pre-date the sync get adopted on first run.
- **Per-row commit** — a single bad row never aborts the run. Failures
  are counted in ``errors`` and logged with the ``iam_id``.
- **Idempotent tagging** — tag assignment uses raw SQL
  ``ON CONFLICT DO NOTHING`` against the existing
  ``contact_tag_assignments_contact_id_tag_id_key`` unique constraint.
- **Single-writer** — a Postgres advisory lock keyed on
  ``aitransformers-sync:<tenant_id>`` serializes overlapping cron + CLI
  invocations. The lock is a no-op on the SQLite test backend.

Schema mapping (resolved against ``api/models.py`` during planning)
-------------------------------------------------------------------
AITransformers payload field → leadgen ``Contact`` column

- ``iam_id``             → ``custom_fields.aitransformers.iam_id`` (primary key)
- ``email``              → ``email_address`` (lower-cased)
- ``name`` / ``display_name`` → ``first_name`` + ``last_name`` (split on first space)
- ``role``               → ``job_title``
- ``company``            → ``custom_fields.aitransformers.company`` (no Company row created)
- ``industry``           → ``custom_fields.aitransformers.industry``
- ``company_size``       → ``custom_fields.aitransformers.company_size``
- ``maturity_level``     → ``custom_fields.aitransformers.maturity_level``
- ``tier``               → ``custom_fields.aitransformers.tier``
- ``is_founding_member`` → ``custom_fields.aitransformers.is_founding_member``
- ``newsletter_subscribed`` → ``custom_fields.aitransformers.aitransformers_newsletter_subscribed``
  (renamed deliberately: this is the AITransformers platform's local
  ``email_subscriptions.status='active'`` derivation, NOT the IAM
  ``newsletter`` scope of record. Prefix avoids future confusion if we
  ever sync an authoritative IAM-side flag.)
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Iterator, Optional

import requests
from sqlalchemy import text as sql_text
from sqlalchemy.orm.attributes import flag_modified

from ..models import Contact, ContactTagAssignment, Tag, Tenant, db

logger = logging.getLogger(__name__)

# Config defaults — overridable via env. Mirrors spec section 7.
DEFAULT_API_URL = "https://aitransformers.eu/api"
DEFAULT_TENANT_SLUG = "visionvolve"
DEFAULT_BATCH_SIZE = 200
DEFAULT_TAG_NAME = "AITransformers"

_HTTP_TIMEOUT_SECONDS = 30
_HTTP_RETRY_BACKOFF_SECONDS = (1, 4, 16)
_AITRANSFORMERS_NS = "aitransformers"  # custom_fields namespace key
_LOCK_NS = "aitransformers-sync"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class SyncConfig:
    """Container for resolved env-var configuration.

    Bundled into a class (rather than a free function) so tests can build
    one explicitly without monkey-patching ``os.environ`` mid-run.
    """

    def __init__(
        self,
        api_url: str,
        admin_token: str,
        tenant_slug: str,
        batch_size: int,
        tag_name: str,
    ):
        self.api_url = api_url.rstrip("/")
        self.admin_token = admin_token
        self.tenant_slug = tenant_slug
        self.batch_size = batch_size
        self.tag_name = tag_name


def load_config() -> SyncConfig:
    """Build a :class:`SyncConfig` from environment variables.

    Required: ``AITRANSFORMERS_ADMIN_TOKEN``. All others fall back to the
    defaults documented in the design spec.

    Raises
    ------
    RuntimeError
        When ``AITRANSFORMERS_ADMIN_TOKEN`` is unset.
    """
    token = os.environ.get("AITRANSFORMERS_ADMIN_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "AITRANSFORMERS_ADMIN_TOKEN is not set — refusing to run the "
            "AITransformers contact sync without an admin service token."
        )

    try:
        batch_size = int(
            os.environ.get("LEADGEN_AITRANSFORMERS_BATCH_SIZE", DEFAULT_BATCH_SIZE)
        )
    except ValueError:
        batch_size = DEFAULT_BATCH_SIZE
    if batch_size < 1:
        batch_size = DEFAULT_BATCH_SIZE

    return SyncConfig(
        api_url=os.environ.get("AITRANSFORMERS_API_URL", DEFAULT_API_URL),
        admin_token=token,
        tenant_slug=os.environ.get(
            "LEADGEN_AITRANSFORMERS_TENANT_SLUG", DEFAULT_TENANT_SLUG
        ),
        batch_size=batch_size,
        tag_name=os.environ.get("LEADGEN_AITRANSFORMERS_TAG_NAME", DEFAULT_TAG_NAME),
    )


# ---------------------------------------------------------------------------
# HTTP fetch (paginated, with retry)
# ---------------------------------------------------------------------------


def _http_get_with_retry(
    url: str,
    params: dict,
    headers: dict,
    timeout: int = _HTTP_TIMEOUT_SECONDS,
    backoffs: tuple = _HTTP_RETRY_BACKOFF_SECONDS,
) -> dict:
    """GET with bounded exponential retry on 5xx / network errors.

    4xx errors are surfaced immediately (config / token problems are not
    transient and a retry would just delay the failure).
    """
    last_exc: Optional[Exception] = None
    attempts = len(backoffs) + 1
    for attempt in range(attempts):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            last_exc = exc
            if attempt == attempts - 1:
                raise
            logger.warning(
                "AITransformers sync: network error on attempt %d/%d: %s",
                attempt + 1,
                attempts,
                exc,
            )
            time.sleep(backoffs[attempt])
            continue

        if 400 <= resp.status_code < 500:
            # Terminal — bad request, bad auth, etc. Log + raise immediately.
            body = resp.text[:300] if hasattr(resp, "text") else ""
            raise RuntimeError(
                f"AITransformers leads-export returned {resp.status_code}: {body}"
            )

        if resp.status_code >= 500:
            if attempt == attempts - 1:
                raise RuntimeError(
                    f"AITransformers leads-export returned {resp.status_code} "
                    f"after {attempts} attempts"
                )
            logger.warning(
                "AITransformers sync: HTTP %d on attempt %d/%d, retrying",
                resp.status_code,
                attempt + 1,
                attempts,
            )
            time.sleep(backoffs[attempt])
            continue

        try:
            return resp.json() or {}
        except ValueError as exc:
            raise RuntimeError(
                f"AITransformers leads-export returned non-JSON body: {exc}"
            ) from exc

    # Defensive — loop always either returns or raises above.
    raise RuntimeError(f"AITransformers leads-export exhausted retries: {last_exc}")


def _iter_pages(cfg: SyncConfig) -> Iterator[list[dict]]:
    """Yield ``items`` lists from each page of ``/admin/leads-export``."""
    offset = 0
    pages = 0
    while True:
        page = _http_get_with_retry(
            f"{cfg.api_url}/admin/leads-export",
            params={"limit": cfg.batch_size, "offset": offset},
            headers={"Authorization": f"Bearer {cfg.admin_token}"},
        )
        items = page.get("items") or []
        pages += 1
        yield items
        next_offset = page.get("next_offset")
        if next_offset is None:
            logger.info(
                "AITransformers sync: fetched %d page(s), last page had %d item(s)",
                pages,
                len(items),
            )
            return
        offset = int(next_offset)


# ---------------------------------------------------------------------------
# Advisory lock (Postgres) — no-op on SQLite for tests.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _advisory_lock(key: str):
    """Try to acquire a Postgres advisory lock for ``key``.

    Yields ``True`` if acquired (caller proceeds), ``False`` if another
    session already holds it (caller exits cleanly). On SQLite (tests)
    locking is a no-op and always yields ``True``.

    The lock is automatically released on context exit (via
    ``pg_advisory_unlock``).
    """
    engine = db.session.get_bind()
    dialect = engine.dialect.name if engine is not None else "sqlite"
    if dialect != "postgresql":
        yield True
        return

    acquired = False
    try:
        result = db.session.execute(
            sql_text("SELECT pg_try_advisory_lock(hashtext(:key))"),
            {"key": key},
        ).scalar()
        acquired = bool(result)
        yield acquired
    finally:
        if acquired:
            try:
                db.session.execute(
                    sql_text("SELECT pg_advisory_unlock(hashtext(:key))"),
                    {"key": key},
                )
                db.session.commit()
            except Exception:
                # Best-effort release; the lock is per-session and will
                # drop when the connection returns to the pool.
                db.session.rollback()
                logger.warning(
                    "AITransformers sync: advisory unlock failed for %s", key
                )


# ---------------------------------------------------------------------------
# Row processing helpers
# ---------------------------------------------------------------------------


def _split_name(raw: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Split a single name string into ``(first, last)``.

    AITransformers emits either a single ``name`` (typically
    ``"First Last"``) or a ``display_name`` we can fall back to. Anything
    after the first whitespace lands in ``last_name`` so multi-part
    surnames stay together.
    """
    if not raw:
        return None, None
    parts = raw.strip().split(None, 1)
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]


def _fill_if_empty(contact: Contact, attr: str, value) -> None:
    """Strictly-additive set: only writes when the current value is empty.

    Treats ``None`` and the empty string as empty. Leaves non-empty
    values untouched so manual dashboard edits are preserved across
    every resync.
    """
    if value is None or value == "":
        return
    current = getattr(contact, attr, None)
    if current is None or current == "":
        setattr(contact, attr, value)


def _merge_aitransformers_metadata(contact: Contact, payload: dict) -> None:
    """Merge AITransformers-specific metadata under
    ``custom_fields["aitransformers"]``.

    Inner keys are filled-if-empty so manual edits to e.g. an industry
    classification persist. ``synced_at`` is always refreshed to the
    current run timestamp because it's an observability marker.
    """
    # ``custom_fields`` is a JSONB column with a server default of '{}'.
    # When a brand-new contact has just been added to the session and
    # not flushed, the attribute may be ``None``; defend against both.
    existing_raw = getattr(contact, "custom_fields", None) or {}
    if isinstance(existing_raw, str):
        # SQLite test backend serializes JSONB to TEXT — round-trip.
        try:
            existing_raw = json.loads(existing_raw)
        except (ValueError, TypeError):
            existing_raw = {}

    existing = deepcopy(existing_raw) if isinstance(existing_raw, dict) else {}
    bucket = existing.get(_AITRANSFORMERS_NS)
    if not isinstance(bucket, dict):
        bucket = {}

    for key in (
        "iam_id",
        "company",
        "industry",
        "company_size",
        "maturity_level",
        "tier",
        "is_founding_member",
        "aitransformers_newsletter_subscribed",
    ):
        new_val = payload.get(key)
        if new_val is None or new_val == "":
            continue
        current = bucket.get(key)
        if current is None or current == "":
            bucket[key] = new_val

    bucket["synced_at"] = _utcnow_iso()

    existing[_AITRANSFORMERS_NS] = bucket
    contact.custom_fields = existing
    # SQLAlchemy doesn't detect in-place mutation of JSON-typed columns
    # reliably across dialects — mark dirty explicitly.
    flag_modified(contact, "custom_fields")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_existing_contact(
    tenant_id: str, iam_id: str, email: str
) -> Optional[Contact]:
    """Prefer match by stable ``iam_id`` in ``custom_fields``, then by email.

    The JSONB lookup uses raw SQL because SQLAlchemy ORM cannot express
    a portable jsonb path query that also works on the SQLite TEXT
    fallback used in tests. The raw SQL strategy is:

    - Postgres: ``custom_fields -> 'aitransformers' ->> 'iam_id' = :iam_id``
    - SQLite/TEXT: ``custom_fields LIKE '%"iam_id": "..."%' `` — coarse
      but sufficient (test rows have unique tokens, no collisions).
    """
    engine = db.session.get_bind()
    dialect = engine.dialect.name if engine is not None else "sqlite"

    if dialect == "postgresql":
        row = db.session.execute(
            sql_text(
                """
                SELECT id FROM contacts
                WHERE tenant_id = :tenant_id
                  AND custom_fields -> 'aitransformers' ->> 'iam_id' = :iam_id
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "iam_id": iam_id},
        ).first()
        if row:
            return db.session.get(Contact, row[0])
    else:
        # SQLite test path — string-contains match. Quote the iam_id so
        # partial substring collisions are impossible for the JSON shape
        # our writer produces.
        token = f'"iam_id": "{iam_id}"'
        contact = Contact.query.filter(
            Contact.tenant_id == tenant_id,
            Contact.custom_fields.like(f"%{token}%"),
        ).first()
        if contact:
            return contact

    # Fallback: email match within the tenant. Lower-cased for stable
    # comparison — we always insert lower-case below.
    return Contact.query.filter(
        Contact.tenant_id == tenant_id,
        db.func.lower(Contact.email_address) == email.lower(),
    ).first()


def _assign_tag(tenant_id: str, contact_id: str, tag_id: str) -> bool:
    """Idempotently INSERT a (contact_id, tag_id) assignment.

    Returns ``True`` when a new row was created, ``False`` when the pair
    already existed. Uses raw SQL + ``ON CONFLICT DO NOTHING`` (the same
    pattern the bulk-tag route uses) so the call is atomic and survives
    concurrent runs.
    """
    engine = db.session.get_bind()
    dialect = engine.dialect.name if engine is not None else "sqlite"

    # Check existence first (portable across dialects) so we can report
    # tagged_new vs tagged_existing accurately. The INSERT itself is the
    # source of truth for idempotency.
    existing = ContactTagAssignment.query.filter_by(
        contact_id=contact_id, tag_id=tag_id
    ).first()
    if existing is not None:
        return False

    if dialect == "postgresql":
        db.session.execute(
            sql_text(
                """
                INSERT INTO contact_tag_assignments
                    (id, tenant_id, contact_id, tag_id)
                VALUES
                    (gen_random_uuid(), :tenant_id, :contact_id, :tag_id)
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "tenant_id": tenant_id,
                "contact_id": contact_id,
                "tag_id": tag_id,
            },
        )
    else:
        # SQLite test path — no ON CONFLICT, but we already checked
        # existence above, so a plain ORM insert is safe.
        db.session.add(
            ContactTagAssignment(
                tenant_id=tenant_id,
                contact_id=contact_id,
                tag_id=tag_id,
            )
        )
    return True


def _find_or_create_tag(tenant_id: str, name: str) -> Tag:
    """Look up the campaign tag by ``(tenant_id, name)`` or create it."""
    tag = Tag.query.filter_by(tenant_id=tenant_id, name=name).first()
    if tag is not None:
        return tag
    tag = Tag(tenant_id=tenant_id, name=name, is_active=True)
    db.session.add(tag)
    db.session.commit()
    return tag


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def process_row(
    tenant_id: str,
    tag_id: str,
    row: dict,
    totals: dict,
) -> None:
    """Apply a single AITransformers user row to leadgen.

    Mutates ``totals`` in place. Per-row commits ensure a single bad row
    does not poison the whole batch.

    Counter semantics
    -----------------
    - ``created``: a brand-new ``contacts`` row was inserted.
    - ``updated``: an existing contact had at least one blank field filled
      in (or always — we count any existing-contact write).
    - ``tagged_new``: a new ``contact_tag_assignments`` row was created.
    - ``tagged_existing``: the contact already had the AITransformers tag.
    - ``skipped``: row lacked the minimum identity (email + iam_id).
    """
    email = (row.get("email") or "").strip().lower()
    iam_id = (row.get("iam_id") or "").strip()

    if not email or not iam_id:
        totals["skipped"] += 1
        return

    contact = _find_existing_contact(tenant_id, iam_id, email)
    is_new = False
    if contact is None:
        first, last = _split_name(row.get("name") or row.get("display_name"))
        if not first:
            # ``first_name`` is NOT NULL on Contact; fall back to the
            # email local part so the insert succeeds without producing
            # garbage names.
            first = email.split("@", 1)[0]
        contact = Contact(
            tenant_id=tenant_id,
            email_address=email,
            first_name=first,
            last_name=last or "",
            import_source="aitransformers",
            contact_source="aitransformers",
        )
        db.session.add(contact)
        db.session.flush()  # populate contact.id
        totals["created"] += 1
        is_new = True
    else:
        # Adopt source markers if the legacy contact has none. Never
        # overwrite an existing import_source — the original ingest path
        # owns that field.
        _fill_if_empty(contact, "import_source", "aitransformers")
        _fill_if_empty(contact, "contact_source", "aitransformers")
        first, last = _split_name(row.get("name") or row.get("display_name"))
        _fill_if_empty(contact, "first_name", first)
        if last:
            _fill_if_empty(contact, "last_name", last)
        totals["updated"] += 1

    # Common field merges (run on both new and existing rows for symmetry).
    _fill_if_empty(contact, "job_title", row.get("role"))
    # Persist iam_id + auxiliary AITransformers metadata.
    _merge_aitransformers_metadata(
        contact,
        {
            "iam_id": iam_id,
            "company": row.get("company"),
            "industry": row.get("industry"),
            "company_size": row.get("company_size"),
            "maturity_level": row.get("maturity_level"),
            "tier": row.get("tier"),
            "is_founding_member": row.get("is_founding_member"),
            # Upstream key is ``newsletter_subscribed``; we deliberately
            # store it under a platform-prefixed name so it's clearly the
            # AITransformers email_subscriptions flag (current local
            # state, NOT the IAM newsletter scope of record).
            "aitransformers_newsletter_subscribed": row.get("newsletter_subscribed"),
        },
    )

    db.session.flush()

    if _assign_tag(tenant_id, contact.id, tag_id):
        totals["tagged_new"] += 1
    else:
        totals["tagged_existing"] += 1

    db.session.commit()
    # The "is_new" flag is unused after the counter bump above, but
    # captured so future log lines can distinguish first-time creations
    # from updates without re-querying.
    _ = is_new


def sync_aitransformers_users(cfg: Optional[SyncConfig] = None) -> dict:
    """Run the full AITransformers → leadgen sync once.

    Returns a totals dict that's also emitted as a single structured log
    line at end of run:

    ``{created, updated, tagged_new, tagged_existing, skipped, errors,
       pages_fetched, duration_ms, lock_acquired}``.

    Caller responsibilities
    -----------------------
    - The function expects an active Flask app context (so ``db.session``
      is bound). Both the cron entrypoint and the CLI provide one.
    - Raises ``RuntimeError`` when fatal config / tenant / token issues
      prevent any work. Per-row exceptions are caught and counted in
      ``errors`` — the run continues.
    """
    cfg = cfg or load_config()
    start_ts = time.time()

    tenant = Tenant.query.filter_by(slug=cfg.tenant_slug).first()
    if tenant is None:
        raise RuntimeError(
            f"AITransformers sync: tenant slug '{cfg.tenant_slug}' not found"
        )

    totals = {
        "created": 0,
        "updated": 0,
        "tagged_new": 0,
        "tagged_existing": 0,
        "skipped": 0,
        "errors": 0,
        "pages_fetched": 0,
        "duration_ms": 0,
        "lock_acquired": True,
    }

    lock_key = f"{_LOCK_NS}:{tenant.id}"
    with _advisory_lock(lock_key) as acquired:
        if not acquired:
            totals["lock_acquired"] = False
            logger.info(
                "AITransformers sync: skipped — another run holds the advisory "
                "lock for tenant %s",
                tenant.slug,
            )
            return totals

        tag = _find_or_create_tag(tenant.id, cfg.tag_name)

        try:
            for items in _iter_pages(cfg):
                totals["pages_fetched"] += 1
                for row in items:
                    iam_id = row.get("iam_id") if isinstance(row, dict) else None
                    try:
                        process_row(tenant.id, tag.id, row, totals)
                    except Exception as exc:
                        # Roll back the failed row so the session is clean
                        # for the next one. Counter still bumps so the run
                        # summary reflects the issue.
                        db.session.rollback()
                        totals["errors"] += 1
                        logger.exception(
                            "AITransformers sync: row failed (iam_id=%s): %s",
                            iam_id,
                            exc,
                        )
        finally:
            totals["duration_ms"] = int((time.time() - start_ts) * 1000)
            logger.info("AITransformers sync complete: %s", totals)

    return totals
