#!/usr/bin/env bash
# Deploy API + frontend to STAGING (leadgen-api-rev-latest container)
# Usage: bash deploy/deploy-staging.sh
#
# Updates the "latest" API container and dashboard on the staging VPS.
# For revision-specific deploys, use deploy-revision.sh instead.

set -euo pipefail

STAGING_KEY="/Users/michal/Downloads/LightsailDefaultKey-eu-central-1 (1).pem"
STAGING_HOST="ec2-user@3.124.110.199"
STAGING_DIR="/home/ec2-user"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

BRANCH="$(git -C "$PROJECT_DIR" branch --show-current)"
COMMIT="$(git -C "$PROJECT_DIR" rev-parse --short=7 HEAD)"

echo "==> Deploying to staging (latest)..."
echo "    Branch: ${BRANCH}, Commit: ${COMMIT}"

# ---- 1. Build frontend ----
echo ""
echo "==> Building frontend..."
cd "${PROJECT_DIR}/frontend"
VITE_IAM_BASE_URL=https://iam-staging.visionvolve.com npm run build 2>&1 | tail -3
echo "    Frontend build complete"

# ---- 2. Copy API source ----
echo ""
echo "==> Copying API source to staging..."
API_REMOTE="${STAGING_DIR}/leadgen-api-rev-latest"

ssh -i "$STAGING_KEY" "$STAGING_HOST" "mkdir -p ${API_REMOTE}"
scp -i "$STAGING_KEY" "${PROJECT_DIR}/Dockerfile.api" "${STAGING_HOST}:${API_REMOTE}/"

tar -C "${PROJECT_DIR}" --exclude='__pycache__' --exclude='*.pyc' -cf - api/ | \
  ssh -i "$STAGING_KEY" "$STAGING_HOST" "tar -C ${API_REMOTE} -xf -"
echo "    API source copied"

# ---- 3. Copy frontend build ----
echo ""
echo "==> Copying frontend build to staging..."
ssh -i "$STAGING_KEY" "$STAGING_HOST" "sudo mkdir -p /srv/dashboard-rev-latest && sudo chown ec2-user:ec2-user /srv/dashboard-rev-latest"
rsync -az --delete -e "ssh -i \"$STAGING_KEY\"" "${PROJECT_DIR}/frontend/dist/" "${STAGING_HOST}:/srv/dashboard-rev-latest/"
echo "    Frontend copied to /srv/dashboard-rev-latest"

# ---- 4. Rebuild and restart API container ----
echo ""
echo "==> Rebuilding leadgen-api-rev-latest container..."

ssh -i "$STAGING_KEY" "$STAGING_HOST" bash <<'REMOTE'
cd /home/ec2-user

# Only use the base compose + latest overlay (not revision containers)
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.api-rev-latest.yml"

docker compose $COMPOSE_FILES up -d --no-deps --build leadgen-api-rev-latest
echo "    leadgen-api-rev-latest rebuilt and started"

# Reload Caddy (use all compose files to find the caddy service)
ALL_COMPOSE="-f docker-compose.yml"
for f in docker-compose.api-rev-*.yml; do
  [ -f "\$f" ] && ALL_COMPOSE="\$ALL_COMPOSE -f \$f"
done
docker compose \$ALL_COMPOSE exec -T caddy caddy reload --config /etc/caddy/Caddyfile 2>/dev/null || true
echo "    Caddy reloaded"
REMOTE

# ---- 5. Health check ----
echo ""
echo "==> Health check..."
sleep 2
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" https://leadgen-staging.visionvolve.com/api/health)
if [ "$HTTP_CODE" = "200" ]; then
  echo "    API healthy (200)"
else
  echo "    WARNING: API returned $HTTP_CODE"
fi

echo ""
echo "==========================================="
echo "  Staging (latest) deployed — ${COMMIT}"
echo "==========================================="
echo ""
echo "  API:       https://leadgen-staging.visionvolve.com/api/health"
echo "  Dashboard: https://leadgen-staging.visionvolve.com/visionvolve/"
echo ""
