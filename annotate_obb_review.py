"""Minimal OpenCV tool for reviewing one license-plate OBB per exported frame."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_REVIEW_ROOT = PROJECT_DIR / "Dataset" / "obb_hardcase_review"
WINDOW_NAME = "OBB Review"


def load_manifest(review_root: Path) -> list[dict[str, Any]]:
    data = json.loads((review_root / "review_manifest.json").read_text(encoding="utf-8"))
    unique: dict[str, dict[str, Any]] = {}
    for record in data.get("records", []):
        unique.setdefault(record["image"], record)
    return list(unique.values())


def read_label(label_path: Path, width: int, height: int) -> list[tuple[float, float]]:
    if not label_path.exists():
        return []
    values = label_path.read_text(encoding="utf-8").strip().split()
    if len(values) != 9:
        return []
    coords = [float(value) for value in values[1:]]
    return [(coords[index] * width, coords[index + 1] * height) for index in range(0, 8, 2)]


def write_label(label_path: Path, points: list[tuple[float, float]], width: int, height: int) -> None:
    values = " ".join(f"{coordinate:.6f}" for x, y in points for coordinate in (x / width, y / height))
    label_path.write_text(f"0 {values}\n", encoding="utf-8")


def draw_view(image: np.ndarray, points: list[tuple[float, float]], scale: float, record: dict[str, Any]) -> np.ndarray:
    view = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale != 1.0 else image.copy()
    scaled = [(int(x * scale), int(y * scale)) for x, y in points]
    if scaled:
        for index, point in enumerate(scaled):
            cv2.circle(view, point, 5, (0, 255, 255), -1)
            cv2.putText(view, str(index + 1), (point[0] + 6, point[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        if len(scaled) >= 2:
            cv2.polylines(view, [np.array(scaled, dtype=np.int32)], len(scaled) == 4, (0, 255, 0), 2)
    header = f"track={record.get('track_id')} frame={record.get('frame_idx')} source={record.get('source')}"
    cv2.putText(view, header, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
    cv2.putText(view, "click 4 corners | a accept suggestion | s save | r clear | u undo | n skip | q quit", (12, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1)
    return view


def main() -> None:
    parser = argparse.ArgumentParser(description="Review and label OBB hard cases exported from a Top-K run.")
    parser.add_argument("--review-root", type=Path, default=DEFAULT_REVIEW_ROOT)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--display-width", type=int, default=1280)
    parser.add_argument("--display-height", type=int, default=800)
    args = parser.parse_args()

    records = load_manifest(args.review_root)
    if not records:
        raise RuntimeError("No review records found.")
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    skipped_dir = args.review_root / "skipped"
    skipped_dir.mkdir(parents=True, exist_ok=True)
    index = max(0, min(args.start, len(records) - 1))
    points: list[tuple[float, float]] = []

    while 0 <= index < len(records):
        record = records[index]
        image_path = args.review_root / record["image"]
        label_path = args.review_root / record["label"]
        skipped_path = skipped_dir / f"{image_path.stem}.skip"
        image = cv2.imread(str(image_path))
        if image is None:
            index += 1
            continue
        height, width = image.shape[:2]
        scale = min(1.0, args.display_width / width, args.display_height / height)
        existing = read_label(label_path, width, height)
        if existing:
            points = existing
        else:
            points = []

        def on_mouse(event: int, x: int, y: int, _flags: int, _userdata: Any) -> None:
            nonlocal points
            if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
                points.append((x / scale, y / scale))

        cv2.setMouseCallback(WINDOW_NAME, on_mouse)
        while True:
            view = draw_view(image, points, scale, record)
            cv2.imshow(WINDOW_NAME, view)
            key = cv2.waitKey(30) & 0xFF
            if key in (ord("q"), 27):
                cv2.destroyAllWindows()
                return
            if key == ord("a"):
                suggested = record.get("suggested_corners_xy", [])
                if len(suggested) == 4:
                    points = [(float(point[0]), float(point[1])) for point in suggested]
            elif key == ord("r"):
                points = []
            elif key == ord("u") and points:
                points.pop()
            elif key == ord("n"):
                if label_path.exists():
                    label_path.unlink()
                skipped_path.write_text("no visible plate", encoding="utf-8")
                index += 1
                break
            elif key == ord("s"):
                if len(points) == 4:
                    write_label(label_path, points, width, height)
                    if skipped_path.exists():
                        skipped_path.unlink()
                    index += 1
                    break
            elif key == ord("p"):
                index = max(0, index - 1)
                break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
