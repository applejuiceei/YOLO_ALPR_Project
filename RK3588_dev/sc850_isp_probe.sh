#!/usr/bin/env bash
# Collect SC850SL/RKISP evidence and run short non-destructive stream tests.
# Usage on RK3588 board:
#   bash sc850_isp_probe.sh
# Optional custom output dir:
#   bash sc850_isp_probe.sh /tmp/my_sc850_probe

set -u

ts="$(date +%Y%m%d_%H%M%S 2>/dev/null || echo unknown_time)"
out="${1:-/tmp/sc850_isp_probe_${ts}}"
mkdir -p "$out"

section() {
  printf '\n===== %s =====\n' "$1"
}

save_cmd() {
  name="$1"
  shift
  section "$name" | tee "$out/${name}.log"
  {
    printf '$'
    printf ' %q' "$@"
    printf '\n'
    "$@"
  } >>"$out/${name}.log" 2>&1
  cat "$out/${name}.log"
}

save_shell() {
  name="$1"
  cmd="$2"
  section "$name" | tee "$out/${name}.log"
  {
    printf '$ %s\n' "$cmd"
    sh -c "$cmd"
  } >>"$out/${name}.log" 2>&1
  cat "$out/${name}.log"
}

try_stream() {
  node="$1"
  fmt="$2"
  width="$3"
  height="$4"
  tag="$5"
  [ -e "$node" ] || return 0

  log="$out/stream_${tag}.log"
  raw="$out/stream_${tag}.raw"

  section "stream_${tag}" | tee "$log"
  dmesg -C >/dev/null 2>&1 || true
  {
    printf '$ timeout 8 v4l2-ctl -d %s --set-fmt-video=width=%s,height=%s,pixelformat=%s --stream-mmap=4 --stream-count=5 --stream-to=%s --verbose\n' "$node" "$width" "$height" "$fmt" "$raw"
    timeout 8 v4l2-ctl -d "$node" \
      --set-fmt-video=width="$width",height="$height",pixelformat="$fmt" \
      --stream-mmap=4 \
      --stream-count=5 \
      --stream-to="$raw" \
      --verbose
    rc=$?
    printf '\nexit_code=%s\n' "$rc"
    ls -lh "$raw" 2>/dev/null || true
    printf '\n--- dmesg tail ---\n'
    dmesg | tail -n 220
  } >>"$log" 2>&1
  cat "$log"
}

section "SC850 ISP probe"
echo "Output dir: $out"

save_cmd "date" date
save_cmd "hostname" hostname
save_cmd "uname" uname -a
save_shell "process_camera" "ps -ef | grep -Ei 'rkaiq|aiq|isp|camera|iq|media|v4l' | grep -v grep || true"
save_shell "dev_nodes" "ls -l /dev/video* /dev/media* /dev/v4l-subdev* 2>/dev/null || true"
save_shell "i2c_devices" "ls -l /sys/bus/i2c/devices 2>/dev/null || true"
save_shell "i2c_links" "find /sys/bus/i2c/devices -maxdepth 2 \\( -type l -o -type f \\) 2>/dev/null | grep -Ei 'sc850|imx585|camera|sensor|0010|0030|0042|0051' || true"
save_shell "iq_files" "find /etc /usr /oem -iname '*sc850*' -o -iname '*iq*' 2>/dev/null | head -n 200 || true"
save_shell "device_tree_sc850" "grep -Rai 'sc850\\|imx585\\|camera-module\\|lens\\|sensor\\|rkisp\\|mipi' /proc/device-tree 2>/dev/null | head -n 240 || true"
save_shell "dmesg_camera_recent" "dmesg | grep -Ei 'sc850|imx585|camera|sensor|mipi|csi|cif|isp|dphy|i2c|rkaiq' | tail -n 260 || true"

for m in /dev/media*; do
  [ -e "$m" ] || continue
  base="$(basename "$m")"
  save_shell "media_${base}" "media-ctl -d '$m' -p || true"
done

for s in /dev/v4l-subdev*; do
  [ -e "$s" ] || continue
  base="$(basename "$s")"
  save_shell "subdev_${base}_all" "v4l2-ctl -d '$s' --all || true"
  save_shell "subdev_${base}_ctrls" "v4l2-ctl -d '$s' --list-ctrls || true"
done

for v in /dev/video*; do
  [ -e "$v" ] || continue
  base="$(basename "$v")"
  save_shell "video_${base}_all" "v4l2-ctl -d '$v' --all || true"
  save_shell "video_${base}_formats" "v4l2-ctl -d '$v' --list-formats-ext || true"
done

# Known nodes from current investigation.
try_stream /dev/video33 BG10 3840 2160 video33_bg10_raw
try_stream /dev/video53 NV12 3840 2160 video53_nv12_4k
try_stream /dev/video53 UYVY 3840 2160 video53_uyvy_4k
try_stream /dev/video53 NV12 1920 1080 video53_nv12_1080p
try_stream /dev/video53 UYVY 1920 1080 video53_uyvy_1080p
try_stream /dev/video44 NV12 3840 2160 video44_nv12_4k
try_stream /dev/video44 UYVY 3840 2160 video44_uyvy_4k
try_stream /dev/video44 NV12 1920 1080 video44_nv12_1080p
try_stream /dev/video44 UYVY 1920 1080 video44_uyvy_1080p

# SC850SL probe 20250626_124614 shows rkisp1-vir1 mainpath on /dev/video71.
# Device numbers can differ between boards/boots, so keep both known candidates.
try_stream /dev/video71 NV12 3840 2160 video71_nv12_4k
try_stream /dev/video71 UYVY 3840 2160 video71_uyvy_4k
try_stream /dev/video72 NV12 1920 1080 video72_nv12_1080p
try_stream /dev/video72 UYVY 1920 1080 video72_uyvy_1080p

summary="$out/summary.txt"
{
  echo "Output dir: $out"
  echo
  echo "Stream raw files:"
  ls -lh "$out"/stream_*.raw 2>/dev/null || true
  echo
  echo "Stream failures and kernel hints:"
  grep -RaiE 'VIDIOC_STREAMON|Operation not permitted|check rkisp|failed|timeout|stream on|stream OFF|rkisp|sc850|csi|dphy|i2c' "$out"/stream_*.log 2>/dev/null || true
  echo
  echo "Media files:"
  ls -lh "$out"/media_*.log 2>/dev/null || true
} >"$summary"

section "DONE"
cat "$summary"
echo
echo "Please archive or copy this directory for analysis:"
echo "$out"
