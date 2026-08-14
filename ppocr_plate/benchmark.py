from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np

from .runtime import PlateCTCRecognizer, ctc_decode


PLATE_PATTERN = re.compile(r"^[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领警学港澳挂应急民航]{1}[A-Z][A-Z0-9挂学警港澳]{5,6}$")
HISTORICAL_REFERENCE = "historical_hyperlpr3_reference_not_ground_truth"


@dataclass(frozen=True)
class Sample:
    path: Path
    label: str | None = None
    label_source: str | None = None


def read_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot decode image: {path}")
    return image


def _labels_from_paddle(path: Path, data_root: Path) -> dict[Path, tuple[str, str]]:
    labels: dict[Path, tuple[str, str]] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not raw_line.strip():
            continue
        parts = raw_line.split("\t", 1)
        if len(parts) != 2:
            raise ValueError(f"{path}:{line_number}: expected image<TAB>label")
        labels[(data_root / parts[0]).resolve()] = (parts[1].strip(), str(path))
    return labels


def _reference_labels_from_run(input_run: Path) -> dict[Path, tuple[str, str]]:
    labels: dict[Path, tuple[str, str]] = {}
    for summary_path in input_run.glob("track_*/summary.json"):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for candidate in summary.get("candidates", []):
            plate_name = candidate.get("files", {}).get("plate")
            text = candidate.get("ocr", {}).get("text")
            if plate_name and text:
                labels[(summary_path.parent / plate_name).resolve()] = (
                    str(text),
                    HISTORICAL_REFERENCE,
                )
    return labels


def discover_samples(args: argparse.Namespace) -> list[Sample]:
    label_map: dict[Path, tuple[str, str]] = {}
    paths: list[Path] = []
    if args.input_run:
        input_run = args.input_run.resolve()
        paths.extend(sorted(input_run.glob("track_*/plate_rank*.jpg")))
        label_map.update(_reference_labels_from_run(input_run))
    if args.image_dir:
        root = args.image_dir.resolve()
        for pattern in ("*.jpg", "*.jpeg", "*.png", "*.bmp"):
            paths.extend(root.rglob(pattern))
    if args.labels:
        if not args.data_root:
            raise ValueError("--data-root is required with --labels")
        label_map.update(_labels_from_paddle(args.labels.resolve(), args.data_root.resolve()))
        if not paths:
            paths.extend(label_map)
    unique_paths = sorted({path.resolve() for path in paths})
    if not unique_paths:
        raise ValueError("no input images found")
    samples = []
    for path in unique_paths:
        label, source = label_map.get(path, (None, None))
        samples.append(Sample(path=path, label=label, label_source=source))
    return samples


def latency_stats(values: Iterable[float]) -> dict[str, float]:
    array = np.asarray(list(values), dtype=np.float64)
    if array.size == 0:
        return {key: 0.0 for key in ("min_ms", "mean_ms", "p50_ms", "p95_ms", "max_ms")}
    return {
        "min_ms": float(array.min()),
        "mean_ms": float(array.mean()),
        "p50_ms": float(np.percentile(array, 50)),
        "p95_ms": float(np.percentile(array, 95)),
        "max_ms": float(array.max()),
    }


def edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, 1):
        current = [left_index]
        for right_index, right_character in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_character != right_character),
                )
            )
        previous = current
    return previous[-1]


def quality_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labeled = [
        row
        for row in rows
        if row.get("label") and row.get("label_source") != HISTORICAL_REFERENCE
    ]
    references = [
        row
        for row in rows
        if row.get("label") and row.get("label_source") == HISTORICAL_REFERENCE
    ]
    if not labeled:
        exact_accuracy = None
        character_accuracy = None
    else:
        exact = sum(row["text"] == row["label"] for row in labeled)
        total_characters = sum(len(row["label"]) for row in labeled)
        errors = sum(edit_distance(row["label"], row["text"]) for row in labeled)
        exact_accuracy = exact / len(labeled)
        character_accuracy = max(0.0, 1.0 - errors / max(1, total_characters))
    return {
        "labeled_samples": len(labeled),
        "exact_accuracy": exact_accuracy,
        "character_accuracy": character_accuracy,
        "label_sources": sorted({row["label_source"] for row in labeled}),
        "historical_reference_samples": len(references),
        "historical_reference_exact_agreement": (
            sum(row["text"] == row["label"] for row in references) / len(references)
            if references
            else None
        ),
        "historical_reference_is_ground_truth": False,
    }


def execute_benchmark(
    recognizer: PlateCTCRecognizer,
    samples: list[Sample],
    warmup: int,
    iterations: int,
) -> tuple[list[dict[str, Any]], dict[str, list[float]]]:
    loaded: list[tuple[Sample, np.ndarray]] = [(sample, read_image(sample.path)) for sample in samples]
    for index in range(warmup):
        recognizer.recognize(loaded[index % len(loaded)][1])

    timings = {"preprocess": [], "inference": [], "decode": [], "total": []}
    latest: dict[Path, tuple[str, float]] = {}
    for index in range(iterations):
        sample, image = loaded[index % len(loaded)]
        total_start = time.perf_counter_ns()
        stage_start = total_start
        tensor = recognizer.prepare(image)
        inference_start = time.perf_counter_ns()
        scores = recognizer.infer_scores(tensor)
        decode_start = time.perf_counter_ns()
        text, confidence = ctc_decode(scores, recognizer.characters)
        end = time.perf_counter_ns()
        timings["preprocess"].append((inference_start - stage_start) / 1e6)
        timings["inference"].append((decode_start - inference_start) / 1e6)
        timings["decode"].append((end - decode_start) / 1e6)
        timings["total"].append((end - total_start) / 1e6)
        latest[sample.path] = (text, confidence)

    rows = []
    for sample, _ in loaded:
        text, confidence = latest.get(sample.path, ("", 0.0))
        rows.append(
            {
                "image": str(sample.path),
                "label": sample.label,
                "label_source": sample.label_source,
                "text": text,
                "confidence": confidence,
                "valid_plate_format": bool(PLATE_PATTERN.fullmatch(text)),
                "exact_match": text == sample.label if sample.label else None,
                "label_is_ground_truth": bool(
                    sample.label and sample.label_source != HISTORICAL_REFERENCE
                ),
            }
        )
    return rows, timings


def write_results(
    output_root: Path,
    recognizer: PlateCTCRecognizer,
    rows: list[dict[str, Any]],
    timings: dict[str, list[float]],
    args: argparse.Namespace,
) -> tuple[Path, dict[str, Any]]:
    run_dir = output_root.resolve() / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=False)
    stage_stats = {name: latency_stats(values) for name, values in timings.items()}
    quality = quality_stats(rows)
    result = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "engine": "onnxruntime",
        "model": recognizer.metadata(),
        "warmup": args.warmup,
        "iterations": args.iterations,
        "sample_count": len(rows),
        "latency": stage_stats,
        "quality": quality,
        "gates": {
            "p50_under_20ms": stage_stats["total"]["p50_ms"] < 20.0,
            "p95_under_20ms": stage_stats["total"]["p95_ms"] < 20.0,
            "exact_accuracy_at_least_98pct": (
                quality["exact_accuracy"] is not None and quality["exact_accuracy"] >= 0.98
            ),
            "character_accuracy_at_least_99_5pct": (
                quality["character_accuracy"] is not None
                and quality["character_accuracy"] >= 0.995
            ),
        },
        "samples": rows,
    }
    (run_dir / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (run_dir / "results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (run_dir / "latencies.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["iteration", "preprocess_ms", "inference_ms", "decode_ms", "total_ms"])
        for index in range(len(timings["total"])):
            writer.writerow([index] + [timings[name][index] for name in ("preprocess", "inference", "decode", "total")])
    return run_dir, result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark a fixed-shape CTC ONNX plate recognizer.")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--dictionary", type=Path, required=True)
    parser.add_argument("--input-run", type=Path)
    parser.add_argument("--image-dir", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path, default=Path("runs_ppocr_plate"))
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--color-order", choices=("bgr", "rgb"), default="rgb")
    parser.add_argument("--use-space-char", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.warmup < 0 or args.iterations < 1:
        raise ValueError("--warmup must be >= 0 and --iterations must be >= 1")
    samples = discover_samples(args)
    recognizer = PlateCTCRecognizer(
        args.model,
        args.dictionary,
        color_order=args.color_order,
        use_space_char=args.use_space_char,
        threads=args.threads,
    )
    rows, timings = execute_benchmark(recognizer, samples, args.warmup, args.iterations)
    run_dir, result = write_results(args.output, recognizer, rows, timings, args)
    print(json.dumps({"run": str(run_dir), **result["latency"]["total"], **result["quality"], "gates": result["gates"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
