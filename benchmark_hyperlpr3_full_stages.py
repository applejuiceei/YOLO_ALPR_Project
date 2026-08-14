from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np

from benchmark_hyperlpr3_image_dir import (
    DEFAULT_INPUT_DIR,
    discover_images,
    preload_images,
    result_fields,
)
from benchmark_hyperlpr3_recognition import create_unique_run_dir, timing_summary
from hyperlpr3_ocr import HyperLPR3OCR


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_ROOT = PROJECT_DIR / "runs_hyperlpr3_full_stages"
COMPONENTS = ("detector", "recognizer", "classifier")
PHASES = ("preprocess", "inference", "postprocess")
PER_INPUT_TIMING_KEYS = (
    "detector_preprocess_ms",
    "detector_inference_ms",
    "detector_postprocess_ms",
    "detector_total_ms",
    "recognizer_preprocess_ms",
    "recognizer_inference_ms",
    "recognizer_postprocess_ms",
    "recognizer_total_ms",
    "classifier_preprocess_ms",
    "classifier_inference_ms",
    "classifier_postprocess_ms",
    "classifier_total_ms",
    "all_model_preprocess_ms",
    "all_model_inference_ms",
    "all_model_postprocess_ms",
    "perspective_rectify_ms",
    "pipeline_other_ms",
    "result_parse_ms",
    "public_wrapper_other_ms",
    "public_total_ms",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Profile every internal stage of the complete HyperLPR3 public API on "
            "preloaded plate images without modifying the installed package."
        )
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--recursive", action="store_true")
    args = parser.parse_args()
    if args.warmup < 0:
        parser.error("--warmup must be >= 0")
    if args.repeats <= 0:
        parser.error("--repeats must be > 0")
    if args.limit < 0:
        parser.error("--limit must be >= 0")
    return args


class FullStageProfiler:
    """Time bound HyperLPR3 methods while leaving the original pipeline intact."""

    def __init__(self, engine: HyperLPR3OCR) -> None:
        self.engine = engine
        self.pipeline = engine.catcher.pipeline
        self.current: dict[str, Any] | None = None
        self._originals: list[tuple[Any, str, Any]] = []

        self._wrap_component(self.pipeline.detector, "detector")
        self._wrap_component(self.pipeline.recognizer, "recognizer")
        self._wrap_component(self.pipeline.classifier, "classifier")
        import hyperlpr3.inference.pipeline as pipeline_module

        self._wrap_method(
            pipeline_module,
            "get_rotate_crop_image",
            "perspective_rectify",
        )
        self._wrap_method(
            self.pipeline,
            "run",
            "pipeline_total",
            self._pipeline_output,
        )
        self._wrap_method(self.engine, "_parse_results", "result_parse")

    def _append(self, key: str, elapsed_ms: float) -> None:
        if self.current is not None:
            self.current["invocations"].setdefault(key, []).append(elapsed_ms)

    def _wrap_method(
        self,
        owner: Any,
        method_name: str,
        key: str,
        on_result: Callable[[Any, dict[str, Any]], None] | None = None,
    ) -> None:
        original = getattr(owner, method_name)
        self._originals.append((owner, method_name, original))

        def timed(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter_ns()
            try:
                result = original(*args, **kwargs)
            except Exception:
                self._append(key, (time.perf_counter_ns() - started) / 1_000_000.0)
                raise
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            self._append(key, elapsed_ms)
            if on_result is not None and self.current is not None:
                on_result(result, self.current)
            return result

        setattr(owner, method_name, timed)

    @staticmethod
    def _detector_output(result: Any, record: dict[str, Any]) -> None:
        candidates = int(len(result)) if result is not None else 0
        record["detected_candidates"] = candidates
        if candidates and isinstance(result, np.ndarray) and result.ndim == 2 and result.shape[1] > 13:
            record["double_layer_candidates"] = int(np.sum(result[:, 13].astype(int) == 1))
        else:
            record["double_layer_candidates"] = 0

    @staticmethod
    def _pipeline_output(result: Any, record: dict[str, Any]) -> None:
        record["raw_result_count"] = int(len(result)) if result is not None else 0

    def _wrap_component(self, component: Any, name: str) -> None:
        self._wrap_method(component, "_preprocess", f"{name}_preprocess")
        self._wrap_method(component, "_run_session", f"{name}_inference")
        self._wrap_method(
            component,
            "_postprocess",
            f"{name}_postprocess",
            self._detector_output if name == "detector" else None,
        )

    def close(self) -> None:
        for owner, method_name, original in reversed(self._originals):
            setattr(owner, method_name, original)
        self._originals.clear()

    @staticmethod
    def _sum(record: dict[str, Any], key: str) -> float:
        return float(sum(record["invocations"].get(key, [])))

    def profile(self, image: np.ndarray) -> tuple[dict[str, Any], dict[str, list[float]]]:
        raw: dict[str, Any] = {
            "invocations": {},
            "detected_candidates": 0,
            "double_layer_candidates": 0,
            "raw_result_count": 0,
        }
        self.current = raw
        started = time.perf_counter_ns()
        error: str | None = None
        result: tuple[Any, Any] = (None, None)
        try:
            result = self.engine.recognize(image)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        public_total_ms = (time.perf_counter_ns() - started) / 1_000_000.0
        self.current = None

        record: dict[str, Any] = {
            "error": error,
            "detected_candidates": raw["detected_candidates"],
            "single_layer_candidates": (
                raw["detected_candidates"] - raw["double_layer_candidates"]
            ),
            "double_layer_candidates": raw["double_layer_candidates"],
            "raw_result_count": raw["raw_result_count"],
            "recognizer_calls": len(raw["invocations"].get("recognizer_preprocess", [])),
            "classifier_calls": len(raw["invocations"].get("classifier_preprocess", [])),
            "perspective_rectify_calls": len(
                raw["invocations"].get("perspective_rectify", [])
            ),
        }
        record.update(result_fields(result))

        for component in COMPONENTS:
            for phase in PHASES:
                key = f"{component}_{phase}"
                record[f"{key}_ms"] = self._sum(raw, key)
            record[f"{component}_total_ms"] = sum(
                float(record[f"{component}_{phase}_ms"]) for phase in PHASES
            )

        for phase in PHASES:
            record[f"all_model_{phase}_ms"] = sum(
                float(record[f"{component}_{phase}_ms"]) for component in COMPONENTS
            )

        pipeline_total_ms = self._sum(raw, "pipeline_total")
        result_parse_ms = self._sum(raw, "result_parse")
        perspective_rectify_ms = self._sum(raw, "perspective_rectify")
        record["perspective_rectify_ms"] = perspective_rectify_ms
        component_total_ms = sum(float(record[f"{name}_total_ms"]) for name in COMPONENTS)
        record["pipeline_other_ms"] = (
            pipeline_total_ms - component_total_ms - perspective_rectify_ms
        )
        record["result_parse_ms"] = result_parse_ms
        record["public_wrapper_other_ms"] = public_total_ms - pipeline_total_ms - result_parse_ms
        record["public_total_ms"] = public_total_ms
        return record, raw["invocations"]


def timing_values(records: list[dict[str, Any]], key: str) -> list[float]:
    return [float(record[key]) for record in records if record["error"] is None]


def summarize(
    records: list[dict[str, Any]],
    invocation_values: dict[str, list[float]],
) -> dict[str, Any]:
    successful = [record for record in records if record["error"] is None]
    with_output = [record for record in successful if record["text"]]
    without_output = [record for record in successful if not record["text"]]
    public_mean = statistics.fmean(timing_values(successful, "public_total_ms"))
    contribution_keys = (
        "detector_total_ms",
        "recognizer_total_ms",
        "classifier_total_ms",
        "perspective_rectify_ms",
        "pipeline_other_ms",
        "result_parse_ms",
        "public_wrapper_other_ms",
    )
    mean_contributions = {
        key: {
            "mean_ms_per_input": statistics.fmean(timing_values(successful, key)),
            "percent_of_public_mean": (
                statistics.fmean(timing_values(successful, key)) / public_mean * 100.0
                if public_mean > 0
                else None
            ),
        }
        for key in contribution_keys
    }
    candidate_counts = Counter(int(record["detected_candidates"]) for record in successful)
    recognizer_expected = [
        int(record["single_layer_candidates"])
        + 2 * int(record["double_layer_candidates"])
        for record in successful
    ]
    conditional_component_per_input = {
        "perspective_rectify_ms_when_called": timing_summary(
            [
                float(record["perspective_rectify_ms"])
                for record in successful
                if int(record["perspective_rectify_calls"]) > 0
            ]
        ),
        "recognizer_total_ms_when_called": timing_summary(
            [
                float(record["recognizer_total_ms"])
                for record in successful
                if int(record["recognizer_calls"]) > 0
            ]
        ),
        "classifier_total_ms_when_called": timing_summary(
            [
                float(record["classifier_total_ms"])
                for record in successful
                if int(record["classifier_calls"]) > 0
            ]
        ),
    }
    return {
        "calls": len(records),
        "successful_calls": len(successful),
        "errors": len(records) - len(successful),
        "nonempty_outputs": len(with_output),
        "nonempty_rate": len(with_output) / len(successful) if successful else None,
        "detected_candidates_total": sum(int(record["detected_candidates"]) for record in successful),
        "images_with_candidates": sum(int(record["detected_candidates"]) > 0 for record in successful),
        "candidate_count_distribution": dict(sorted(candidate_counts.items())),
        "double_layer_candidates_total": sum(
            int(record["double_layer_candidates"]) for record in successful
        ),
        "raw_results_total": sum(int(record["raw_result_count"]) for record in successful),
        "recognizer_invocations": sum(int(record["recognizer_calls"]) for record in successful),
        "recognizer_call_identity_violations": sum(
            int(record["recognizer_calls"]) != expected
            for record, expected in zip(successful, recognizer_expected)
        ),
        "classifier_invocations": sum(int(record["classifier_calls"]) for record in successful),
        "perspective_rectify_invocations": sum(
            int(record["perspective_rectify_calls"]) for record in successful
        ),
        "per_input_timings_ms": {
            key: timing_summary(timing_values(successful, key))
            for key in PER_INPUT_TIMING_KEYS
        },
        "per_invocation_timings_ms": {
            key: timing_summary(values) for key, values in sorted(invocation_values.items())
        },
        "conditional_component_per_input_ms": conditional_component_per_input,
        "conditional_public_total_ms": {
            "with_output": timing_summary(timing_values(with_output, "public_total_ms")),
            "without_output": timing_summary(timing_values(without_output, "public_total_ms")),
        },
        "mean_time_contributions": mean_contributions,
    }


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    columns = (
        "image",
        "repeat",
        "text",
        "confidence",
        "plate_like",
        "detected_candidates",
        "single_layer_candidates",
        "double_layer_candidates",
        "raw_result_count",
        "recognizer_calls",
        "classifier_calls",
        "perspective_rectify_calls",
        *PER_INPUT_TIMING_KEYS,
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
    print(f"Preloading {len(paths)} image(s); disk I/O is excluded...", flush=True)
    loaded, decode_errors = preload_images(paths)
    if not loaded:
        raise RuntimeError("none of the discovered images could be decoded")

    output_dir = create_unique_run_dir(args.output.resolve())
    import hyperlpr3
    import onnxruntime as ort

    ort.set_default_logger_severity(3)
    started = time.perf_counter_ns()
    engine = HyperLPR3OCR()
    initialization_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    parity_count = min(5, len(loaded))
    baseline_results = [
        result_fields(engine.recognize(loaded[index]["image"]))
        for index in range(parity_count)
    ]
    profiler = FullStageProfiler(engine)
    profiled_results = [
        {
            key: value
            for key, value in profiler.profile(loaded[index]["image"])[0].items()
            if key in {"text", "confidence", "plate_like"}
        }
        for index in range(parity_count)
    ]
    parity_mismatches = [
        index
        for index, (baseline, profiled) in enumerate(
            zip(baseline_results, profiled_results), start=1
        )
        if baseline != profiled
    ]
    if parity_mismatches:
        profiler.close()
        raise RuntimeError(
            f"instrumentation changed public results for parity sample(s): {parity_mismatches}"
        )

    print(f"Warming up complete API {args.warmup} time(s)...", flush=True)
    try:
        for index in range(args.warmup):
            record, _invocations = profiler.profile(loaded[index % len(loaded)]["image"])
            if record["error"]:
                raise RuntimeError(
                    f"warm-up failed at call {index + 1}: {record['error']}"
                )

        records: list[dict[str, Any]] = []
        all_invocations: dict[str, list[float]] = {}
        total = len(loaded) * args.repeats
        completed = 0
        for repeat in range(1, args.repeats + 1):
            for item in loaded:
                record, invocations = profiler.profile(item["image"])
                record["image"] = str(item["path"])
                record["repeat"] = repeat
                records.append(record)
                for key, values in invocations.items():
                    all_invocations.setdefault(key, []).extend(values)
                completed += 1
                if completed % 100 == 0 or completed == total:
                    print(f"[profile] {completed}/{total}", flush=True)
    finally:
        profiler.close()

    summary = summarize(records, all_invocations)
    pipeline = engine.catcher.pipeline
    payload = {
        "metadata": {
            "created_at": datetime.now().astimezone().isoformat(),
            "input_dir": str(input_dir),
            "output_dir": str(output_dir),
            "discovered_images": len(paths),
            "decoded_images": len(loaded),
            "decode_errors": decode_errors,
            "warmup_calls": args.warmup,
            "repeats_per_image": args.repeats,
            "disk_io_in_timing": False,
            "batch_size": 1,
            "concurrency": 1,
            "initialization_ms": initialization_ms,
            "hyperlpr3_package": str(Path(hyperlpr3.__file__).resolve()),
            "onnxruntime_version": ort.__version__,
            "onnxruntime_available_providers": ort.get_available_providers(),
            "detector_input_size": list(pipeline.detector.input_size),
            "detector_effective_postprocess_thresholds": {
                "confidence": 0.25,
                "iou": 0.5,
                "source": "post_precessing function defaults used by MultiTaskDetectorORT",
            },
            "recognizer_input_shape": list(pipeline.recognizer.input_config.shape),
            "classifier_input_shape": list(pipeline.classifier.input_config.shape),
            "instrumentation": (
                "Original bound methods are wrapped only with perf_counter_ns. Pipeline "
                "control flow and model outputs are unchanged. Conditional stages are "
                "reported both per input (missing stage=0) and per actual invocation."
            ),
            "instrumentation_parity": {
                "samples": parity_count,
                "public_result_mismatches": len(parity_mismatches),
            },
            "quality_policy": (
                "No manually verified labels are present; this run measures timing and "
                "call behavior, not OCR accuracy."
            ),
        },
        "summary": summary,
        "records": records,
    }
    results_path = output_dir / "results.json"
    csv_path = output_dir / "stage_latencies.csv"
    results_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    write_csv(csv_path, records)

    print(
        json.dumps(
            {
                "output": str(output_dir),
                "calls": summary["calls"],
                "nonempty_rate": summary["nonempty_rate"],
                "candidate_count_distribution": summary["candidate_count_distribution"],
                "raw_results_total": summary["raw_results_total"],
                "recognizer_invocations": summary["recognizer_invocations"],
                "recognizer_call_identity_violations": summary[
                    "recognizer_call_identity_violations"
                ],
                "classifier_invocations": summary["classifier_invocations"],
                "per_input_timings_ms": summary["per_input_timings_ms"],
                "per_invocation_timings_ms": summary["per_invocation_timings_ms"],
                "conditional_component_per_input_ms": summary[
                    "conditional_component_per_input_ms"
                ],
                "conditional_public_total_ms": summary["conditional_public_total_ms"],
                "mean_time_contributions": summary["mean_time_contributions"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
