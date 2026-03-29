#!/usr/bin/env bash
# Deploy the leadgen API to VPS
# Usage: bash deploy/deploy-api.sh

set -euo pipefail

VPS_KEY="/Users/michal/git/visionvolve-vps/LightsailDefaultKey-eu-central-1.pem"
VPS_HOST="ec2-user@52.58.119.191"
VPS_DIR="/home/ec2-user/n8n-docker-caddy"
API_DIR="/home/ec2-user/leadgen-api"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "==> Deploying leadgen API to VPS..."

# 1. Copy Dockerfile
scp -i "$VPS_KEY" "${PROJECT_DIR}/Dockerfile.api" "${VPS_HOST}:${API_DIR}/"

# 2. Rsync entire api/ directory (includes agents/, tools/, services/memory/, services/multimodal/, services/registries/)
rsync -avz --delete \
  -e "ssh -i $VPS_KEY" \
  --exclude '__pycache__' --exclude '*.pyc' \
  "${PROJECT_DIR}/api/" "${VPS_HOST}:${API_DIR}/api/"
echo "    Synced API source files"

# 3. Copy compose overlay
scp -i "$VPS_KEY" "${PROJECT_DIR}/deploy/docker-compose.api.yml" "${VPS_HOST}:${VPS_DIR}/"
echo "    Copied docker-compose.api.yml"

# 4. Build and start the API container
ssh -i "$VPS_KEY" "$VPS_HOST" bash <<'REMOTE'
cd /home/ec2-user/n8n-docker-caddy
docker compose -f docker-compose.yml -f docker-compose.api.yml up -d --no-deps --build leadgen-api
echo "    leadgen-api container started"
REMOTE

# 5. Deploy Caddy snippet
echo "==> Deploying Caddy snippet..."
scp -i "$VPS_KEY" "${PROJECT_DIR}/deploy/prod.caddy" "${VPS_HOST}:/home/ec2-user/n8n-docker-caddy/caddy_config/conf.d/leadgen.caddy"
ssh -i "$VPS_KEY" "$VPS_HOST" "docker exec n8n-docker-caddy-caddy-1 caddy reload --config /etc/caddy/Caddyfile"

echo "==> API deployed to https://leadgen.visionvolve.com/api/health"
