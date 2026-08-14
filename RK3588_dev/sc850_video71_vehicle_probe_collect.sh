#!/usr/bin/env bash
set -u

# Run this on the remote SC850SL RK3588 board.
# It collects /dev/video71 NV12 diagnostics, runs one bounded vehicle-box probe,
# and packages all feedback into a single tar.gz for transfer back to Windows.

TAG="${TAG:-$(date +%Y%m%d_%H%M%S)}"
BASE="/tmp/sc850_video71_vehicle_probe_${TAG}"
RUN_BASE="/root/alpr_topk_rk3588/runs_sc850_video71_nv12_vehicle_probe_${TAG}"
TARBALL="/tmp/sc850_video71_vehicle_probe_${TAG}.tar.gz"

MAX_FRAMES="${MAX_FRAMES:-300}"
CAMERA_DEVICE="${CAMERA_DEVICE:-/dev/video71}"
CAMERA_WIDTH="${CAMERA_WIDTH:-3840}"
CAMERA_HEIGHT="${CAMERA_HEIGHT:-2160}"
ARTIFACT_FULL_FRAME_MAX_WIDTH="${ARTIFACT_FULL_FRAME_MAX_WIDTH:-960}"
MAX_REJECTED_PER_TRACK="${MAX_REJECTED_PER_TRACK:-1}"
VEHICLE_SOURCE="${VEHICLE_SOURCE:-rknn}"
VEHICLE_CONF="${VEHICLE_CONF:-0.12}"
MIN_PROCESS_VEHICLE_CONF="${MIN_PROCESS_VEHICLE_CONF:-1.10}"
PLATE_CONF="${PLATE_CONF:-0.25}"
OCR_ENGINE="${OCR_ENGINE:-none}"
VOTE_THRESHOLD="${VOTE_THRESHOLD:-3}"
MIN_CHAR_VOTE_RATIO="${MIN_CHAR_VOTE_RATIO:-0.65}"
MIN_OCR_CONF="${MIN_OCR_CONF:-0.70}"
MIN_LOCK_VEHICLE_CONF="${MIN_LOCK_VEHICLE_CONF:-0.70}"
MIN_LOCK_CANDIDATE_SCORE="${MIN_LOCK_CANDIDATE_SCORE:-0.0}"
MIN_LOCK_OBB_CONF="${MIN_LOCK_OBB_CONF:-0.0}"
STRICT_PLATE_FORMAT="${STRICT_PLATE_FORMAT:-0}"
ROI_X1="${ROI_X1:-0.03}"
ROI_Y1="${ROI_Y1:-0.15}"
ROI_X2="${ROI_X2:-0.55}"
ROI_Y2="${ROI_Y2:-0.95}"
TILE_ROWS="${TILE_ROWS:-2}"
TILE_COLS="${TILE_COLS:-2}"
TILE_OVERLAP="${TILE_OVERLAP:-0.18}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-900}"
VEHICLE_MODEL="${VEHICLE_MODEL:-/root/rk3588_alpr_roadtest_bundle_20260701/deploy/vehicle.rknn}"
PLATE_MODEL="${PLATE_MODEL:-/root/rk3588_alpr_roadtest_bundle_20260701/deploy/best_obb.rknn}"

STRICT_PLATE_FORMAT_ARGS=()
case "$STRICT_PLATE_FORMAT" in
  1|true|TRUE|yes|YES|on|ON)
    STRICT_PLATE_FORMAT_ARGS=(--strict-plate-format)
    ;;
esac

if [ ! -f "$VEHICLE_MODEL" ] && [ -f /root/deploy/vehicle.rknn ]; then
  VEHICLE_MODEL="/root/deploy/vehicle.rknn"
fi
if [ ! -f "$PLATE_MODEL" ] && [ -f /root/deploy/best_obb.rknn ]; then
  PLATE_MODEL="/root/deploy/best_obb.rknn"
fi

mkdir -p "$BASE"

log() {
  printf '\n[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$BASE/collect.log"
}

capture_cmd() {
  local name="$1"
  shift
  log "RUN ${name}: $*"
  "$@" >"$BASE/${name}.txt" 2>&1
  local rc=$?
  echo "exit_code=${rc}" >>"$BASE/${name}.txt"
  return 0
}

capture_shell() {
  local name="$1"
  local cmd="$2"
  log "RUN ${name}: ${cmd}"
  sh -c "$cmd" >"$BASE/${name}.txt" 2>&1
  local rc=$?
  echo "exit_code=${rc}" >>"$BASE/${name}.txt"
  return 0
}

log "collect dir: $BASE"
log "run dir: $RUN_BASE"

capture_cmd date date
capture_cmd uname uname -a
capture_shell dev_nodes "ls -l /dev/video-camera0 /dev/video33 /dev/video44 /dev/video53 /dev/video71 /dev/video72 2>/dev/null; readlink -f /dev/video-camera0 2>/dev/null || true"
capture_shell process_snapshot "ps -ef | grep -E 'rkaiq|rk3588_topk|v4l2-ctl|http.server|stream.py' | grep -v grep || true"
capture_shell frame_before "stat /tmp/frame.jpg 2>/dev/null || true; md5sum /tmp/frame.jpg 2>/dev/null || true"

if command -v v4l2-ctl >/dev/null 2>&1; then
  capture_cmd video71_all v4l2-ctl -d "$CAMERA_DEVICE" --all
  capture_cmd video71_formats v4l2-ctl -d "$CAMERA_DEVICE" --list-formats-ext
else
  echo "v4l2-ctl not found" >"$BASE/video71_all.txt"
fi

if command -v media-ctl >/dev/null 2>&1; then
  for media_dev in /dev/media7 /dev/media6 /dev/media5; do
    if [ -e "$media_dev" ]; then
      capture_cmd "media_$(basename "$media_dev")" media-ctl -d "$media_dev" -p
    fi
  done
else
  echo "media-ctl not found" >"$BASE/media_ctl_missing.txt"
fi

capture_shell rkaiq_status "systemctl status rkaiq_3A.service --no-pager 2>/dev/null || true"
capture_shell rkaiq_journal "journalctl -u rkaiq_3A.service -n 250 --no-pager 2>/dev/null || true"
capture_shell dmesg_before "dmesg | tail -n 250 || true"
capture_shell script_hash "cd /root/alpr_topk_rk3588 2>/dev/null && ls -l rk3588_topk_capture_mipi_debug_sc850.py rk3588_topk_capture_mipi_debug.py rk3588_topk_capture.py 2>/dev/null && sha256sum rk3588_topk_capture_mipi_debug_sc850.py rk3588_topk_capture_mipi_debug.py rk3588_topk_capture.py 2>/dev/null || true"
capture_shell model_hash "ls -l /root/rk3588_alpr_roadtest_bundle_20260701/deploy/vehicle.rknn /root/rk3588_alpr_roadtest_bundle_20260701/deploy/best_obb.rknn /root/deploy/vehicle.rknn /root/deploy/best_obb.rknn 2>/dev/null; sha256sum /root/rk3588_alpr_roadtest_bundle_20260701/deploy/vehicle.rknn /root/rk3588_alpr_roadtest_bundle_20260701/deploy/best_obb.rknn /root/deploy/vehicle.rknn /root/deploy/best_obb.rknn 2>/dev/null || true"

if command -v v4l2-ctl >/dev/null 2>&1; then
  log "capturing one raw NV12 frame from ${CAMERA_DEVICE}"
  timeout 15 v4l2-ctl -d "$CAMERA_DEVICE" \
    --set-fmt-video=width="$CAMERA_WIDTH",height="$CAMERA_HEIGHT",pixelformat=NV12 \
    --stream-mmap=4 \
    --stream-count=1 \
    --stream-to="$BASE/video71_1f_nv12.raw" \
    --verbose >"$BASE/video71_1f_nv12_stream.txt" 2>&1 || true
  ls -lh "$BASE"/video71_1f_nv12.raw >>"$BASE/video71_1f_nv12_stream.txt" 2>&1 || true

  RAW_PATH="$BASE/video71_1f_nv12.raw" JPG_PATH="$BASE/video71_1f_nv12.jpg" WIDTH="$CAMERA_WIDTH" HEIGHT="$CAMERA_HEIGHT" python3 - <<'PY' >"$BASE/video71_1f_nv12_convert.txt" 2>&1 || true
import os
from pathlib import Path
import numpy as np
import cv2

raw_path = Path(os.environ["RAW_PATH"])
jpg_path = Path(os.environ["JPG_PATH"])
w = int(os.environ["WIDTH"])
h = int(os.environ["HEIGHT"])
expected = w * h * 3 // 2
data = raw_path.read_bytes() if raw_path.exists() else b""
print(f"raw_size={len(data)} expected={expected}")
if len(data) >= expected:
    arr = np.frombuffer(data[:expected], dtype=np.uint8).reshape((h * 3 // 2, w))
    bgr = cv2.cvtColor(arr, cv2.COLOR_YUV2BGR_NV12)
    ok = cv2.imwrite(str(jpg_path), bgr)
    print(f"jpg_written={ok} path={jpg_path}")
else:
    print("raw too small; skip jpg")
PY
fi

log "starting ALPR vehicle-box probe"
cd /root/alpr_topk_rk3588 || {
  log "ERROR: /root/alpr_topk_rk3588 missing"
  tar -czf "$TARBALL" -C /tmp "$(basename "$BASE")"
  echo "$TARBALL"
  exit 0
}

timeout "$TIMEOUT_SECONDS" python3 rk3588_topk_capture_mipi_debug_sc850.py \
  --video mipi \
  --camera-device "$CAMERA_DEVICE" \
  --camera-width "$CAMERA_WIDTH" \
  --camera-height "$CAMERA_HEIGHT" \
  --mipi-backend v4l2ctl \
  --mipi-fourcc NV12 \
  --mipi-color-mode nv12 \
  --vehicle-model "$VEHICLE_MODEL" \
  --plate-model "$PLATE_MODEL" \
  --ocr-engine "$OCR_ENGINE" \
  --output "$RUN_BASE" \
  --artifact-full-frame-max-width "$ARTIFACT_FULL_FRAME_MAX_WIDTH" \
  --max-rejected-per-track "$MAX_REJECTED_PER_TRACK" \
  --detect-roi "$ROI_X1" "$ROI_Y1" "$ROI_X2" "$ROI_Y2" \
  --draw-detect-roi \
  --process-roi "$ROI_X1" "$ROI_Y1" "$ROI_X2" "$ROI_Y2" \
  --draw-process-roi \
  --vehicle-source "$VEHICLE_SOURCE" \
  --vehicle-detect-interval 1 \
  --vehicle-conf "$VEHICLE_CONF" \
  --plate-conf "$PLATE_CONF" \
  --detect-roi-tiles "$TILE_ROWS" "$TILE_COLS" \
  --detect-roi-overlap "$TILE_OVERLAP" \
  --min-process-vehicle-conf "$MIN_PROCESS_VEHICLE_CONF" \
  --vote-threshold "$VOTE_THRESHOLD" \
  --min-char-vote-ratio "$MIN_CHAR_VOTE_RATIO" \
  --min-ocr-conf "$MIN_OCR_CONF" \
  --min-lock-vehicle-conf "$MIN_LOCK_VEHICLE_CONF" \
  --min-lock-candidate-score "$MIN_LOCK_CANDIDATE_SCORE" \
  --min-lock-obb-conf "$MIN_LOCK_OBB_CONF" \
  "${STRICT_PLATE_FORMAT_ARGS[@]}" \
  --motion-min-aspect 1.0 \
  --motion-min-fill-ratio 0.18 \
  --motion-accept-roi "$ROI_X1" "$ROI_Y1" "$ROI_X2" "$ROI_Y2" \
  --publish-frame /tmp/frame.jpg \
  --publish-interval 1 \
  --progress-interval 20 \
  --max-frames "$MAX_FRAMES" >"$BASE/alpr_vehicle_probe.log" 2>&1 || true

capture_shell frame_after "stat /tmp/frame.jpg 2>/dev/null || true; md5sum /tmp/frame.jpg 2>/dev/null || true"
capture_shell dmesg_after "dmesg | tail -n 250 || true"

cp -f /tmp/frame.jpg "$BASE/frame_after.jpg" 2>/dev/null || true
if [ -d "$RUN_BASE" ]; then
  cp -a "$RUN_BASE" "$BASE/run"
fi

log "packaging feedback"
tar -czf "$TARBALL" -C /tmp "$(basename "$BASE")"
ls -lh "$TARBALL" | tee -a "$BASE/collect.log"
echo "$TARBALL"
