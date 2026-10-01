-- Migration 011: Add blur/shake quality-probe scores to media table (0.6.0)
-- Populated by backend.pipeline.quality_probe (first pipeline stage). quality_score
-- is the combined 0-1 metric the selection quality gate reads; blur_score/shake_score
-- are sub-metrics kept for debugging/calibration. All nullable — a NULL score never
-- rejects a clip in selection (missing data ≠ bad).
ALTER TABLE media ADD COLUMN IF NOT EXISTS quality_score REAL;
ALTER TABLE media ADD COLUMN IF NOT EXISTS blur_score REAL;
ALTER TABLE media ADD COLUMN IF NOT EXISTS shake_score REAL;
