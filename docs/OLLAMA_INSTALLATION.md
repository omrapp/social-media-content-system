# Ollama + Local Vision (Moondream) — Server Installation Guide

Step-by-step setup for the **nightly local vision hook-scoring** job (Enhancement E)
on your server. Follow top to bottom. Each step has a **verify** check — do
not move on until it passes.

> **What this sets up:** an `ollama` container running the Moondream vision model,
> capped to 2 cores / 3 GB so it never slows the live API or other services on the host.
> A host cron job runs a small batch at **03:00** every night, scoring clips that
> don't have a `hook_score` yet. The online pipeline keeps using Groq for new
> clips; this is the **$0 backfill / fallback** that drains the archive overnight.

---

## 0. Prerequisites & assumptions

- You can SSH into the VPS as the deploy user (the one that runs `docker`).
- Docker + the Docker Compose plugin are installed (`docker compose version` works).
- The app lives at **`/srv/social-media-cms`** and that directory holds
  `docker-compose.yml` and `.env`. If your path differs, substitute it everywhere
  below (and set `COMPOSE_DIR` in the cron step).
- These repo changes are already merged and deployed to the server:
  - `docker-compose.yml` → has the `ollama` service + `OLLAMA_URL` on `api`
  - `deploy/vision-nightly.sh` → the nightly wrapper
  - `backend/pipeline/classify_vision.py` → the vision batch module

**Verify the repo changes are on the server:**
```bash
cd /srv/social-media-cms
grep -A2 'OLLAMA_URL' docker-compose.yml          # should show http://ollama:11434
grep -q 'ollama:' docker-compose.yml && echo "ollama service present"
ls deploy/vision-nightly.sh
```
If any are missing, pull/deploy the latest code first (your normal release flow:
tag `release/*` → CI builds image → `deploy.sh` on the VPS), then come back.

---

## 1. Check server headroom

The `api` container already reserves **2.5 cores / 4 GB**. Ollama will add
**2 cores / 3 GB**. Make sure the box (and the neighbor project) can absorb it.

```bash
nproc          # total vCPUs
free -h        # total / available RAM
docker stats --no-stream   # current per-container usage
```

- If `nproc` ≥ 6 and you have ≥ 3 GB free → defaults are fine.
- If the box is smaller, **edit `docker-compose.yml`** and lower the `ollama`
  limits before continuing, e.g.:
  ```yaml
  ollama:
    mem_limit: 2g
    cpus: "1.5"
  ```

---

## 2. Create the model volume & start Ollama

Ollama stores pulled models in a bind-mounted directory so they survive
container restarts and redeploys.

```bash
cd /srv/social-media-cms
mkdir -p /srv/social-media-cms/ollama
docker compose up -d ollama
```

**Verify the container is up:**
```bash
docker compose ps ollama          # State should be "running"/"Up"
docker compose logs --tail 20 ollama
```
You should see Ollama's startup log with no crash loop.

---

## 3. Pull the Moondream model (one-time, ~1.7 GB)

```bash
docker compose exec ollama ollama pull moondream
```
This downloads into `/srv/social-media-cms/ollama`. It runs once; future restarts reuse it.

**Verify the model is installed:**
```bash
docker compose exec ollama ollama list      # "moondream" should be listed
```

---

## 4. Confirm the api container can reach Ollama

The vision batch runs **inside the `api` container** and calls Ollama over the
compose network at `http://ollama:11434`.

```bash
docker compose exec -T api python -c "import os,urllib.request; print(urllib.request.urlopen(os.environ.get('OLLAMA_URL','http://ollama:11434')+'/api/tags', timeout=5).status)"
```
**Expected:** prints `200`.
If it errors (connection refused / name not resolved):
- Ensure both services are on the same network: `docker compose ps` shows `api`
  and `ollama` in the same project.
- Recreate api so it picks up the new `OLLAMA_URL` env:
  `docker compose up -d api`

---

## 5. Smoke-test on 2 clips

Run the vision batch by hand for just 2 items before trusting the cron.

```bash
cd /srv/social-media-cms
docker compose exec -T api python -m backend.pipeline.classify_vision --provider local --limit 2
```
**Expected output:** `Vision: scored 2, skipped 0, failed 0 / 2` (numbers may vary
if some rows already had a score or had no video file).

**Verify the data landed** (Supabase): open the `media` table and confirm the two
processed rows now have a non-null `hook_score` and a `metadata.vision` object
with `provider: "local"`.

**If `scored 0 / failed N`:**
- `failed` → check the error in the command output. Common causes: model name
  mismatch (re-run step 3), Ollama not up (step 2), or the model is still warming
  up (wait, retry).
- `skipped` → those rows had no `local_path`/`reel_ready_path` file on disk; that's
  expected for rows whose media isn't on this server.

---

## 6. Make the wrapper script executable & test it

```bash
chmod +x /srv/social-media-cms/deploy/vision-nightly.sh
mkdir -p /srv/social-media-cms/logs

# Dry run the wrapper itself (uses VISION_LIMIT, default 50; override small here):
VISION_LIMIT=2 /srv/social-media-cms/deploy/vision-nightly.sh
```

**Verify the log:**
```bash
tail -n 10 /srv/social-media-cms/logs/vision-nightly.log
```
You should see a `start limit=2` line and a `done rc=0` line.

> If your compose file is **not** in `/srv/social-media-cms`, run the script with
> `COMPOSE_DIR=/your/path VISION_LIMIT=2 /srv/social-media-cms/deploy/vision-nightly.sh`
> and add that `COMPOSE_DIR=...` to the cron line in step 7.

---

## 7. Install the nightly cron (03:00 server time)

First confirm the server's timezone so 03:00 is actually off-peak for you:
```bash
timedatectl        # look at "Time zone"
```

Then add the cron entry:
```bash
crontab -e
```
Add this line (adjust the hour if the box isn't on your off-peak timezone):
```cron
0 3 * * *  /srv/social-media-cms/deploy/vision-nightly.sh
```
Save and exit.

**Verify the cron is registered:**
```bash
crontab -l        # the 0 3 line should be listed
```

---

## 8. Verify the first real nightly run

The morning after the cron first fires:
```bash
tail -n 30 /srv/social-media-cms/logs/vision-nightly.log
```
Look for a `start limit=50` and a `done rc=0`. Then spot-check the `media` table:
the count of rows with a non-null `hook_score` should have grown by up to ~50.

You're done. The job will keep draining ~50 clips/night until every clip on the
server has a `hook_score`, then it only touches newly added clips.

---

## Tuning & operations

| Goal | How |
|---|---|
| Process more per night | Set `VISION_LIMIT` higher in the cron line, e.g. `VISION_LIMIT=150 /srv/.../vision-nightly.sh` |
| One-off manual drain | `VISION_LIMIT=300 /srv/social-media-cms/deploy/vision-nightly.sh` |
| Pause the job | Comment out the cron line (`#` prefix) via `crontab -e` |
| Disable vision globally | Set `vision.enabled = false` in app Settings (the module returns a skip) |
| Better accuracy (more RAM/CPU) | `docker compose exec ollama ollama pull qwen2.5vl:3b`, then add `OLLAMA_VISION_MODEL=qwen2.5vl:3b` to `.env` and `docker compose up -d api` |
| Watch live resource use during a run | `docker stats` in another SSH session while step 5/6 runs |

---

## Troubleshooting

| Symptom | Likely cause → fix |
|---|---|
| `connection refused` to ollama | ollama container down → `docker compose up -d ollama`; re-check step 4 |
| `model 'moondream' not found` | model not pulled → repeat step 3; confirm with `ollama list` |
| Batch prints `failed N` | inspect the printed error; often a warm-up timeout → re-run; or model name mismatch |
| All rows `skipped` | no video files at `local_path`/`reel_ready_path` on this host → expected for off-host media |
| api latency spikes at 03:00 | lower `ollama` `cpus:` in compose, or shrink `VISION_LIMIT`, or move the cron to a quieter hour |
| Out-of-memory / container killed | raise `ollama` `mem_limit` (if headroom) or use a smaller model; Moondream needs ~2–3 GB |
| Cron didn't run | check server TZ (`timedatectl`), confirm `crontab -l`, check `/var/log/syslog` for cron entries, ensure script is `chmod +x` |

---

## Rollback / uninstall

```bash
# Stop and remove the nightly job
crontab -e        # delete the 0 3 line

# Stop Ollama (keeps the model files)
cd /srv/social-media-cms
docker compose stop ollama

# Full removal (also frees the ~1.7 GB model)
docker compose rm -sf ollama
rm -rf /srv/social-media-cms/ollama
```
The online Groq vision path and the rest of the pipeline are unaffected — only
the local nightly backfill stops.
