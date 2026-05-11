#!/usr/bin/env python
"""Phase 4 preflight — exits 0 if all green, non-zero with a diagnostic summary.

Checks, in order:
  1. Env vars present (required set listed below)
  2. Shared API key matches between UA and leadgen (UA /api/invites rejects 401 if mismatch)
  3. Leadgen ingest reachable (POST to /api/tracking/microsite-event with sentinel)
  4. Resend API key live (GET /domains returns 200)
  5. Resend domain `loserscirque.cz` verified (or sandbox mode explicitly enabled)
  6. UA microsite reachable (HEAD/GET returns 2xx/3xx + SSL handshake OK)
  7. Leadgen migration 060 applied (idx_activities_microsite_dedup exists)

Stdlib only — urllib, argparse, os, sys, subprocess, json. No new pip deps.

Exit codes:
  0  = all green
  1  = env vars missing
  2  = shared API key mismatch (UA returned 401)
  3  = leadgen ingest unreachable
  4  = Resend API key dead (401)
  5  = Resend domain not verified AND sandbox mode not enabled
  6  = UA microsite unreachable
  7  = migration 060 missing
  8  = unexpected failure
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

REQUIRED_ENV = [
    "DATABASE_URL",
    "UA_MICROSITE_URL",
    "UA_INVITE_API_KEY",
    "UA_MAILING_FROM_EMAIL",
    "UA_MAILING_REPLY_TO",
    "RESEND_API_KEY",
]

RESEND_DOMAIN = "loserscirque.cz"


def _get(url: str, headers: dict[str, str] | None = None, timeout: int = 5) -> tuple[int, bytes]:
    req = urllib.request.Request(url, method="GET", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if hasattr(e, "read") else b""


def _post(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: int = 5,
) -> tuple[int, bytes]:
    data = json.dumps(body).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, method="POST", headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if hasattr(e, "read") else b""


def check_env() -> tuple[bool, str]:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        return False, f"missing env vars: {', '.join(missing)}"
    return True, "env vars present"


def check_shared_key() -> tuple[bool, str, int]:
    """Hit UA /api/invites with the shared key. 200/400 = key matches. 401 = mismatch."""
    url = os.environ["UA_MICROSITE_URL"].rstrip("/") + "/api/invites"
    api_key = os.environ["UA_INVITE_API_KEY"]
    t0 = time.time()
    try:
        status, _ = _get(url, headers={"x-api-key": api_key}, timeout=8)
    except Exception as e:  # noqa: BLE001
        return False, f"UA unreachable at {url}: {e}", 0
    ms = int((time.time() - t0) * 1000)
    if status == 401:
        return False, f"UA rejects shared key — Phase 3 D-01 mismatch (HTTP 401 from {url})", ms
    # 200 (listing) and 400 (malformed GET) both mean the key was accepted.
    if status in (200, 400):
        return True, f"shared API key accepted by UA (HTTP {status}, {ms}ms)", ms
    # 404 or 405 could mean route doesn't exist — treat as key-agnostic failure.
    return False, f"UA returned unexpected HTTP {status} — cannot confirm key", ms


def check_leadgen_ingest() -> tuple[bool, str, int]:
    """POST a sentinel to leadgen /api/tracking/microsite-event."""
    ingest_base = os.environ.get("LEADGEN_INGEST_URL") or os.environ.get(
        "LEADGEN_SITE_EVENTS_URL", "http://localhost:5000"
    )
    url = ingest_base.rstrip("/") + "/api/tracking/microsite-event"
    api_key = os.environ["UA_INVITE_API_KEY"]
    now = datetime.now(timezone.utc).isoformat()
    body = {
        "token": "PHASE4-PREFLIGHT",
        "event": "page_viewed",
        "data": {"path": "/preflight"},
        "timestamp": now,
    }
    t0 = time.time()
    try:
        status, resp = _post(url, body, headers={"X-API-Key": api_key}, timeout=8)
    except Exception as e:  # noqa: BLE001
        return False, f"leadgen ingest unreachable at {url}: {e}", 0
    ms = int((time.time() - t0) * 1000)
    if 200 <= status < 300:
        return True, f"leadgen ingest reachable at {url} (HTTP {status}, {ms}ms)", ms
    return (
        False,
        f"leadgen ingest returned HTTP {status} from {url}: {resp[:200]!r}",
        ms,
    )


def check_resend_key() -> tuple[bool, str]:
    """Hit Resend /domains with bearer token."""
    key = os.environ["RESEND_API_KEY"]
    status, body = _get(
        "https://api.resend.com/domains",
        headers={"Authorization": f"Bearer {key}"},
        timeout=8,
    )
    if status == 200:
        return True, "Resend API key live"
    if status == 401:
        return False, "Resend API key dead — rotate in 1Password"
    return False, f"Resend /domains returned HTTP {status}: {body[:200]!r}"


def check_resend_domain() -> tuple[bool, str]:
    """Confirm loserscirque.cz status is verified (or sandbox mode set)."""
    key = os.environ["RESEND_API_KEY"]
    sandbox = os.environ.get("RESEND_SANDBOX_MODE", "").lower() == "true"
    status, body = _get(
        "https://api.resend.com/domains",
        headers={"Authorization": f"Bearer {key}"},
        timeout=8,
    )
    if status != 200:
        return False, f"cannot fetch domains (HTTP {status})"
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False, "Resend /domains returned non-JSON"
    domains = payload.get("data", []) if isinstance(payload, dict) else []
    match = next((d for d in domains if d.get("name") == RESEND_DOMAIN), None)
    if match is None:
        if sandbox:
            return (
                True,
                f"domain {RESEND_DOMAIN} not registered in Resend — sandbox-mode fallback active",
            )
        return False, (
            f"domain {RESEND_DOMAIN} not registered in Resend; "
            "set RESEND_SANDBOX_MODE=true to fall back to onboarding@resend.dev"
        )
    status_val = (match.get("status") or "").lower()
    if status_val == "verified":
        return True, f"domain {RESEND_DOMAIN} status=verified"
    if sandbox:
        return (
            True,
            f"domain {RESEND_DOMAIN} status={status_val} — sandbox-mode fallback active",
        )
    return False, (
        f"domain {RESEND_DOMAIN} status={status_val} (not verified); "
        "set RESEND_SANDBOX_MODE=true to proceed via onboarding@resend.dev"
    )


def check_ua_reachable() -> tuple[bool, str]:
    """HEAD/GET the UA microsite root; any 2xx/3xx = SSL + container OK."""
    url = os.environ["UA_MICROSITE_URL"].rstrip("/") + "/"
    try:
        status, _ = _get(url, timeout=8)
    except Exception as e:  # noqa: BLE001
        return False, f"UA microsite unreachable at {url}: {e}"
    if 200 <= status < 400:
        return True, f"UA microsite reachable at {url} (HTTP {status})"
    return False, f"UA microsite returned HTTP {status} at {url}"


def check_migration_060() -> tuple[bool, str]:
    """SELECT 1 FROM pg_indexes WHERE indexname='idx_activities_microsite_dedup'."""
    db_url = os.environ["DATABASE_URL"]
    sql = (
        "SELECT 1 FROM pg_indexes "
        "WHERE indexname='idx_activities_microsite_dedup' LIMIT 1;"
    )
    try:
        result = subprocess.run(
            ["psql", db_url, "-tAc", sql],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        return False, "psql not found in PATH — cannot verify migration 060"
    except subprocess.TimeoutExpired:
        return False, "psql timed out verifying migration 060"
    if result.returncode != 0:
        return False, f"psql failed: {result.stderr.strip()[:200]}"
    out = result.stdout.strip()
    if out == "1":
        return True, "migration 060 applied (idx_activities_microsite_dedup present)"
    return False, "Phase 3 Task B migration 060 not applied on this DB"


def main() -> int:
    checks = []
    print("PREFLIGHT — PHASE 4")

    # 1 — env vars
    ok, msg = check_env()
    checks.append(("env vars present", ok, msg))
    _log(1, ok, msg)
    if not ok:
        _summary(checks)
        return 1

    # 2 — shared API key
    ok, msg, _ms = check_shared_key()
    checks.append(("shared API key matches UA", ok, msg))
    _log(2, ok, msg)
    if not ok:
        _summary(checks)
        return 2

    # 3 — leadgen ingest reachable
    ok, msg, _ms = check_leadgen_ingest()
    checks.append(("leadgen ingest reachable", ok, msg))
    _log(3, ok, msg)
    if not ok:
        _summary(checks)
        return 3

    # 4 — Resend key
    ok, msg = check_resend_key()
    checks.append(("Resend API key live", ok, msg))
    _log(4, ok, msg)
    if not ok:
        _summary(checks)
        return 4

    # 5 — Resend domain
    ok, msg = check_resend_domain()
    checks.append(("Resend domain loserscirque.cz", ok, msg))
    _log(5, ok, msg)
    if not ok:
        _summary(checks)
        return 5

    # 6 — UA reachable
    ok, msg = check_ua_reachable()
    checks.append(("UA microsite reachable", ok, msg))
    _log(6, ok, msg)
    if not ok:
        _summary(checks)
        return 6

    # 7 — migration 060
    ok, msg = check_migration_060()
    checks.append(("migration 060 applied", ok, msg))
    _log(7, ok, msg)
    if not ok:
        _summary(checks)
        return 7

    print()
    print("PREFLIGHT — PHASE 4 (all green)")
    for name, _ok, msg in checks:
        print(f"  OK {name}: {msg}")
    print()
    print("Ready to run: bash scripts/run_phase4_test_send.sh")
    return 0


def _log(n: int, ok: bool, msg: str) -> None:
    marker = "OK" if ok else "FAIL"
    print(f"  [{n}] {marker} {msg}")


def _summary(checks: list[tuple[str, bool, str]]) -> None:
    print()
    print("PREFLIGHT — PHASE 4 (aborted)")
    for name, ok, msg in checks:
        marker = "OK" if ok else "FAIL"
        print(f"  {marker} {name}: {msg}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        print(f"UNEXPECTED ERROR: {exc}", file=sys.stderr)
        sys.exit(8)
