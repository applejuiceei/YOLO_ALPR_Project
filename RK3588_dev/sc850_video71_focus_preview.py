#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


def read_exact(stream, size: int) -> Optional[bytes]:
    buffer = bytearray(size)
    view = memoryview(buffer)
    offset = 0
    while offset < size:
        count = stream.readinto(view[offset:])
        if not count:
            return None
        offset += count
    return bytes(buffer)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f"{path.stem}_tmp{path.suffix}")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def atomic_write_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(f"{path.stem}_tmp{path.suffix}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def encode_jpeg(image: np.ndarray, quality: int) -> bytes:
    ok, encoded = cv2.imencode(
        ".jpg",
        image,
        [cv2.IMWRITE_JPEG_QUALITY, quality],
    )
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return encoded.tobytes()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Low-latency SC850SL focus assistant without ALPR inference."
    )
    parser.add_argument("--device", default="/dev/video71")
    parser.add_argument("--width", type=int, default=3840)
    parser.add_argument("--height", type=int, default=2160)
    parser.add_argument("--publish-fps", type=float, default=4.0)
    parser.add_argument("--full-max-width", type=int, default=1920)
    parser.add_argument("--jpeg-quality", type=int, default=75)
    parser.add_argument(
        "--focus-roi",
        type=float,
        nargs=4,
        default=(0.45, 0.35, 0.92, 0.96),
        metavar=("X1", "Y1", "X2", "Y2"),
    )
    parser.add_argument("--full-output", type=Path, default=Path("/tmp/frame.jpg"))
    parser.add_argument(
        "--crop-output", type=Path, default=Path("/tmp/focus_crop.jpg")
    )
    parser.add_argument(
        "--metrics-output", type=Path, default=Path("/tmp/focus_metrics.json")
    )
    args = parser.parse_args()

    if args.publish_fps <= 0:
        raise ValueError("--publish-fps must be positive")
    if args.width <= 0 or args.height <= 0:
        raise ValueError("capture dimensions must be positive")
    if not 1 <= args.jpeg_quality <= 100:
        raise ValueError("--jpeg-quality must be in the range 1-100")

    x1n, y1n, x2n, y2n = args.focus_roi
    if not (
        0.0 <= x1n < x2n <= 1.0
        and 0.0 <= y1n < y2n <= 1.0
    ):
        raise ValueError("--focus-roi must be normalized X1 Y1 X2 Y2 values")

    x1 = int(round(x1n * args.width))
    y1 = int(round(y1n * args.height))
    x2 = int(round(x2n * args.width))
    y2 = int(round(y2n * args.height))
    frame_size = args.width * args.height * 3 // 2
    command = [
        "v4l2-ctl",
        "-d",
        args.device,
        (
            "--set-fmt-video="
            f"width={args.width},height={args.height},pixelformat=NV12"
        ),
        "--stream-mmap=4",
        "--stream-to=-",
    ]

    print(
        f"Focus preview: device={args.device} "
        f"capture={args.width}x{args.height} NV12 "
        f"publish={args.publish_fps:.1f} FPS "
        f"roi=({x1},{y1})-({x2},{y2})",
        flush=True,
    )

    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    if process.stdout is None:
        raise RuntimeError("Cannot open v4l2-ctl output pipe")

    frame_index = 0
    next_publish = 0.0
    sharpness_ema: Optional[float] = None
    started = time.monotonic()

    try:
        while True:
            raw = read_exact(process.stdout, frame_size)
            if raw is None:
                code = process.poll()
                raise RuntimeError(
                    f"video capture stopped before a complete frame (exit={code})"
                )
            frame_index += 1

            now = time.monotonic()
            if now < next_publish:
                continue
            next_publish = now + 1.0 / args.publish_fps

            packed = np.frombuffer(raw, dtype=np.uint8).reshape(
                args.height * 3 // 2,
                args.width,
            )
            frame = cv2.cvtColor(packed, cv2.COLOR_YUV2BGR_NV12)
            crop = frame[y1:y2, x1:x2]
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            sharpness_ema = (
                sharpness
                if sharpness_ema is None
                else 0.82 * sharpness_ema + 0.18 * sharpness
            )

            annotated = frame.copy()
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 5)
            cv2.putText(
                annotated,
                (
                    f"FOCUS ROI  sharpness={sharpness:.1f} "
                    f"avg={sharpness_ema:.1f}  MAXIMIZE AVG"
                ),
                (40, 70),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.25,
                (0, 0, 255),
                3,
                cv2.LINE_AA,
            )

            full = annotated
            if args.full_max_width and args.width > args.full_max_width:
                display_height = int(
                    round(args.height * args.full_max_width / args.width)
                )
                full = cv2.resize(
                    annotated,
                    (args.full_max_width, display_height),
                    interpolation=cv2.INTER_AREA,
                )

            crop_annotated = crop.copy()
            cv2.putText(
                crop_annotated,
                f"native crop | sharpness avg={sharpness_ema:.1f}",
                (24, 48),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )

            atomic_write_bytes(
                args.full_output,
                encode_jpeg(full, args.jpeg_quality),
            )
            atomic_write_bytes(
                args.crop_output,
                encode_jpeg(crop_annotated, min(90, args.jpeg_quality + 10)),
            )
            atomic_write_json(
                args.metrics_output,
                {
                    "device": args.device,
                    "capture_width": args.width,
                    "capture_height": args.height,
                    "full_preview_width": int(full.shape[1]),
                    "full_preview_height": int(full.shape[0]),
                    "crop_width": int(crop.shape[1]),
                    "crop_height": int(crop.shape[0]),
                    "focus_roi_normalized": [x1n, y1n, x2n, y2n],
                    "frame_index": frame_index,
                    "sharpness": round(sharpness, 3),
                    "sharpness_average": round(sharpness_ema, 3),
                    "elapsed_seconds": round(now - started, 3),
                    "updated_unix": time.time(),
                },
            )
    except KeyboardInterrupt:
        print("Focus preview interrupted.", flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


if __name__ == "__main__":
    main()
