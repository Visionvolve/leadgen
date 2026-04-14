#!/usr/bin/env bash
# DEPRECATED: Production deploys via GitHub Actions (merge to main).
# This script is for emergency manual deploys only.
#
# Pulls the GHCR image and restarts the container — no local build.
# Usage: bash deploy/deploy-api.sh

set -euo pipefail

VPS_KEY="/Users/michal/git/visionvolve-vps/vps-deploy-key"
VPS_HOST="ec2-user@52.58.119.191"
VPS_DIR="/home/ec2-user/n8n-docker-caddy"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "==> Deploying leadgen API to VPS (GHCR image pull)..."

# 1. Copy compose overlay (uses image: directive, no build:)
scp -i "$VPS_KEY" "${PROJECT_DIR}/deploy/docker-compose.api.yml" "${VPS_HOST}:${VPS_DIR}/"
echo "    Copied docker-compose.api.yml"

# 2. Pull image and restart container (no local build)
ssh -i "$VPS_KEY" "$VPS_HOST" bash <<'REMOTE'
cd /home/ec2-user/n8n-docker-caddy
COMPOSE_FILES='-f docker-compose.yml -f docker-compose.mcp.yml -f docker-compose.airtable-mcp.yml -f docker-compose.dashboard.yml -f docker-compose.api.yml -f docker-compose.ds.yml'
docker compose $COMPOSE_FILES pull leadgen-api
docker compose $COMPOSE_FILES up -d --no-deps leadgen-api
docker system prune -f --filter 'until=1h'
echo "    leadgen-api container started (from GHCR image)"
REMOTE

# 3. Deploy Caddy snippet
echo "==> Deploying Caddy snippet..."
scp -i "$VPS_KEY" "${PROJECT_DIR}/deploy/prod.caddy" "${VPS_HOST}:/home/ec2-user/n8n-docker-caddy/caddy_config/conf.d/leadgen.caddy"
ssh -i "$VPS_KEY" "$VPS_HOST" "docker exec n8n-docker-caddy-caddy-1 caddy reload --config /etc/caddy/Caddyfile"

# 4. Post-deploy health checks
HEALTH_URL="https://leadgen.visionvolve.com/api/health"
LIVENESS_URL="https://leadgen.visionvolve.com/api/health/liveness"

echo "==> Waiting for container to start (liveness check)..."
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
  echo "DEPLOY FAILED: API container did not become live after 30s"
  exit 1
fi

echo "==> Checking readiness (DB connectivity)..."
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

echo "==> API deployed successfully to https://leadgen.visionvolve.com/api/health"
