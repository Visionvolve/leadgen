#!/usr/bin/env bash
# DEPRECATED: Production deploys via GitHub Actions (merge to main).
# This script is for emergency manual deploys only.
#
# Deploy the dashboard to VPS (React SPA only + standalone roadmap.html)
# Usage: bash deploy/deploy-dashboard.sh

set -euo pipefail

VPS_KEY="/Users/michal/git/visionvolve-vps/vps-deploy-key"
VPS_HOST="ec2-user@52.58.119.191"
VPS_DIR="/home/ec2-user/n8n-docker-caddy"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FRONTEND_DIR="${PROJECT_DIR}/frontend"

echo "==> Building React frontend..."
cd "$FRONTEND_DIR"
npm run build
echo "    Build complete"

echo "==> Deploying dashboard to VPS..."

# 1. Create dashboard + assets directories on VPS
ssh -i "$VPS_KEY" "$VPS_HOST" "mkdir -p ${VPS_DIR}/dashboard/assets"

# 2. Deploy React SPA build output (index.html + assets/)
scp -i "$VPS_KEY" "${FRONTEND_DIR}/dist/index.html" "${VPS_HOST}:${VPS_DIR}/dashboard/"
scp -i "$VPS_KEY" ${FRONTEND_DIR}/dist/assets/* "${VPS_HOST}:${VPS_DIR}/dashboard/assets/"
# SVGs may not exist if Vite inlines them — only copy if present
if compgen -G "${FRONTEND_DIR}/dist/*.svg" > /dev/null 2>&1; then
  scp -i "$VPS_KEY" ${FRONTEND_DIR}/dist/*.svg "${VPS_HOST}:${VPS_DIR}/dashboard/"
fi
echo "    Copied React SPA build"

# 3. Deploy standalone pages (not part of the React SPA)
scp -i "$VPS_KEY" "${PROJECT_DIR}/dashboard/roadmap.html" "${VPS_HOST}:${VPS_DIR}/dashboard/"
echo "    Copied roadmap.html"

# 4. Clean up stale vanilla files from previous deploys
ssh -i "$VPS_KEY" "$VPS_HOST" bash <<'REMOTE'
cd /home/ec2-user/n8n-docker-caddy/dashboard
for stale in contacts.html companies.html messages.html enrich.html \
             import.html admin.html llm-costs.html echo.html playbook.html \
             pipeline-archive.html auth.js nav.js nav.css; do
  if [ -f "$stale" ]; then
    rm "$stale"
    echo "    Removed stale $stale"
  fi
done
REMOTE

# 5. Add dashboard volume to Caddy if not already present
ssh -i "$VPS_KEY" "$VPS_HOST" bash <<'REMOTE'
cd /home/ec2-user/n8n-docker-caddy

if [ ! -f docker-compose.dashboard.yml ]; then
  cat > docker-compose.dashboard.yml <<'EOF'
# Additive compose file — add dashboard volume to Caddy
# Usage: docker compose -f docker-compose.yml -f docker-compose.mcp.yml -f docker-compose.dashboard.yml up -d
services:
  caddy:
    volumes:
      - ./dashboard:/srv/dashboard:ro
EOF
  echo "    Created docker-compose.dashboard.yml"
fi

# Restart with all compose files
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.mcp.yml -f docker-compose.airtable-mcp.yml -f docker-compose.dashboard.yml -f docker-compose.api.yml -f docker-compose.ds.yml"
docker compose $COMPOSE_FILES up -d caddy
echo "    Caddy restarted"
REMOTE

# 6. Post-deploy health checks (verify API is still healthy after Caddy restart)
HEALTH_URL="https://leadgen.visionvolve.com/api/health"
LIVENESS_URL="https://leadgen.visionvolve.com/api/health/liveness"

echo "==> Waiting for API liveness after Caddy restart..."
LIVE=0
for i in 1 2 3 4 5 6; do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$LIVENESS_URL" || true)
  if [ "$HTTP_CODE" = "200" ]; then
    LIVE=1
    echo "    Liveness OK (attempt $i)"
    break
  fi
  echo "    Liveness not ready (HTTP $HTTP_CODE), retrying in 5s... (attempt $i/6)"
  sleep 5
done

if [ "$LIVE" -ne 1 ]; then
  echo "DEPLOY WARNING: API liveness check failed after Caddy restart"
  echo "    Dashboard is deployed but API may be down"
  exit 1
fi

echo "==> Checking API readiness (DB connectivity)..."
READY=0
for i in 1 2 3; do
  BODY=$(curl -s "$HEALTH_URL" || true)
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" || true)
  echo "    Attempt $i/3: HTTP $HTTP_CODE — $BODY"
  if [ "$HTTP_CODE" = "200" ]; then
    READY=1
    break
  fi
  if [ "$i" -lt 3 ]; then
    echo "    Retrying in 5s..."
    sleep 5
  fi
done

if [ "$READY" -ne 1 ]; then
  echo ""
  echo "========================================="
  echo "DEPLOY FAILED: API is up but cannot reach database"
  echo "Last health response: $BODY"
  echo "========================================="
  exit 1
fi

echo "==> Dashboard deployed to https://leadgen.visionvolve.com/"
echo "    React SPA handles all pages"
echo "    Standalone: roadmap.html"
