from __future__ import annotations

import argparse
import csv
import json
import math
import site
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


PROJECT_DIR = Path(__file__).resolve().parent
LOCAL_OCR_DEPS_DIR = PROJECT_DIR / "python_deps_ocr"
if LOCAL_OCR_DEPS_DIR.exists():
    site.addsitedir(str(LOCAL_OCR_DEPS_DIR))

import cv2
import numpy as np

from hyperlpr3_ocr import HyperLPR3OCR
from plate_rec_ocr import PlateRecONNX


DEFAULT_INPUT_RUN = (
    PROJECT_DIR
    / "captures_topk_codex_win_20260708"
    / "run_20260708_131529"
)
DEFAULT_OUTPUT_ROOT = PROJECT_DIR / "runs_hyperlpr3_recognition_ab"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare full HyperLPR3 with its recognition-only module on paired "
            "vehicle_rank/plate_rank images. Existing run data is read-only."
        )
    )
    parser.add_argument(
        "--input-run",
        type=Path,
        default=DEFAULT_INPUT_RUN,
        help=f"Top-K run containing track_* folders (default: {DEFAULT_INPUT_RUN})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=(
            "Output root. A new run_YYYYMMDD_HHMMSS directory is always created "
            f"inside it (default: {DEFAULT_OUTPUT_ROOT})."
        ),
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=20,
        help="Warm-up calls for each of the three benchmark arms (default: 20).",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=10,
        help="Measured calls per sample and benchmark arm (default: 10).",
    )
    args = parser.parse_args()
    if args.warmup < 0:
        parser.error("--warmup must be >= 0")
    if args.repeats <= 0:
        parser.error("--repeats must be > 0")
    return args


def create_unique_run_dir(output_root: Path) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    stem = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    candidate = output_root / stem
    suffix = 1
    while candidate.exists():
        candidate = output_root / f"{stem}_{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=False, exist_ok=False)
    return candidate


def read_image(path: Path) -> np.ndarray:
    if not path.is_file():
        raise FileNotFoundError(f"image not found: {path}")
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError(f"cannot decode image: {path}")
    return image


def finite_float(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def clean_result(result: tuple[Any, Any]) -> tuple[str | None, float | None]:
    text, confidence = result
    cleaned = PlateRecONNX.clean_plate_text(str(text)) if text else ""
    return (cleaned or None), finite_float(confidence)


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def timing_summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "mean": None,
            "p50": None,
            "p95": None,
            "max": None,
        }
    return {
        "count": len(values),
        "min": round(min(values), 3),
        "mean": round(statistics.fmean(values), 3),
        "p50": round(percentile(values, 50.0) or 0.0, 3),
        "p95": round(percentile(values, 95.0) or 0.0, 3),
        "max": round(max(values), 3),
    }


def representative_result(
    results: list[tuple[str | None, float | None]],
) -> tuple[str | None, float | None, bool]:
    if not results:
        return None, None, False
    counts = Counter(text for text, _confidence in results)
    text = counts.most_common(1)[0][0]
    confidences = [
        confidence
        for candidate, confidence in results
        if candidate == text and confidence is not None
    ]
    confidence = statistics.fmean(confidences) if confidences else None
    return text, confidence, len(counts) == 1


def arm_payload(
    results: list[tuple[str | None, float | None]],
    timings: dict[str, list[float]],
    error: str | None,
) -> dict[str, Any]:
    text, confidence, stable = representative_result(results)
    return {
        "text": text,
        "confidence": round(confidence, 6) if confidence is not None else None,
        "plate_like": bool(text and PlateRecONNX.is_plate_like(text)),
        "stable_across_repeats": stable,
        "error": error,
        "timings_ms": {
            name: {
                "values": [round(value, 3) for value in values],
                "summary": timing_summary(values),
            }
            for name, values in timings.items()
        },
    }


def benchmark_full(
    recognize: Callable[[np.ndarray], tuple[str | None, float | None]],
    image: np.ndarray,
    repeats: int,
) -> dict[str, Any]:
    results: list[tuple[str | None, float | None]] = []
    total_ms: list[float] = []
    error = None
    for repeat_index in range(repeats):
        try:
            started = time.perf_counter()
            result = clean_result(recognize(image))
            total_ms.append((time.perf_counter() - started) * 1000.0)
            results.append(result)
        except Exception as exc:  # Continue with the remaining dataset, but report this arm.
            error = f"repeat {repeat_index + 1}: {type(exc).__name__}: {exc}"
            break
    return arm_payload(results, {"total": total_ms}, error)


def benchmark_recognition_only(
    recognizer: Any,
    image: np.ndarray,
    repeats: int,
) -> dict[str, Any]:
    results: list[tuple[str | None, float | None]] = []
    stage_values: dict[str, list[float]] = {
        "preprocess": [],
        "inference": [],
        "decode": [],
        "total": [],
    }
    error = None
    for repeat_index in range(repeats):
        try:
            total_started = time.perf_counter()

            started = time.perf_counter()
            input_tensor = recognizer._preprocess(image)
            stage_values["preprocess"].append((time.perf_counter() - started) * 1000.0)

            started = time.perf_counter()
            raw_output = recognizer._run_session(input_tensor)
            stage_values["inference"].append((time.perf_counter() - started) * 1000.0)

            started = time.perf_counter()
            decoded = recognizer._postprocess(raw_output)
            stage_values["decode"].append((time.perf_counter() - started) * 1000.0)

            stage_values["total"].append((time.perf_counter() - total_started) * 1000.0)
            results.append(clean_result(decoded))
        except Exception as exc:  # Internal API failures must be visible in the result files.
            error = f"repeat {repeat_index + 1}: {type(exc).__name__}: {exc}"
            break
    return arm_payload(results, stage_values, error)


def warm_up(call: Callable[[], Any], count: int, label: str) -> None:
    for index in range(count):
        try:
            call()
        except Exception as exc:
            raise RuntimeError(
                f"warm-up failed for {label} at call {index + 1}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc


def load_reference(track_dir: Path, plate_name: str, rank: int) -> dict[str, Any]:
    summary_path = track_dir / "summary.json"
    if not summary_path.is_file():
        return {"text": None, "confidence": None, "source": None, "error": "summary.json missing"}
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        for candidate in summary.get("candidates", []):
            files = candidate.get("files") or {}
            if files.get("plate") == plate_name or int(candidate.get("rank", -1)) == rank:
                ocr = candidate.get("ocr") or {}
                text = ocr.get("text")
                return {
                    "text": PlateRecONNX.clean_plate_text(str(text)) if text else None,
                    "confidence": finite_float(ocr.get("confidence")),
                    "source": "summary.json candidate OCR; reference only, not ground truth",
                    "error": None,
                }
        return {
            "text": None,
            "confidence": None,
            "source": None,
            "error": f"candidate for {plate_name} not found in summary.json",
        }
    except Exception as exc:
        return {
            "text": None,
            "confidence": None,
            "source": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def discover_samples(input_run: Path) -> list[dict[str, Any]]:
    if not input_run.is_dir():
        raise FileNotFoundError(f"input run not found: {input_run}")
    samples: list[dict[str, Any]] = []
    for track_dir in sorted(input_run.glob("track_*"), key=lambda path: path.name):
        try:
            track_id = int(track_dir.name.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        plate_paths = sorted(
            track_dir.glob("plate_rank*.jpg"),
            key=lambda path: int(path.stem.removeprefix("plate_rank")),
        )
        for plate_path in plate_paths:
            rank = int(plate_path.stem.removeprefix("plate_rank"))
            vehicle_path = track_dir / f"vehicle_rank{rank}.jpg"
            samples.append(
                {
                    "track_id": track_id,
                    "rank": rank,
                    "track_dir": track_dir,
                    "vehicle_path": vehicle_path,
                    "plate_path": plate_path,
                    "reference": load_reference(track_dir, plate_path.name, rank),
                }
            )
    return samples


def resolve_hyperlpr3_recognition_model() -> Path:
    from hyperlpr3.config.settings import _DEFAULT_FOLDER_, onnx_runtime_config

    model_path = (Path(_DEFAULT_FOLDER_) / onnx_runtime_config["rec_model_path"]).resolve()
    if not model_path.is_file():
        raise FileNotFoundError(f"HyperLPR3 recognition model not found: {model_path}")
    return model_path


def flatten_timings(sample: dict[str, Any], arm_name: str, row: dict[str, Any]) -> None:
    arm = sample[arm_name]
    row[f"{arm_name}_text"] = arm["text"]
    row[f"{arm_name}_confidence"] = arm["confidence"]
    row[f"{arm_name}_plate_like"] = arm["plate_like"]
    row[f"{arm_name}_stable"] = arm["stable_across_repeats"]
    row[f"{arm_name}_error"] = arm["error"]
    for stage, values in arm["timings_ms"].items():
        summary = values["summary"]
        for metric in ("min", "mean", "p50", "p95", "max"):
            row[f"{arm_name}_{stage}_{metric}_ms"] = summary[metric]


def write_csv(path: Path, samples: list[dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    for sample in samples:
        reference = sample["reference"]
        row: dict[str, Any] = {
            "track_id": sample["track_id"],
            "rank": sample["rank"],
            "vehicle_path": sample["vehicle_path"],
            "plate_path": sample["plate_path"],
            "reference_text": reference["text"],
            "reference_confidence": reference["confidence"],
            "reference_note": reference["source"],
            "reference_error": reference["error"],
            "sample_error": sample["sample_error"],
            "double_line_status": sample["double_line_status"],
            "rec_vs_full_vehicle": sample["agreement"]["rec_vs_full_vehicle"],
            "rec_vs_full_plate": sample["agreement"]["rec_vs_full_plate"],
            "rec_vs_reference": sample["agreement"]["rec_vs_reference"],
            "confidence_rec_minus_full_vehicle": sample["agreement"][
                "rec_minus_full_vehicle"
            ],
            "confidence_rec_minus_full_plate": sample["agreement"]["rec_minus_full_plate"],
            "confidence_rec_minus_summary_reference": sample["agreement"][
                "rec_minus_summary_reference"
            ],
        }
        for arm_name in ("full_vehicle", "full_plate", "recognition_only"):
            flatten_timings(sample, arm_name, row)
        rows.append(row)

    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def aggregate_timing(
    samples: list[dict[str, Any]], arm_name: str, stage: str
) -> dict[str, float | int | None]:
    values: list[float] = []
    for sample in samples:
        values.extend(
            float(value)
            for value in sample[arm_name]["timings_ms"].get(stage, {}).get("values", [])
        )
    return timing_summary(values)


def ratio(numerator: Any, denominator: Any) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return round(float(numerator) / float(denominator), 3)


def difference(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    return round(float(left) - float(right), 6)


def build_aggregate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    timing = {
        "full_vehicle_total_ms": aggregate_timing(samples, "full_vehicle", "total"),
        "full_plate_total_ms": aggregate_timing(samples, "full_plate", "total"),
        "recognition_only_preprocess_ms": aggregate_timing(
            samples, "recognition_only", "preprocess"
        ),
        "recognition_only_inference_ms": aggregate_timing(
            samples, "recognition_only", "inference"
        ),
        "recognition_only_decode_ms": aggregate_timing(
            samples, "recognition_only", "decode"
        ),
        "recognition_only_total_ms": aggregate_timing(samples, "recognition_only", "total"),
    }
    comparable_vehicle = [
        sample
        for sample in samples
        if sample["recognition_only"]["text"] and sample["full_vehicle"]["text"]
    ]
    comparable_plate = [
        sample
        for sample in samples
        if sample["recognition_only"]["text"] and sample["full_plate"]["text"]
    ]
    reference_samples = [sample for sample in samples if sample["reference"]["text"]]
    stage_p50 = {
        stage: timing[f"recognition_only_{stage}_ms"]["p50"]
        for stage in ("preprocess", "inference", "decode")
    }
    available_stages = {key: value for key, value in stage_p50.items() if value is not None}
    bottleneck = max(available_stages, key=available_stages.get) if available_stages else None
    full_vehicle_p50 = timing["full_vehicle_total_ms"]["p50"]
    rec_p50 = timing["recognition_only_total_ms"]["p50"]
    rec_p95 = timing["recognition_only_total_ms"]["p95"]
    confidence_delta: dict[str, dict[str, float | int | None]] = {}
    for comparison in (
        "rec_minus_full_vehicle",
        "rec_minus_full_plate",
        "rec_minus_summary_reference",
    ):
        values = [
            float(sample["agreement"][comparison])
            for sample in samples
            if sample["agreement"][comparison] is not None
        ]
        confidence_delta[comparison] = timing_summary(values)
    return {
        "sample_count": len(samples),
        "sample_failures": sum(bool(sample["sample_error"]) for sample in samples),
        "arm_failures": {
            arm_name: sum(bool(sample[arm_name]["error"]) for sample in samples)
            for arm_name in ("full_vehicle", "full_plate", "recognition_only")
        },
        "timing": timing,
        "recognition_only_bottleneck_by_p50": bottleneck,
        "recognition_only_speedup_vs_full_vehicle_p50": ratio(full_vehicle_p50, rec_p50),
        "recognition_only_p50_under_20ms": bool(rec_p50 is not None and rec_p50 < 20.0),
        "recognition_only_p95_under_20ms": bool(rec_p95 is not None and rec_p95 < 20.0),
        "valid_plate_rate": {
            arm_name: round(
                sum(bool(sample[arm_name]["plate_like"]) for sample in samples)
                / max(1, len(samples)),
                4,
            )
            for arm_name in ("full_vehicle", "full_plate", "recognition_only")
        },
        "agreement_rate": {
            "rec_vs_full_vehicle": (
                round(
                    sum(
                        sample["recognition_only"]["text"] == sample["full_vehicle"]["text"]
                        for sample in comparable_vehicle
                    )
                    / len(comparable_vehicle),
                    4,
                )
                if comparable_vehicle
                else None
            ),
            "rec_vs_full_plate": (
                round(
                    sum(
                        sample["recognition_only"]["text"] == sample["full_plate"]["text"]
                        for sample in comparable_plate
                    )
                    / len(comparable_plate),
                    4,
                )
                if comparable_plate
                else None
            ),
            "rec_vs_summary_reference": (
                round(
                    sum(
                        sample["recognition_only"]["text"] == sample["reference"]["text"]
                        for sample in reference_samples
                    )
                    / len(reference_samples),
                    4,
                )
                if reference_samples
                else None
            ),
        },
        "confidence_delta": confidence_delta,
        "confirmed_plate_check": {
            "expected": "冀B6R9F9",
            "recognition_only_matches": sum(
                sample["recognition_only"]["text"] == "冀B6R9F9" for sample in samples
            ),
            "note": (
                "This checks whether the confirmed plate appears in this crop set; "
                "absence does not prove the model is wrong if the sample set does not contain it."
            ),
        },
    }


def print_summary(aggregate: dict[str, Any], output_dir: Path) -> None:
    timing = aggregate["timing"]

    def line(label: str, key: str) -> None:
        stats = timing[key]
        print(
            f"{label:<32} "
            f"P50={stats['p50']} ms  P95={stats['p95']} ms  "
            f"mean={stats['mean']} ms  min={stats['min']} ms  max={stats['max']} ms"
        )

    print("\n=== HyperLPR3 recognition-only A/B summary ===")
    print(
        f"samples={aggregate['sample_count']}  sample_failures={aggregate['sample_failures']}  "
        f"arm_failures={aggregate['arm_failures']}"
    )
    line("full / vehicle crop", "full_vehicle_total_ms")
    line("full / plate crop", "full_plate_total_ms")
    line("recognition-only / total", "recognition_only_total_ms")
    line("  preprocess", "recognition_only_preprocess_ms")
    line("  inference", "recognition_only_inference_ms")
    line("  decode", "recognition_only_decode_ms")
    print(f"bottleneck={aggregate['recognition_only_bottleneck_by_p50']}")
    print(
        "under 20 ms: "
        f"P50={aggregate['recognition_only_p50_under_20ms']}  "
        f"P95={aggregate['recognition_only_p95_under_20ms']}"
    )
    print(f"valid_plate_rate={aggregate['valid_plate_rate']}")
    print(f"agreement_rate={aggregate['agreement_rate']}")
    print(f"confidence_delta={aggregate['confidence_delta']}")
    print(f"confirmed_plate_check={aggregate['confirmed_plate_check']}")
    print(f"results={output_dir}")


def main() -> int:
    args = parse_args()
    input_run = args.input_run.resolve()
    samples = discover_samples(input_run)
    if not samples:
        raise RuntimeError(f"no plate_rank*.jpg samples found under: {input_run}")

    output_dir = create_unique_run_dir(args.output.resolve())
    model_path = resolve_hyperlpr3_recognition_model()

    import hyperlpr3
    import onnxruntime as ort
    from hyperlpr3.inference.recognition import PPRCNNRecognitionORT

    ort.set_default_logger_severity(3)
    full_engine = HyperLPR3OCR()
    recognizer = PPRCNNRecognitionORT(str(model_path), input_size=(48, 160))

    first_vehicle = read_image(samples[0]["vehicle_path"])
    first_plate = read_image(samples[0]["plate_path"])
    print(
        f"Discovered {len(samples)} paired candidates. Warming up each arm "
        f"{args.warmup} time(s)..."
    )
    warm_up(lambda: full_engine.recognize(first_vehicle), args.warmup, "full/vehicle")
    warm_up(lambda: full_engine.recognize(first_plate), args.warmup, "full/plate")
    warm_up(lambda: recognizer(first_plate), args.warmup, "recognition-only/plate")

    results: list[dict[str, Any]] = []
    for index, sample in enumerate(samples, start=1):
        print(
            f"[{index:02d}/{len(samples):02d}] track={sample['track_id']} rank={sample['rank']}",
            flush=True,
        )
        record: dict[str, Any] = {
            "track_id": sample["track_id"],
            "rank": sample["rank"],
            "vehicle_path": str(sample["vehicle_path"].resolve()),
            "plate_path": str(sample["plate_path"].resolve()),
            "reference": sample["reference"],
            "double_line_status": (
                "pending verification: recognition-only mode has no detector layer_num "
                "and does not split double-line plates"
            ),
            "sample_error": None,
        }
        try:
            vehicle_image = read_image(sample["vehicle_path"])
            plate_image = read_image(sample["plate_path"])
            record["full_vehicle"] = benchmark_full(
                full_engine.recognize, vehicle_image, args.repeats
            )
            record["full_plate"] = benchmark_full(
                full_engine.recognize, plate_image, args.repeats
            )
            record["recognition_only"] = benchmark_recognition_only(
                recognizer, plate_image, args.repeats
            )
        except Exception as exc:
            record["sample_error"] = f"{type(exc).__name__}: {exc}"
            empty_full = arm_payload([], {"total": []}, record["sample_error"])
            empty_rec = arm_payload(
                [],
                {"preprocess": [], "inference": [], "decode": [], "total": []},
                record["sample_error"],
            )
            record.setdefault("full_vehicle", empty_full)
            record.setdefault("full_plate", empty_full.copy())
            record.setdefault("recognition_only", empty_rec)

        rec_text = record["recognition_only"]["text"]
        full_vehicle_text = record["full_vehicle"]["text"]
        full_plate_text = record["full_plate"]["text"]
        reference_text = record["reference"]["text"]
        record["agreement"] = {
            "rec_vs_full_vehicle": (
                rec_text == full_vehicle_text if rec_text and full_vehicle_text else None
            ),
            "rec_vs_full_plate": rec_text == full_plate_text if rec_text and full_plate_text else None,
            "rec_vs_reference": rec_text == reference_text if rec_text and reference_text else None,
            "rec_minus_full_vehicle": difference(
                record["recognition_only"]["confidence"],
                record["full_vehicle"]["confidence"],
            ),
            "rec_minus_full_plate": difference(
                record["recognition_only"]["confidence"],
                record["full_plate"]["confidence"],
            ),
            "rec_minus_summary_reference": difference(
                record["recognition_only"]["confidence"],
                record["reference"]["confidence"],
            ),
        }
        results.append(record)

    aggregate = build_aggregate(results)
    payload = {
        "metadata": {
            "created_at": datetime.now().astimezone().isoformat(),
            "input_run": str(input_run),
            "output_dir": str(output_dir),
            "warmup_per_arm": args.warmup,
            "repeats_per_sample": args.repeats,
            "hyperlpr3_package": str(Path(hyperlpr3.__file__).resolve()),
            "recognition_model": str(model_path),
            "recognition_input_shape": list(recognizer.input_config.shape),
            "recognition_output_shape": list(recognizer.output_config.shape),
            "onnxruntime_version": ort.__version__,
            "onnxruntime_available_providers": ort.get_available_providers(),
            "reference_policy": (
                "Existing summary.json OCR is a comparison reference, not manually verified ground truth."
            ),
            "scope": (
                "Offline A/B only. No real-time pipeline, model, quantization, or C++ changes."
            ),
        },
        "aggregate": aggregate,
        "samples": results,
    }
    json_path = output_dir / "results.json"
    csv_path = output_dir / "results.csv"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    write_csv(csv_path, results)
    print_summary(aggregate, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
