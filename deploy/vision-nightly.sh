#!/usr/bin/env bash
#
# Nightly local-vision hook-scoring (Enhancement E) on the VPS.
# Runs the Moondream/Ollama batch off-peak, in a fixed small batch, with no
# overlap. CPU isolation is enforced by the `cpus:` caps on the ollama + api
# containers in docker-compose.yml — this script just bounds *when* and *how
# much* runs. nice/ionice are belt-and-suspenders for the ffmpeg client side.
#
# Install (on the server, as the deploy user):
#   chmod +x /srv/social-media-cms/deploy/vision-nightly.sh
#   crontab -e   →   0 3 * * *  /srv/social-media-cms/deploy/vision-nightly.sh
#
# Tune the nightly volume with VISION_LIMIT (default 50).
#
set -euo pipefail

# Directory that holds docker-compose.yml + .env on the server.
COMPOSE_DIR="${COMPOSE_DIR:-/srv/social-media-cms}"
LIMIT="${VISION_LIMIT:-50}"
LOG="${VISION_LOG:-/srv/social-media-cms/logs/vision-nightly.log}"

# Ensure the log directory exists, else the >>"$LOG" redirects below abort
# the script (and cron) before anything is written.
mkdir -p "$(dirname "$LOG")"

# Single instance only — skip if a previous night's run is somehow still going.
exec 9>/tmp/vision-nightly.lock
if ! flock -n 9; then
    echo "$(date -Is) already running — skipping" >>"$LOG"
    exit 0
fi

echo "$(date -Is) start limit=$LIMIT" >>"$LOG"
cd "$COMPOSE_DIR"

set +e
nice -n 19 ionice -c3 docker compose exec -T api \
    python -m backend.pipeline.classify_vision --provider auto --limit "$LIMIT" \
    >>"$LOG" 2>&1
rc=$?
set -e

echo "$(date -Is) done rc=$rc" >>"$LOG"
exit "$rc"
