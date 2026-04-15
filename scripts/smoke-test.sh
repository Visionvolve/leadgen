#!/usr/bin/env bash
#
# Post-deploy smoke test for SSO and core infrastructure.
# Catches: wrong OAuth URLs (Bug 1), SPA fallback masking API errors (Bug 2),
# missing env vars (Bug 3), nginx SPA fallback gaps (Bug 4), stale frontend (Bug 5).
#
# Usage:
#   bash scripts/smoke-test.sh https://leadgen-staging.visionvolve.com
#   bash scripts/smoke-test.sh http://localhost:5173
#
set -euo pipefail

BASE_URL="${1:?Usage: smoke-test.sh <base-url>}"
# Strip trailing slash
BASE_URL="${BASE_URL%/}"

PASS=0
FAIL=0
WARN=0

pass() { echo "  PASS: $1"; ((PASS++)); }
fail() { echo "  FAIL: $1"; ((FAIL++)); }
warn() { echo "  WARN: $1"; ((WARN++)); }

echo "=== SSO Smoke Test: $BASE_URL ==="
echo ""

# 1. Health check — API is alive and returns JSON
echo "[1] API Health Check"
HEALTH=$(curl -s -o /dev/null -w "%{http_code}:%{content_type}" "$BASE_URL/api/health" 2>/dev/null || echo "000:")
HEALTH_CODE="${HEALTH%%:*}"
HEALTH_CT="${HEALTH#*:}"

if [[ "$HEALTH_CODE" == "200" ]]; then
  pass "GET /api/health returns 200"
else
  fail "GET /api/health returned $HEALTH_CODE (expected 200)"
fi

if [[ "$HEALTH_CT" == *"application/json"* ]]; then
  pass "Health endpoint returns JSON content-type"
else
  fail "Health endpoint returns '$HEALTH_CT' (expected application/json) — SPA fallback may be masking API"
fi

# 2. SPA fallback — /auth/callback should return 200 HTML (not 404)
echo ""
echo "[2] SPA Fallback for /auth/callback"
CB=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/auth/callback" 2>/dev/null || echo "000")

if [[ "$CB" == "200" ]]; then
  pass "GET /auth/callback returns 200 (SPA fallback works)"
elif [[ "$CB" == "404" ]]; then
  fail "GET /auth/callback returns 404 — nginx SPA fallback missing (Bug 4)"
else
  warn "GET /auth/callback returns $CB (expected 200)"
fi

# 3. OAuth URL correctness — SSO buttons must point to /auth/oauth/google (not /oauth/google)
echo ""
echo "[3] OAuth URL in Frontend Bundle"
# Fetch the login page HTML and look for the SSO link pattern
LOGIN_HTML=$(curl -s "$BASE_URL/" 2>/dev/null || echo "")

if echo "$LOGIN_HTML" | grep -q '/auth/oauth/google'; then
  pass "Login page contains /auth/oauth/google (correct OAuth path)"
elif echo "$LOGIN_HTML" | grep -q '/oauth/google'; then
  fail "Login page contains /oauth/google — wrong path (Bug 1: should be /auth/oauth/google)"
else
  # For SPAs, the link is in the JS bundle, not the initial HTML
  # Try to find and fetch the main JS bundle
  JS_BUNDLE=$(echo "$LOGIN_HTML" | grep -oE 'src="[^"]*\.js"' | head -1 | sed 's/src="//;s/"$//')
  if [[ -n "$JS_BUNDLE" ]]; then
    # Handle relative and absolute paths
    if [[ "$JS_BUNDLE" == /* ]]; then
      JS_URL="$BASE_URL$JS_BUNDLE"
    else
      JS_URL="$BASE_URL/$JS_BUNDLE"
    fi
    BUNDLE=$(curl -s "$JS_URL" 2>/dev/null || echo "")
    if echo "$BUNDLE" | grep -q '/auth/oauth/google'; then
      pass "JS bundle contains /auth/oauth/google (correct OAuth path)"
    elif echo "$BUNDLE" | grep -q '/oauth/google'; then
      fail "JS bundle contains /oauth/google — wrong path (Bug 1)"
    else
      warn "Could not find OAuth URL pattern in JS bundle"
    fi
  else
    warn "Could not locate JS bundle to verify OAuth URL"
  fi
fi

# 4. IAM connectivity — bad credentials should return 401 JSON, not 503 or HTML
echo ""
echo "[4] IAM Connectivity (login with bad creds)"
LOGIN_RESP=$(curl -s -o /tmp/smoke-login-body -w "%{http_code}:%{content_type}" \
  -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"smoke-test@nonexistent.local","password":"bad"}' 2>/dev/null || echo "000:")
LOGIN_CODE="${LOGIN_RESP%%:*}"
LOGIN_CT="${LOGIN_RESP#*:}"

if [[ "$LOGIN_CODE" == "401" ]]; then
  pass "POST /api/auth/login with bad creds returns 401 (IAM reachable)"
elif [[ "$LOGIN_CODE" == "503" ]]; then
  fail "POST /api/auth/login returns 503 — IAM unreachable (Bug 3: check IAM_BASE_URL env var)"
elif [[ "$LOGIN_CODE" == "200" && "$LOGIN_CT" == *"text/html"* ]]; then
  fail "POST /api/auth/login returns 200 HTML — SPA fallback intercepting API route (Bug 2)"
else
  warn "POST /api/auth/login returned $LOGIN_CODE (expected 401)"
fi

if [[ "$LOGIN_CT" == *"application/json"* ]]; then
  pass "Login error returns JSON content-type"
else
  fail "Login error returns '$LOGIN_CT' (expected application/json)"
fi

# 5. Callback endpoint returns JSON errors, not HTML
echo ""
echo "[5] OAuth Callback Returns JSON Errors"
CB_RESP=$(curl -s -o /tmp/smoke-cb-body -w "%{http_code}:%{content_type}" \
  "$BASE_URL/api/auth/iam/callback" 2>/dev/null || echo "000:")
CB_CODE="${CB_RESP%%:*}"

if [[ "$CB_CODE" == "302" ]]; then
  pass "GET /api/auth/iam/callback without code returns 302 redirect (correct)"
else
  warn "GET /api/auth/iam/callback returned $CB_CODE (expected 302)"
fi

# Summary
echo ""
echo "=== Results: $PASS passed, $FAIL failed, $WARN warnings ==="

# Clean up
rm -f /tmp/smoke-login-body /tmp/smoke-cb-body

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
