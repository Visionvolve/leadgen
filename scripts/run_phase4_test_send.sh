#!/usr/bin/env bash
# Phase 4 — orchestrates the 10-recipient test send.
#
# Preconditions: scripts/preflight_phase4.py passes.
# Side effects (on success):
#   - Creates a TEST-PHASE4-<timestamp> campaign in leadgen
#   - Creates 10 Invites in UA (one per licko61+t01..t10@gmail.com)
#   - Actually sends 10 emails via Resend to those plus-addresses
#
# Usage:
#   export PHASE4_TENANT_UUID=<uuid>
#   export PHASE4_RECIPIENTS_FILE=/Users/michal/git/ua-microsite/.planning/phases/04-end-to-end-verification/fixtures/test-phase4-recipients.txt
#   bash scripts/run_phase4_test_send.sh
# Or pass the recipients file as arg 1.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---- Required inputs ----

RECIPIENTS_FILE="${1:-${PHASE4_RECIPIENTS_FILE:-}}"
if [[ -z "$RECIPIENTS_FILE" || ! -f "$RECIPIENTS_FILE" ]]; then
  echo "ERROR: recipients file not found." >&2
  echo "  Pass as arg 1 or set PHASE4_RECIPIENTS_FILE." >&2
  echo "  Expected: /Users/michal/git/ua-microsite/.planning/phases/04-end-to-end-verification/fixtures/test-phase4-recipients.txt" >&2
  exit 1
fi

TENANT_UUID="${PHASE4_TENANT_UUID:-}"
if [[ -z "$TENANT_UUID" ]]; then
  echo "ERROR: PHASE4_TENANT_UUID is unset." >&2
  echo "  Get it from the Phase 3 dry-run log or leadgen Tenants table." >&2
  exit 1
fi

# ---- Campaign naming (D-02: MUST start with TEST-PHASE4-) ----

TS="$(date -u +"%Y%m%dT%H%MZ")"
CAMPAIGN_NAME="TEST-PHASE4-${TS}"
if [[ "$CAMPAIGN_NAME" != TEST-PHASE4-* ]]; then
  echo "ERROR: campaign name prefix violated — bailing." >&2
  exit 1
fi

RECIPIENT_COUNT="$(grep -c '^[^#[:space:]]' "$RECIPIENTS_FILE" || true)"

echo "=== Phase 4 test send ==="
echo "Campaign name : $CAMPAIGN_NAME"
echo "Tenant        : $TENANT_UUID"
echo "Recipients    : $RECIPIENTS_FILE ($RECIPIENT_COUNT emails)"
echo "CWD           : $REPO_ROOT"
echo

# ---- Step 1: preflight ----

echo "--- Step 1: preflight ---"
# Use `python3` on systems without a `python` alias (macOS default since Catalina).
PYTHON_BIN="${PYTHON:-$(command -v python3 || command -v python)}"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: neither python3 nor python found on PATH." >&2
  exit 1
fi
if ! "$PYTHON_BIN" "$SCRIPT_DIR/preflight_phase4.py"; then
  echo "ABORT: preflight failed." >&2
  exit 1
fi
echo

# ---- Step 2: provision campaign ----

echo "--- Step 2: provision campaign ---"
cd "$REPO_ROOT"
PROVISION_OUTPUT=$("$PYTHON_BIN" "$SCRIPT_DIR/provision_eventfest_campaign.py" \
  --name "$CAMPAIGN_NAME" \
  --tenant "$TENANT_UUID" \
  --file "$RECIPIENTS_FILE")
echo "$PROVISION_OUTPUT"

# Parse campaign id out of "Campaign <uuid> created. Dashboard: ..."
CAMPAIGN_ID=$(echo "$PROVISION_OUTPUT" | grep -oE 'Campaign [a-f0-9-]+' | awk '{print $2}' | head -1)
if [[ -z "$CAMPAIGN_ID" ]]; then
  echo "ABORT: could not parse campaign_id from provisioner output." >&2
  exit 1
fi
echo "Campaign id   : $CAMPAIGN_ID"
echo "$CAMPAIGN_ID" > "/tmp/phase4-last-campaign-id"
echo "$CAMPAIGN_NAME" > "/tmp/phase4-last-campaign-name"
echo

# ---- Step 3: confirm before send ----

echo "--- Step 3: confirm before send ---"
read -r -p "About to send 10 REAL emails to licko61+t01..t10@gmail.com via Resend. Proceed? [y/N] " CONFIRM
if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
  echo "Aborted by operator. Campaign $CAMPAIGN_ID remains in draft state." >&2
  exit 0
fi
echo

# ---- Step 4: trigger send ----

echo "--- Step 4: trigger send ---"
# send_campaign_emails(campaign_id, tenant_id) — signature requires both args
# (verified against api/services/send_service.py:275 at commit 11f2eda).
"$PYTHON_BIN" - <<PYEOF
from api import create_app
from api.services.send_service import send_campaign_emails
app = create_app()
with app.app_context():
    result = send_campaign_emails("$CAMPAIGN_ID", "$TENANT_UUID")
    print(result)
PYEOF

echo
echo "=== Send complete ==="
echo "Next: follow .planning/phases/04-end-to-end-verification/04-PLAYBOOK.md"
echo "Walkthrough: open 6 of 10 in Gmail, click 3, unsubscribe 1, leave 4 unopened."
echo "Campaign id: $CAMPAIGN_ID (saved to /tmp/phase4-last-campaign-id)"
echo "Campaign name: $CAMPAIGN_NAME (saved to /tmp/phase4-last-campaign-name)"
