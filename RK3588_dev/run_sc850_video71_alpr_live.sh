#!/usr/bin/env bash
set -euo pipefail

# Long-running SC850SL ALPR: use /dev/video71 exclusively while publishing
# annotated frames for the existing /root/deploy/stream.py browser viewer.
cd /root/alpr_topk_rk3588

CAMERA_DEVICE="${CAMERA_DEVICE:-/dev/video71}"
CAMERA_WIDTH="${CAMERA_WIDTH:-3840}"
CAMERA_HEIGHT="${CAMERA_HEIGHT:-2160}"
OUTPUT_DIR="${OUTPUT_DIR:-/root/alpr_topk_rk3588/runs_sc850_video71_live}"
PUBLISH_FRAME="${PUBLISH_FRAME:-/tmp/frame.jpg}"
STATE_RETENTION_FRAMES="${STATE_RETENTION_FRAMES:-120}"
LOCK_TEXT_DEDUPE_FRAMES="${LOCK_TEXT_DEDUPE_FRAMES:-60}"

# `quality` is the prior two-tile, full-preview configuration. `balanced`
# keeps original 4K plate crops and lock criteria but removes avoidable
# per-frame preview work and one vehicle-model pass.
ALPR_PROFILE="${ALPR_PROFILE:-balanced}"
case "$ALPR_PROFILE" in
  quality)
    DETECT_ROI_TILE_COLS="${DETECT_ROI_TILE_COLS:-2}"
    PUBLISH_INTERVAL="${PUBLISH_INTERVAL:-1}"
    PREVIEW_MAX_WIDTH="${PREVIEW_MAX_WIDTH:-1920}"
    PREVIEW_JPEG_QUALITY="${PREVIEW_JPEG_QUALITY:-75}"
    ;;
  balanced)
    DETECT_ROI_TILE_COLS="${DETECT_ROI_TILE_COLS:-1}"
    PUBLISH_INTERVAL="${PUBLISH_INTERVAL:-2}"
    PREVIEW_MAX_WIDTH="${PREVIEW_MAX_WIDTH:-1280}"
    PREVIEW_JPEG_QUALITY="${PREVIEW_JPEG_QUALITY:-60}"
    ;;
  *)
    echo "Unknown ALPR_PROFILE: $ALPR_PROFILE (use quality or balanced)" >&2
    exit 2
    ;;
esac

# Recognition-first road region: keep the motor-vehicle lanes and exclude the
# building facade, parking bays and the non-motor-vehicle lane on the right.
# The same region is used for vehicle detection and plate/OCR eligibility.
ROAD_ROI=(0.02 0.18 0.57 0.95)

echo "SC850 ALPR profile=$ALPR_PROFILE tiles=1x$DETECT_ROI_TILE_COLS preview=${PREVIEW_MAX_WIDTH}px/$PUBLISH_INTERVAL frames/q$PREVIEW_JPEG_QUALITY" >&2

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
  --output "$OUTPUT_DIR" \
  --artifact-full-frame-max-width 960 \
  --max-rejected-per-track 1 \
  --state-retention-frames "$STATE_RETENTION_FRAMES" \
  --detect-roi "${ROAD_ROI[@]}" \
  --draw-detect-roi \
  --process-roi "${ROAD_ROI[@]}" \
  --vehicle-source rknn \
  --vehicle-detect-interval 1 \
  --vehicle-conf 0.25 \
  --plate-conf 0.25 \
  --detect-roi-tiles 1 "$DETECT_ROI_TILE_COLS" \
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
  --draw-min-vehicle-conf 0.25 \
  --draw-min-vehicle-width 180 \
  --draw-min-vehicle-height 110 \
  --draw-min-vehicle-area 20000 \
  --track-max-age 2 \
  --max-locked-predict-frames 0 \
  --max-unlocked-predict-frames 0 \
  --no-locked-reassociate \
  --plate-attempt-interval 1 \
  --vote-threshold 2 \
  --lock-text-dedupe-frames "$LOCK_TEXT_DEDUPE_FRAMES" \
  --rk-adaptive \
  --adaptive-min-exact-votes 2 \
  --adaptive-min-strong-votes 2 \
  --adaptive-min-vote-frames 2 \
  --min-char-vote-ratio 0.65 \
  --min-ocr-conf 0.70 \
  --strict-plate-format \
  --publish-frame "$PUBLISH_FRAME" \
  --publish-interval "$PUBLISH_INTERVAL" \
  --preview-jpeg-quality "$PREVIEW_JPEG_QUALITY" \
  --preview-max-width "$PREVIEW_MAX_WIDTH" \
  --progress-interval 20
