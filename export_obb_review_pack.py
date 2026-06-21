"""Export accepted and rejected ALPR candidates as a manual OBB review pack."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import cv2


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_BASE = PROJECT_DIR / "captures_topk"
DEFAULT_OUTPUT = PROJECT_DIR / "Dataset" / "obb_hardcase_review"


def find_latest_run(base: Path) -> Path:
    runs = sorted((path for path in base.glob("run_*") if path.is_dir()), key=lambda path: path.stat().st_mtime, reverse=True)
    if not runs:
        raise FileNotFoundError(f"No run directories under {base}")
    return runs[0]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def export_item(
    review_root: Path,
    track_dir: Path,
    track_id: int,
    item: dict[str, Any],
    source: str,
    copied_frames: set[str],
) -> dict[str, Any] | None:
    files = item.get("files", {})
    full_path = track_dir / files.get("full", "")
    if not full_path.exists():
        return None
    frame_idx = int(item.get("frame_idx", -1))
    image_name = f"track{track_id}_frame{frame_idx}.jpg"
    target_image = review_root / "images" / image_name
    if image_name not in copied_frames:
        shutil.copy2(full_path, target_image)
        copied_frames.add(image_name)
    image = cv2.imread(str(target_image))
    if image is None:
        return None
    height, width = image.shape[:2]
    return {
        "image": f"images/{image_name}",
        "label": f"labels/{Path(image_name).stem}.txt",
        "track_id": track_id,
        "frame_idx": frame_idx,
        "source": source,
        "reason": item.get("reason", ""),
        "suggested_corners_xy": item.get("plate_corners_xy", []),
        "image_width": width,
        "image_height": height,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export ALPR candidates into an OBB manual-review pack.")
    parser.add_argument("--run-dir", type=Path, help="Top-K run directory. Defaults to latest run.")
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--include-accepted", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-rejected", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir or find_latest_run(args.base)
    if args.clean and args.output.exists():
        shutil.rmtree(args.output)
    (args.output / "images").mkdir(parents=True, exist_ok=True)
    (args.output / "labels").mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    copied_frames: set[str] = set()
    for track_dir in sorted(run_dir.glob("track_*"), key=lambda path: int(path.name.split("_")[-1])):
        summary_path = track_dir / "summary.json"
        if not summary_path.exists():
            continue
        summary = load_json(summary_path)
        track_id = int(summary["track_id"])
        if args.include_accepted:
            for item in summary.get("candidates", []):
                record = export_item(args.output, track_dir, track_id, item, "accepted_suggestion", copied_frames)
                if record:
                    records.append(record)
        if args.include_rejected:
            for item in summary.get("rejected_candidates", []):
                record = export_item(args.output, track_dir, track_id, item, "rejected_suggestion", copied_frames)
                if record:
                    records.append(record)

    manifest = {"source_run": str(run_dir), "records": records}
    manifest_path = args.output / "review_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported {len(records)} review records to: {args.output}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
