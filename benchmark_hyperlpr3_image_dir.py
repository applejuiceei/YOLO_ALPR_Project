from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np

from benchmark_hyperlpr3_recognition import (
    clean_result,
    create_unique_run_dir,
    read_image,
    resolve_hyperlpr3_recognition_model,
    timing_summary,
)
from hyperlpr3_ocr import HyperLPR3OCR
from plate_rec_ocr import PlateRecONNX


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = PROJECT_DIR / "Dataset" / "dataset" / "test" / "sharp"
DEFAULT_OUTPUT_ROOT = PROJECT_DIR / "runs_hyperlpr3_image_dir"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark the complete HyperLPR3 API and its recognition-only ONNX "
            "module on a directory of pre-cropped plate images. Disk I/O is excluded."
        )
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="Measured calls per decoded image (default: 1).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Use at most this many sorted images; 0 means all images.",
    )
    parser.add_argument("--recursive", action="store_true")
    args = parser.parse_args()
    if args.warmup < 0:
        parser.error("--warmup must be >= 0")
    if args.repeats <= 0:
        parser.error("--repeats must be > 0")
    if args.limit < 0:
        parser.error("--limit must be >= 0")
    return args


def discover_images(root: Path, recursive: bool, limit: int) -> list[Path]:
    if not root.is_dir():
        raise FileNotFoundError(f"input directory not found: {root}")
    candidates = root.rglob("*") if recursive else root.glob("*")
    images = sorted(
        (path for path in candidates if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES),
        key=lambda path: path.as_posix().lower(),
    )
    return images[:limit] if limit else images


def preload_images(paths: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    loaded: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in paths:
        try:
            image = read_image(path)
            loaded.append(
                {
                    "path": path.resolve(),
                    "image": image,
                    "width": int(image.shape[1]),
                    "height": int(image.shape[0]),
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "image": str(path.resolve()),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return loaded, errors


def measured_call(call: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter_ns()
    result = call()
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    return result, elapsed_ms


def recognition_only_call(recognizer: Any, image: np.ndarray) -> tuple[tuple[Any, Any], dict[str, float]]:
    total_started = time.perf_counter_ns()

    started = time.perf_counter_ns()
    tensor = recognizer._preprocess(image)
    preprocess_ms = (time.perf_counter_ns() - started) / 1_000_000.0

    started = time.perf_counter_ns()
    raw_output = recognizer._run_session(tensor)
    inference_ms = (time.perf_counter_ns() - started) / 1_000_000.0

    started = time.perf_counter_ns()
    decoded = recognizer._postprocess(raw_output)
    decode_ms = (time.perf_counter_ns() - started) / 1_000_000.0

    total_ms = (time.perf_counter_ns() - total_started) / 1_000_000.0
    return decoded, {
        "preprocess_ms": preprocess_ms,
        "inference_ms": inference_ms,
        "decode_ms": decode_ms,
        "total_ms": total_ms,
    }


def result_fields(result: tuple[Any, Any]) -> dict[str, Any]:
    text, confidence = clean_result(result)
    return {
        "text": text,
        "confidence": round(float(confidence), 8) if confidence is not None else None,
        "plate_like": bool(text and PlateRecONNX.is_plate_like(text)),
    }


def warm_up(
    loaded: list[dict[str, Any]],
    count: int,
    call: Callable[[np.ndarray], Any],
    label: str,
) -> None:
    for index in range(count):
        try:
            call(loaded[index % len(loaded)]["image"])
        except Exception as exc:
            raise RuntimeError(
                f"warm-up failed for {label} at call {index + 1}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc


def benchmark_full(
    engine: HyperLPR3OCR,
    loaded: list[dict[str, Any]],
    repeats: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    total = len(loaded) * repeats
    completed = 0
    for repeat in range(1, repeats + 1):
        for item in loaded:
            record: dict[str, Any] = {
                "arm": "full_interface",
                "image": str(item["path"]),
                "repeat": repeat,
                "preprocess_ms": None,
                "inference_ms": None,
                "decode_ms": None,
                "total_ms": None,
                "text": None,
                "confidence": None,
                "plate_like": False,
                "error": None,
            }
            try:
                result, elapsed_ms = measured_call(lambda: engine.recognize(item["image"]))
                record.update(result_fields(result))
                record["total_ms"] = elapsed_ms
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
            records.append(record)
            completed += 1
            if completed % 100 == 0 or completed == total:
                print(f"[full] {completed}/{total}", flush=True)
    return records


def benchmark_recognition_only(
    recognizer: Any,
    loaded: list[dict[str, Any]],
    repeats: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    total = len(loaded) * repeats
    completed = 0
    for repeat in range(1, repeats + 1):
        for item in loaded:
            record: dict[str, Any] = {
                "arm": "recognition_only",
                "image": str(item["path"]),
                "repeat": repeat,
                "preprocess_ms": None,
                "inference_ms": None,
                "decode_ms": None,
                "total_ms": None,
                "text": None,
                "confidence": None,
                "plate_like": False,
                "error": None,
            }
            try:
                result, stages = recognition_only_call(recognizer, item["image"])
                record.update(result_fields(result))
                record.update(stages)
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
            records.append(record)
            completed += 1
            if completed % 100 == 0 or completed == total:
                print(f"[recognition-only] {completed}/{total}", flush=True)
    return records


def summarize_records(records: list[dict[str, Any]], stage_names: tuple[str, ...]) -> dict[str, Any]:
    successful = [record for record in records if record["error"] is None]
    nonempty = [record for record in successful if record["text"]]
    plate_like = [record for record in successful if record["plate_like"]]
    confidences = [
        float(record["confidence"])
        for record in nonempty
        if record["confidence"] is not None
    ]
    text_counts = Counter(record["text"] for record in nonempty)
    return {
        "calls": len(records),
        "successful_calls": len(successful),
        "errors": len(records) - len(successful),
        "nonempty_outputs": len(nonempty),
        "nonempty_rate": len(nonempty) / len(successful) if successful else None,
        "plate_like_outputs": len(plate_like),
        "plate_like_rate": len(plate_like) / len(successful) if successful else None,
        "mean_confidence_nonempty": statistics.fmean(confidences) if confidences else None,
        "most_common_outputs": text_counts.most_common(10),
        "timings_ms": {
            stage: timing_summary(
                [float(record[stage]) for record in successful if record[stage] is not None]
            )
            for stage in stage_names
        },
    }


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    columns = (
        "arm",
        "image",
        "repeat",
        "text",
        "confidence",
        "plate_like",
        "preprocess_ms",
        "inference_ms",
        "decode_ms",
        "total_ms",
        "error",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: record.get(column) for column in columns} for record in records)


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    paths = discover_images(input_dir, args.recursive, args.limit)
    if not paths:
        raise RuntimeError(f"no supported images found: {input_dir}")

    print(f"Preloading {len(paths)} image(s); disk I/O is excluded from timing...", flush=True)
    loaded, decode_errors = preload_images(paths)
    if not loaded:
        raise RuntimeError("none of the discovered images could be decoded")
    output_dir = create_unique_run_dir(args.output.resolve())

    import hyperlpr3
    import onnxruntime as ort
    from hyperlpr3.inference.recognition import PPRCNNRecognitionORT

    ort.set_default_logger_severity(3)
    model_path = resolve_hyperlpr3_recognition_model()

    started = time.perf_counter_ns()
    full_engine = HyperLPR3OCR()
    full_init_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    full_cold_result, full_cold_ms = measured_call(
        lambda: full_engine.recognize(loaded[0]["image"])
    )

    started = time.perf_counter_ns()
    recognizer = PPRCNNRecognitionORT(str(model_path), input_size=(48, 160))
    recognition_init_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    recognition_cold_result, recognition_cold_stages = recognition_only_call(
        recognizer, loaded[0]["image"]
    )

    print(f"Warming up each arm {args.warmup} time(s)...", flush=True)
    warm_up(loaded, args.warmup, full_engine.recognize, "full-interface")
    warm_up(loaded, args.warmup, recognizer, "recognition-only")

    full_records = benchmark_full(full_engine, loaded, args.repeats)
    recognition_records = benchmark_recognition_only(recognizer, loaded, args.repeats)
    all_records = full_records + recognition_records

    full_summary = summarize_records(full_records, ("total_ms",))
    recognition_summary = summarize_records(
        recognition_records,
        ("preprocess_ms", "inference_ms", "decode_ms", "total_ms"),
    )
    rec_total = recognition_summary["timings_ms"]["total_ms"]
    shape_counts = Counter(
        f"{item['width']}x{item['height']}" for item in loaded
    )
    payload = {
        "metadata": {
            "created_at": datetime.now().astimezone().isoformat(),
            "input_dir": str(input_dir),
            "output_dir": str(output_dir),
            "discovered_images": len(paths),
            "decoded_images": len(loaded),
            "decode_errors": decode_errors,
            "shape_counts": dict(shape_counts),
            "warmup_per_arm": args.warmup,
            "repeats_per_image": args.repeats,
            "disk_io_in_timing": False,
            "batch_size": 1,
            "concurrency": 1,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "logical_cpu_count": os.cpu_count(),
            "hyperlpr3_package": str(Path(hyperlpr3.__file__).resolve()),
            "recognition_model": str(model_path),
            "recognition_input_shape": list(recognizer.input_config.shape),
            "recognition_output_shape": list(recognizer.output_config.shape),
            "onnxruntime_version": ort.__version__,
            "onnxruntime_available_providers": ort.get_available_providers(),
            "quality_policy": (
                "The directory has no manually verified labels. Output/format rates are "
                "diagnostics only and are not recognition accuracy."
            ),
        },
        "initialization_ms": {
            "full_interface": full_init_ms,
            "recognition_only": recognition_init_ms,
        },
        "cold_calls": {
            "image": str(loaded[0]["path"]),
            "full_interface": {
                **result_fields(full_cold_result),
                "total_ms": full_cold_ms,
            },
            "recognition_only": {
                **result_fields(recognition_cold_result),
                **recognition_cold_stages,
            },
        },
        "full_interface": full_summary,
        "recognition_only": recognition_summary,
        "gates": {
            "recognition_only_p50_under_20ms": bool(
                rec_total["p50"] is not None and float(rec_total["p50"]) < 20.0
            ),
            "recognition_only_p95_under_20ms": bool(
                rec_total["p95"] is not None and float(rec_total["p95"]) < 20.0
            ),
        },
        "records": all_records,
    }

    results_path = output_dir / "results.json"
    csv_path = output_dir / "latencies.csv"
    results_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    write_csv(csv_path, all_records)

    print(json.dumps({
        "output": str(output_dir),
        "full_interface": full_summary,
        "recognition_only": recognition_summary,
        "gates": payload["gates"],
        "cold_calls": payload["cold_calls"],
    }, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
