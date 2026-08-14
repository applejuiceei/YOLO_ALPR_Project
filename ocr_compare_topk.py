import argparse
import csv
from pathlib import Path
from typing import Any

import cv2

from topk_report import build_ocr_engine, find_latest_run, load_json


DEFAULT_BASE = r"D:\YOLO_ALPR_Project\captures_topk"


def try_engine(engine: str, track_dir: Path, candidate: dict[str, Any]) -> dict[str, Any]:
    result = {
        "engine": engine,
        "text": "",
        "confidence": "",
        "is_plate_like": "",
        "error": "",
        "source": "",
    }
    try:
        _ocr, recognize, is_plate_like, use_vehicle_first = build_ocr_engine(engine)
        file_order = ["vehicle", "plate"] if use_vehicle_first else ["plate"]
        for file_key in file_order:
            rel_path = candidate.get("files", {}).get(file_key)
            if not rel_path:
                continue
            image = cv2.imread(str(track_dir / rel_path))
            if image is None:
                continue
            text, confidence = recognize(image)
            if text:
                result["text"] = text
                result["confidence"] = confidence if confidence is not None else ""
                result["is_plate_like"] = bool(is_plate_like(text)) if is_plate_like else ""
                result["source"] = file_key
                break
    except Exception as exc:
        result["error"] = str(exc)
    return result


def build_rows(run_dir: Path, engines: list[str]) -> list[dict[str, Any]]:
    rows = []
    for track_dir in sorted(run_dir.glob("track_*"), key=lambda p: int(p.name.split("_")[-1])):
        summary_path = track_dir / "summary.json"
        if not summary_path.exists():
            continue
        summary = load_json(summary_path)
        for candidate in summary.get("candidates", []):
            for engine in engines:
                engine_result = try_engine(engine, track_dir, candidate)
                rows.append(
                    {
                        "track_id": summary.get("track_id"),
                        "rank": candidate.get("rank"),
                        "frame_idx": candidate.get("frame_idx"),
                        "score": candidate.get("score"),
                        "plate_path": str(track_dir / candidate.get("files", {}).get("plate", "")),
                        **engine_result,
                    }
                )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare OCR engines on saved Top-K plate candidates.")
    parser.add_argument("--run-dir", help="Run directory. Defaults to latest run under --base.")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument(
        "--engines",
        nargs="+",
        default=["hyperlpr3", "plate-rec-ort", "plate-rec-cv2"],
        choices=["plate-rec", "plate-rec-ort", "plate-rec-cv2", "hyperlpr3", "paddle"],
    )
    parser.add_argument("--output", default="ocr_compare.csv")
    args = parser.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else find_latest_run(Path(args.base))
    rows = build_rows(run_dir, args.engines)
    out_path = run_dir / args.output
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)
    print(f"OCR comparison written: {out_path}")


if __name__ == "__main__":
    main()
