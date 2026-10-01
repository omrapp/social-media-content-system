#!/usr/bin/env bash
# Manual rollback. Usage: rollback.sh <image_tag>
# Example: rollback.sh v0.1.0
set -euo pipefail

TAG="${1:?Usage: rollback.sh <image_tag>}"
COMPOSE_DIR="/srv/social-media-cms"
HEALTH_URL="http://localhost:8000/api/health"

cd "$COMPOSE_DIR"

echo "==> Rolling back to social-media-cms:$TAG"
IMAGE_TAG="$TAG" docker compose up -d --remove-orphans

sleep 5
if curl -fsS "$HEALTH_URL" | grep -q '"ok"'; then
    echo "$TAG" > "$COMPOSE_DIR/.last-good"
    echo "==> Rollback to $TAG succeeded"
else
    echo "==> WARNING: $TAG also unhealthy — check logs: docker compose logs api"
    exit 1
fi
