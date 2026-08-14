"""Collect RK3588 MIPI/ISP diagnostics and optional frame probes.

Run this on the RK3588 board. The script is read-only except for writing the
diagnostic output directory.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


def run_command(command: list[str]) -> dict[str, object]:
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=12, check=False)
        return {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except FileNotFoundError as exc:
        return {"command": command, "error": f"not found: {exc.filename}"}
    except subprocess.TimeoutExpired as exc:
        return {"command": command, "error": f"timeout after {exc.timeout}s"}


def decode_frame(raw: bytes, width: int, height: int, fourcc: str) -> np.ndarray | None:
    data = np.frombuffer(raw, dtype=np.uint8)
    if fourcc == "UYVY":
        expected = width * height * 2
        if data.size < expected:
            return None
        packed = data[:expected].reshape(height, width, 2)
        return cv2.cvtColor(packed, cv2.COLOR_YUV2BGR_UYVY)
    if fourcc == "NV12":
        expected = width * height * 3 // 2
        if data.size < expected:
            return None
        packed = data[:expected].reshape(height * 3 // 2, width)
        return cv2.cvtColor(packed, cv2.COLOR_YUV2BGR_NV12)
    if fourcc == "NV21":
        expected = width * height * 3 // 2
        if data.size < expected:
            return None
        packed = data[:expected].reshape(height * 3 // 2, width)
        return cv2.cvtColor(packed, cv2.COLOR_YUV2BGR_NV21)
    return None


def gray_world_white_balance(frame: np.ndarray) -> np.ndarray:
    image = frame.astype(np.float32)
    means = image.reshape(-1, 3).mean(axis=0)
    gray = float(means.mean())
    scale = gray / np.maximum(means, 1.0)
    return np.clip(image * scale.reshape(1, 1, 3), 0, 255).astype(np.uint8)


def capture_one(device: str, width: int, height: int, fourcc: str) -> bytes:
    frame_size = width * height * 2 if fourcc == "UYVY" else width * height * 3 // 2
    command = [
        "v4l2-ctl",
        "-d",
        device,
        f"--set-fmt-video=width={width},height={height},pixelformat={fourcc}",
        "--stream-mmap=4",
        "--stream-count=1",
        "--stream-to=-",
    ]
    result = subprocess.run(command, capture_output=True, timeout=12, check=False)
    return result.stdout[:frame_size]


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect RK3588 MIPI/ISP diagnostics and frame samples.")
    parser.add_argument("--device", default="/dev/video22")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fourcc", choices=("UYVY", "NV12", "NV21"), default="UYVY")
    parser.add_argument("--output", type=Path, default=Path("mipi_isp_probe"))
    parser.add_argument("--capture", action="store_true", help="Capture one raw frame and decoded JPEG samples.")
    args = parser.parse_args()

    run_dir = args.output / f"probe_{datetime.now():%Y%m%d_%H%M%S}"
    run_dir.mkdir(parents=True, exist_ok=False)

    commands = [
        ["uname", "-a"],
        ["ps", "aux"],
        ["media-ctl", "-p"],
        ["v4l2-ctl", "-d", args.device, "--all"],
        ["v4l2-ctl", "-d", args.device, "--list-formats-ext"],
        ["ls", "-l", "/dev/video0", "/dev/video1", "/dev/video2", "/dev/video22"],
    ]
    results = [run_command(command) for command in commands]
    (run_dir / "diagnostics.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for index, result in enumerate(results, 1):
        name = "_".join(str(part).replace("/", "_") for part in result["command"][:2]) if "command" in result else f"result_{index}"
        (run_dir / f"{index:02d}_{name}.txt").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if args.capture:
        raw = capture_one(args.device, args.width, args.height, args.fourcc)
        (run_dir / f"frame_{args.fourcc.lower()}.raw").write_bytes(raw)
        decoded = decode_frame(raw, args.width, args.height, args.fourcc)
        if decoded is not None:
            cv2.imwrite(str(run_dir / "decoded.jpg"), decoded, [cv2.IMWRITE_JPEG_QUALITY, 95])
            cv2.imwrite(str(run_dir / "decoded_grayworld.jpg"), gray_world_white_balance(decoded), [cv2.IMWRITE_JPEG_QUALITY, 95])

    print(f"Saved MIPI/ISP probe: {run_dir}")


if __name__ == "__main__":
    main()
