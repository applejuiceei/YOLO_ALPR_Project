#!/usr/bin/env bash
set -euo pipefail

# Post-focus SC850SL 4K ALPR validation.
#
# Keep vehicle detection broad enough to acquire complete vehicles, but only
# start plate OBB/OCR after the vehicle center enters the useful road corridor.
# This file is intentionally independent from the validated 20260730 baseline.
cd /root/alpr_topk_rk3588

CAMERA_DEVICE="${CAMERA_DEVICE:-/dev/video71}"
CAMERA_WIDTH="${CAMERA_WIDTH:-3840}"
CAMERA_HEIGHT="${CAMERA_HEIGHT:-2160}"
OUTPUT_DIR="${OUTPUT_DIR:-/root/alpr_topk_rk3588/runs_sc850_video71_postfocus_trafficcorridor_4k_accuracy}"
PUBLISH_FRAME="${PUBLISH_FRAME:-/tmp/frame.jpg}"
STATE_RETENTION_FRAMES="${STATE_RETENTION_FRAMES:-120}"
LOCK_TEXT_DEDUPE_FRAMES="${LOCK_TEXT_DEDUPE_FRAMES:-60}"
MAX_FRAMES="${MAX_FRAMES:-0}"

# Native-resolution browser publication remains comparable with the previous
# 4K-accuracy run. The inference path always receives the original 4K frame.
PUBLISH_INTERVAL="${PUBLISH_INTERVAL:-4}"
PREVIEW_MAX_WIDTH="${PREVIEW_MAX_WIDTH:-3840}"
PREVIEW_JPEG_QUALITY="${PREVIEW_JPEG_QUALITY:-70}"

# Detection ROI: acquire full vehicles along both visible carriageways.
# Process ROI: admit plate/OCR work only after the vehicle center enters the
# evidence-backed corridor; this excludes right-edge overlap failures.
DETECT_ROI=(0.24 0.05 0.99 0.99)
PROCESS_ROI=(0.33 0.12 0.93 0.90)

echo \
  "SC850 ALPR profile=postfocus_trafficcorridor_4k_accuracy " \
  "detect_roi=${DETECT_ROI[*]} process_roi=${PROCESS_ROI[*]} " \
  "tiles=1x1 preview=${PREVIEW_MAX_WIDTH}px/${PUBLISH_INTERVAL} frames/q${PREVIEW_JPEG_QUALITY} " \
  "max_frames=${MAX_FRAMES}" >&2

exec python3 rk3588_topk_capture_mipi_debug_sc850.py \
  --video mipi \
  --camera-device "$CAMERA_DEVICE" \
  --camera-width "$CAMERA_WIDTH" \
  --camera-height "$CAMERA_HEIGHT" \
  --mipi-backend v4l2ctl \
  --mipi-fourcc NV12 \
  --mipi-color-mode nv12 \
  --vehicle-model /root/rk3588_alpr_roadtest_bundle_20260701/deploy/vehicle.rknn \
  --plate-model /root/rk3588_alpr_roadtest_bundle_20260701/deploy/best_obb.rknn \
  --ocr-engine hyperlpr3 \
  --hyperlpr-pre-ocr \
  --output "$OUTPUT_DIR" \
  --artifact-full-frame-max-width 960 \
  --max-rejected-per-track 3 \
  --state-retention-frames "$STATE_RETENTION_FRAMES" \
  --detect-roi "${DETECT_ROI[@]}" \
  --draw-detect-roi \
  --process-roi "${PROCESS_ROI[@]}" \
  --draw-process-roi \
  --vehicle-source rknn \
  --vehicle-detect-interval 1 \
  --vehicle-conf 0.25 \
  --plate-conf 0.25 \
  --detect-roi-tiles 1 1 \
  --detect-roi-overlap 0.18 \
  --min-process-vehicle-conf 0.25 \
  --min-process-vehicle-width 180 \
  --min-process-vehicle-height 110 \
  --min-process-vehicle-area 20000 \
  --min-process-vehicle-area-ratio 0.006 \
  --min-lock-vehicle-conf 0.25 \
  --min-lock-vehicle-width 180 \
  --min-lock-vehicle-height 110 \
  --min-lock-vehicle-area 20000 \
  --min-lock-vehicle-area-ratio 0.006 \
  --min-lock-candidate-score 0.35 \
  --min-lock-obb-conf 0.40 \
  --min-plate-obb-conf 0.40 \
  --min-plate-vehicle-overlap 0.35 \
  --draw-min-vehicle-conf 0.25 \
  --draw-min-vehicle-width 180 \
  --draw-min-vehicle-height 110 \
  --draw-min-vehicle-area 20000 \
  --track-center-threshold 0.35 \
  --track-max-age 6 \
  --max-locked-predict-frames 0 \
  --max-unlocked-predict-frames 0 \
  --plate-attempt-interval 1 \
  --vote-threshold 2 \
  --lock-text-dedupe-frames "$LOCK_TEXT_DEDUPE_FRAMES" \
  --rk-adaptive \
  --adaptive-min-exact-votes 2 \
  --adaptive-min-strong-votes 2 \
  --adaptive-min-vote-frames 2 \
  --min-char-vote-ratio 0.65 \
  --min-ocr-conf 0.60 \
  --strict-plate-format \
  --publish-frame "$PUBLISH_FRAME" \
  --publish-interval "$PUBLISH_INTERVAL" \
  --preview-jpeg-quality "$PREVIEW_JPEG_QUALITY" \
  --preview-max-width "$PREVIEW_MAX_WIDTH" \
  --progress-interval 20 \
  --max-frames "$MAX_FRAMES"
