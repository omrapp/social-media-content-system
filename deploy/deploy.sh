#!/usr/bin/env bash
# Runs on your server after CI pushes a new image.
# Usage: deploy.sh <image_tag>
# Called by .github/workflows/release.yml via SSH.
set -euo pipefail

TAG="${1:?Usage: deploy.sh <image_tag>}"
COMPOSE_DIR="/srv/social-media-cms"
LAST_GOOD_FILE="$COMPOSE_DIR/.last-good"
HEALTH_URL="http://localhost:8000/api/health"
GHCR_OWNER="${GHCR_OWNER:-}"
IMAGE_REPO="ghcr.io/${GHCR_OWNER}/social-media-cms"

cd "$COMPOSE_DIR"

# Persist previous good tag for rollback
PREV_TAG=$(cat "$LAST_GOOD_FILE" 2>/dev/null || echo "latest")

echo "==> Deploying social-media-cms:$TAG (previous: $PREV_TAG)"

# Free disk: remove only dangling (untagged) layers — safe pre-deploy.
# Versioned images (vX.Y.Z) are cleaned after the new container is healthy.
echo "==> Pruning dangling Docker images"
docker image prune -f

# Remove old social-media-cms version images, keeping the current TAG image (and any
# tag pointing at the same image ID, e.g. :latest). Targeted by image ID so
# co-hosted projects' images are never touched. Only runs once the new container
# is up and healthy, so the rollback image survives a failed deploy.
prune_old_versions() {
    if [ -z "$GHCR_OWNER" ]; then
        echo "==> Skipping old-version prune (GHCR_OWNER unset)"
        return 0
    fi
    local current_id
    current_id=$(docker images --no-trunc -q "${IMAGE_REPO}:${TAG}" | head -n1)
    if [ -z "$current_id" ]; then
        echo "==> Skipping old-version prune (current image id not found)"
        return 0
    fi
    echo "==> Removing old ${IMAGE_REPO} images (keeping $TAG)"
    docker images --no-trunc -q "${IMAGE_REPO}" \
        | sort -u \
        | grep -v "^${current_id}$" \
        | xargs -r docker rmi -f 2>/dev/null || true
}

# Pull new image — ONLY the api service. Pulling the whole compose stack also
# re-pulls ollama/ollama:latest (a large image) on every deploy, which times out
# the CI SSH step. ollama is a long-lived side service (restart: unless-stopped)
# and is left running untouched.
IMAGE_TAG="$TAG" docker compose pull api

# Rotate only the api container. --no-deps keeps ollama from being recreated;
# it has no depends_on and stays up on its own.
IMAGE_TAG="$TAG" docker compose up -d --no-deps api

# Poll health for 60 s
echo -n "==> Health check "
for i in $(seq 1 12); do
    sleep 5
    if curl -fsS "$HEALTH_URL" | grep -q '"ok"'; then
        echo " OK"
        echo "$TAG" > "$LAST_GOOD_FILE"
        prune_old_versions
        # Ensure vision nightly cron is registered (idempotent)
        CRON_LINE="0 3 * * * /srv/social-media-cms/deploy/vision-nightly.sh"
        ( crontab -l 2>/dev/null | grep -v "vision-nightly"; echo "$CRON_LINE" ) | crontab -
        echo "==> Vision cron registered"
        echo "==> Deploy $TAG succeeded"
        exit 0
    fi
    echo -n "."
done

# Health failed — rollback to previous good tag
echo ""
echo "==> Health check failed. Rolling back to $PREV_TAG"
IMAGE_TAG="$PREV_TAG" docker compose up -d --no-deps api
sleep 5
if curl -fsS "$HEALTH_URL" | grep -q '"ok"'; then
    echo "==> Rollback to $PREV_TAG succeeded"
else
    echo "==> WARNING: rollback also unhealthy — check container logs"
fi
exit 1
