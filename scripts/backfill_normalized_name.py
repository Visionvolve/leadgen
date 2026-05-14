#!/usr/bin/env python3
"""Backfill companies.normalized_name for BL-1203 / Phase 12.

Idempotent: only updates rows whose stored ``normalized_name`` differs
from ``normalize_company_name(name)``. Batched by row reads (read all,
write in chunks of 500) to keep individual transactions short. Safe to
re-run after a partial failure — the second run reports ``updated=0``.

Usage:
    LEADGEN_DATABASE_URL=postgres://… python3 scripts/backfill_normalized_name.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the api package importable when running standalone
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402

from api.services.name_normalize import normalize_company_name  # noqa: E402

BATCH = 500


def main() -> int:
    url = os.environ.get("LEADGEN_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print(
            "ERROR: LEADGEN_DATABASE_URL (or DATABASE_URL) not set",
            file=sys.stderr,
        )
        return 1
    eng = create_engine(url, pool_pre_ping=True)
    with eng.begin() as conn:
        rows = conn.execute(
            text("SELECT id, name, normalized_name FROM companies ORDER BY id")
        ).fetchall()
    seen = len(rows)
    print(f"Read {seen} companies; computing diffs...")

    pending = []
    for r in rows:
        desired = normalize_company_name(r[1])
        if (r[2] or "") != desired:
            pending.append({"id": r[0], "nn": desired})

    if not pending:
        print(f"Done. seen={seen} updated=0")
        return 0

    updated = 0
    for i in range(0, len(pending), BATCH):
        chunk = pending[i : i + BATCH]
        with eng.begin() as conn:
            for row in chunk:
                conn.execute(
                    text("UPDATE companies SET normalized_name = :nn WHERE id = :id"),
                    row,
                )
        updated += len(chunk)
        print(f"  batch {i // BATCH + 1}: updated {len(chunk)} rows")

    print(f"Done. seen={seen} updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
