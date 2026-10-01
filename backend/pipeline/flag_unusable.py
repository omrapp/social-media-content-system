"""
flag_unusable — one-shot archive sweep that permanently shelves raw clips which
fail the *hard, present-field* selection rules (duration too short, resolution too
low). Sets do_not_use=1 so they never resurface in any selection path.

Scope is deliberately narrow:
  - Only `duration_s` and resolution (`min(width,height)`) — fields that never
    change for a given source file, so a permanent flag is safe.
  - hook_score / quality_score are NOT used here — those are soft, mutable signals
    handled at selection time (selection gate) and by the quality_probe stage.
  - Null-safe: a clip is flagged ONLY when the field is present and below threshold.
    Missing data is never flagged.

Idempotent: clips already flagged do_not_use are skipped. Run --dry-run first.

CLI:
  python -m backend.pipeline.flag_unusable --dry-run
  python -m backend.pipeline.flag_unusable
"""

from __future__ import annotations

import argparse
import json
import logging

from backend.db import (
    _use_supabase, get_supabase, db_retry, get_setting, query, execute,
)

log = logging.getLogger(__name__)


def _thresholds() -> dict:
    cfg = get_setting("selection") or {}

    def _num(key, default):
        try:
            return float(cfg.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    return {
        "min_duration_s": _num("min_duration_s", 10.0),
        "min_short_side": _num("min_short_side", 720.0),
    }


def _reason(row: dict, thr: dict) -> str | None:
    """Return a flag reason if the clip fails a hard present-field rule, else None."""
    dur = row.get("duration_s")
    if dur is not None and thr["min_duration_s"] > 0 and dur < thr["min_duration_s"]:
        return f"too_short({dur:.1f}s<{thr['min_duration_s']:.0f}s)"

    w, h = row.get("width"), row.get("height")
    if w and h and thr["min_short_side"] > 0 and min(w, h) < thr["min_short_side"]:
        return f"low_res({min(w, h)}px<{thr['min_short_side']:.0f}px)"

    return None


def _load_candidates() -> list[dict]:
    """Raw VIDEO clips not already shelved."""
    if _use_supabase():
        PAGE = 1000
        rows, offset = [], 0
        sb = get_supabase()
        while True:
            batch = (
                sb.table("media")
                .select("id,duration_s,width,height,do_not_use,media_type,status")
                .eq("status", "raw")
                .eq("media_type", "VIDEO")
                .eq("do_not_use", False)
                .range(offset, offset + PAGE - 1)
                .execute()
                .data or []
            )
            rows.extend(batch)
            if len(batch) < PAGE:
                break
            offset += PAGE
        return rows
    return query(
        "SELECT id, duration_s, width, height, do_not_use, media_type, status "
        "FROM media WHERE status='raw' AND media_type='VIDEO' "
        "AND COALESCE(do_not_use, 0) = 0"
    )


def run(dry_run: bool = False) -> dict:
    thr = _thresholds()
    rows = _load_candidates()

    flagged = []
    reasons: dict[str, int] = {}
    for r in rows:
        reason = _reason(r, thr)
        if reason:
            flagged.append({"id": r["id"], "reason": reason})
            key = reason.split("(")[0]
            reasons[key] = reasons.get(key, 0) + 1

    log.info("flag_unusable: scanned=%d would_flag=%d reasons=%s dry_run=%s",
             len(rows), len(flagged), reasons, dry_run)

    if not dry_run:
        for f in flagged:
            if _use_supabase():
                db_retry(lambda fid=f["id"]: get_supabase().table("media").update(
                    {"do_not_use": True}).eq("id", fid).execute())
            else:
                execute("UPDATE media SET do_not_use=1 WHERE id=?", (f["id"],))
            log.info("flag_unusable: flagged media_id=%s — %s", f["id"], f["reason"])

    return {
        "scanned": len(rows),
        "flagged": len(flagged),
        "reasons": reasons,
        "dry_run": dry_run,
        "thresholds": thr,
        "sample": flagged[:10],
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(dry_run=args.dry_run), indent=2, default=str))
