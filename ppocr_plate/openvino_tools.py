from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

import cv2
import numpy as np

from .runtime import ctc_decode, load_characters, preprocess_plate


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
CANONICAL_MANIFEST_COLUMNS = (
    "image_path",
    "label",
    "group_id",
    "source",
    "readable",
)
REAL_VERIFIED_SOURCE = "real_verified"
MIN_CALIBRATION_SAMPLES = 1000
MAX_CALIBRATION_SAMPLES = 2000
DEFAULT_COLOR_ORDER = "rgb"


@dataclass(frozen=True)
class Sample:
    path: Path
    label: str | None = None
    group_id: str | None = None


def _require_openvino() -> Any:
    try:
        import openvino as ov
    except ImportError as exc:
        raise RuntimeError(
            "OpenVINO is not installed. Install a version compatible with this Python "
            "environment, for example: pip install openvino"
        ) from exc
    return ov


def _require_nncf() -> Any:
    try:
        import nncf
    except ImportError as exc:
        raise RuntimeError(
            "NNCF is required for INT8 calibration. Install a version compatible with "
            "OpenVINO, for example: pip install nncf"
        ) from exc
    return nncf


def _read_image(path: Path) -> np.ndarray:
    if not path.is_file():
        raise FileNotFoundError(f"image does not exist: {path}")
    encoded = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot decode image: {path}")
    return image


def _static_nchw(input_port: Any) -> tuple[int, int]:
    try:
        shape = tuple(int(value) for value in input_port.shape)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise ValueError(
            f"model input must have a fixed [1, 3, H, W] shape, got {input_port.partial_shape}"
        ) from exc
    if len(shape) != 4 or shape[0] != 1 or shape[1] != 3:
        raise ValueError(f"model input must be fixed NCHW [1, 3, H, W], got {shape}")
    if shape[2] <= 0 or shape[3] <= 0:
        raise ValueError(f"model input dimensions must be positive, got {shape}")
    return shape[2], shape[3]


def _port_name(port: Any) -> str:
    try:
        return str(port.get_any_name())
    except RuntimeError:
        return "<unnamed>"


def _load_model(model_path: Path) -> tuple[Any, Any]:
    ov = _require_openvino()
    model_path = model_path.resolve()
    if not model_path.is_file():
        raise FileNotFoundError(f"model does not exist: {model_path}")
    core = ov.Core()
    try:
        model = core.read_model(str(model_path))
    except Exception as exc:
        raise RuntimeError(f"OpenVINO cannot read model {model_path}: {exc}") from exc
    if len(model.inputs) != 1:
        raise ValueError(f"recognizer must have exactly one input, got {len(model.inputs)}")
    if len(model.outputs) != 1:
        raise ValueError(f"recognizer must have exactly one CTC output, got {len(model.outputs)}")
    _static_nchw(model.input(0))
    return core, model


def _save_openvino_model(ov: Any, model: Any, output_path: Path) -> Path:
    output_path = output_path.resolve()
    if output_path.suffix.lower() != ".xml":
        raise ValueError("OpenVINO IR output must end in .xml")
    bin_path = output_path.with_suffix(".bin")
    if output_path.exists() or bin_path.exists():
        raise FileExistsError(
            f"refusing to overwrite an existing OpenVINO IR pair: {output_path}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ov.save_model(model, str(output_path), compress_to_fp16=False)
    if not output_path.is_file() or not bin_path.is_file():
        raise RuntimeError(f"OpenVINO did not create the expected IR pair: {output_path}")
    return output_path


def _iter_images(image_dirs: Sequence[Path]) -> Iterable[Path]:
    for image_dir in image_dirs:
        resolved = image_dir.resolve()
        if not resolved.is_dir():
            raise NotADirectoryError(f"image directory does not exist: {resolved}")
        for path in sorted(resolved.rglob("*")):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                yield path.resolve()


def _read_label_file(path: Path, data_root: Path) -> list[Sample]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"label/list file does not exist: {path}")
    samples: list[Sample] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", 1)
        image_value = parts[0].strip()
        if not image_value:
            raise ValueError(f"{path}:{line_number}: empty image path")
        image_path = Path(image_value)
        if not image_path.is_absolute():
            image_path = data_root / image_path
        label = parts[1].strip() if len(parts) == 2 and parts[1].strip() else None
        samples.append(Sample(path=image_path.resolve(), label=label))
    return samples


def _collect_samples(
    image_dirs: Sequence[Path],
    labels_path: Path | None,
    data_root: Path | None,
) -> list[Sample]:
    by_path: dict[Path, Sample] = {
        path: Sample(path=path) for path in _iter_images(image_dirs)
    }
    if labels_path is not None:
        if data_root is None:
            raise ValueError("--data-root is required when --labels is used")
        for sample in _read_label_file(labels_path, data_root.resolve()):
            by_path[sample.path] = sample
    samples = [by_path[path] for path in sorted(by_path, key=str)]
    if not samples:
        raise ValueError("no input images found; provide --image-dir and/or --labels")
    return samples


def _resolve_manifest_image(
    image_value: str,
    data_root: Path,
    manifest_path: Path,
    row_number: int,
) -> Path:
    if not image_value:
        raise ValueError(f"{manifest_path}:{row_number}: empty image_path")
    relative_path = Path(image_value)
    if (
        relative_path.is_absolute()
        or relative_path.drive
        or relative_path.root
        or ".." in relative_path.parts
    ):
        raise ValueError(
            f"{manifest_path}:{row_number}: image_path must be relative and stay "
            f"inside --data-root: {image_value!r}"
        )
    image_path = (data_root / relative_path).resolve()
    try:
        image_path.relative_to(data_root)
    except ValueError as exc:
        raise ValueError(
            f"{manifest_path}:{row_number}: image_path escapes --data-root: "
            f"{image_value!r}"
        ) from exc
    if not image_path.is_file():
        raise FileNotFoundError(
            f"{manifest_path}:{row_number}: calibration image does not exist: {image_path}"
        )
    return image_path


def _read_calibration_manifest(
    manifest_path: Path,
    data_root: Path,
) -> tuple[list[Sample], dict[str, int]]:
    manifest_path = manifest_path.resolve()
    data_root = data_root.resolve()
    if manifest_path.suffix.lower() != ".tsv":
        raise ValueError(
            f"INT8 calibration requires a canonical TSV manifest, got: {manifest_path}"
        )
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"canonical calibration manifest does not exist: {manifest_path}"
        )
    if not data_root.is_dir():
        raise NotADirectoryError(f"calibration data root does not exist: {data_root}")

    samples: list[Sample] = []
    seen_paths: set[Path] = set()
    seen_hashes: set[str] = set()
    seen_groups: set[str] = set()
    stats = {
        "manifest_rows": 0,
        "eligible_rows": 0,
        "duplicate_image_rows_skipped": 0,
        "duplicate_image_path_rows_skipped": 0,
        "duplicate_image_content_rows_skipped": 0,
        "duplicate_group_rows_skipped": 0,
    }
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fieldnames = tuple(reader.fieldnames or ())
        if fieldnames != CANONICAL_MANIFEST_COLUMNS:
            raise ValueError(
                f"{manifest_path}: canonical TSV columns must be exactly "
                f"{list(CANONICAL_MANIFEST_COLUMNS)}, got {list(fieldnames)}"
            )
        for row_number, row in enumerate(reader, start=2):
            stats["manifest_rows"] += 1
            if None in row:
                raise ValueError(
                    f"{manifest_path}:{row_number}: malformed TSV row has extra fields"
                )
            source = (row.get("source") or "").strip()
            readable = (row.get("readable") or "").strip()
            if source != REAL_VERIFIED_SOURCE or readable != "1":
                continue
            stats["eligible_rows"] += 1
            group_id = (row.get("group_id") or "").strip()
            if not group_id:
                raise ValueError(
                    f"{manifest_path}:{row_number}: real_verified readable row has empty group_id"
                )
            image_path = _resolve_manifest_image(
                (row.get("image_path") or "").strip(),
                data_root,
                manifest_path,
                row_number,
            )
            if image_path in seen_paths:
                stats["duplicate_image_rows_skipped"] += 1
                stats["duplicate_image_path_rows_skipped"] += 1
                continue
            if group_id in seen_groups:
                stats["duplicate_group_rows_skipped"] += 1
                continue
            try:
                image_digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
            except OSError as exc:
                raise RuntimeError(
                    f"{manifest_path}:{row_number}: cannot read calibration image "
                    f"for duplicate detection: {image_path}: {exc}"
                ) from exc
            if image_digest in seen_hashes:
                stats["duplicate_image_rows_skipped"] += 1
                stats["duplicate_image_content_rows_skipped"] += 1
                continue
            seen_paths.add(image_path)
            seen_hashes.add(image_digest)
            seen_groups.add(group_id)
            label = (row.get("label") or "").strip() or None
            samples.append(Sample(path=image_path, label=label, group_id=group_id))
    stats["unique_rows_after_path_hash_group_dedup"] = len(samples)
    return samples, stats


def _latency_stats(values: Sequence[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    if not array.size:
        raise ValueError("cannot summarize an empty latency sequence")
    return {
        "min_ms": float(np.min(array)),
        "mean_ms": float(np.mean(array)),
        "p50_ms": float(np.percentile(array, 50)),
        "p95_ms": float(np.percentile(array, 95)),
        "max_ms": float(np.max(array)),
    }


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_character in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_character != right_character),
                )
            )
        previous = current
    return previous[-1]


def _quality(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    labeled = [row for row in rows if row["label"] is not None]
    if not labeled:
        return {
            "labeled_samples": 0,
            "exact_accuracy": None,
            "character_accuracy": None,
        }
    exact_matches = sum(row["text"] == row["label"] for row in labeled)
    character_count = sum(len(row["label"]) for row in labeled)
    edit_errors = sum(_edit_distance(row["label"], row["text"]) for row in labeled)
    return {
        "labeled_samples": len(labeled),
        "exact_accuracy": exact_matches / len(labeled),
        "character_accuracy": max(0.0, 1.0 - edit_errors / max(1, character_count)),
    }


def command_convert(args: argparse.Namespace) -> int:
    ov = _require_openvino()
    _, model = _load_model(args.model)
    output_path = _save_openvino_model(ov, model, args.output)
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_model": str(args.model.resolve()),
        "fp32_ir": str(output_path),
        "input_shape": list(model.input(0).shape),
        "output_shape": [str(value) for value in model.output(0).partial_shape],
    }
    report_path = output_path.with_suffix(".conversion.json")
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_quantize(args: argparse.Namespace) -> int:
    if not (
        MIN_CALIBRATION_SAMPLES
        <= args.min_samples
        <= args.max_samples
        <= MAX_CALIBRATION_SAMPLES
    ):
        raise ValueError(
            f"require {MIN_CALIBRATION_SAMPLES} <= --min-samples <= --max-samples "
            f"<= {MAX_CALIBRATION_SAMPLES}"
        )
    requested_output = args.output.resolve()
    if requested_output.suffix.lower() != ".xml":
        raise ValueError("OpenVINO IR output must end in .xml")
    report_path = requested_output.with_suffix(".quantization.json")
    existing_outputs = [
        path
        for path in (requested_output, requested_output.with_suffix(".bin"), report_path)
        if path.exists()
    ]
    if existing_outputs:
        raise FileExistsError(
            "refusing to overwrite existing INT8 output artifact(s): "
            + ", ".join(str(path) for path in existing_outputs)
        )

    samples, manifest_stats = _read_calibration_manifest(args.manifest, args.data_root)
    unique_eligible_count = len(samples)
    if unique_eligible_count < args.min_samples:
        raise ValueError(
            f"INT8 calibration requires at least {args.min_samples} unique images and "
            f"groups with source={REAL_VERIFIED_SOURCE!r} and readable=1, but canonical "
            f"manifest {args.manifest.resolve()} provides only {unique_eligible_count} "
            "after image/group deduplication"
        )
    selected = samples[: args.max_samples]

    ov = _require_openvino()
    nncf = _require_nncf()
    _, model = _load_model(args.model)
    target_height, target_width = _static_nchw(model.input(0))

    tensors: list[np.ndarray] = []
    for sample in selected:
        tensors.append(
            preprocess_plate(
                _read_image(sample.path),
                target_height=target_height,
                target_width=target_width,
                color_order=args.color_order,
            )
        )
    calibration_dataset = nncf.Dataset(tensors)
    try:
        quantized_model = nncf.quantize(
            model,
            calibration_dataset,
            subset_size=len(tensors),
        )
    except Exception as exc:
        raise RuntimeError(f"NNCF INT8 quantization failed: {exc}") from exc
    output_path = _save_openvino_model(ov, quantized_model, requested_output)
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_model": str(args.model.resolve()),
        "int8_ir": str(output_path),
        "calibration_manifest": str(args.manifest.resolve()),
        "calibration_data_root": str(args.data_root.resolve()),
        "calibration_contract": {
            "source": REAL_VERIFIED_SOURCE,
            "readable": 1,
            "unique_image_path": True,
            "unique_group_id": True,
        },
        "calibration_sample_count": len(tensors),
        "calibration_sample_minimum": args.min_samples,
        "calibration_sample_maximum": args.max_samples,
        "calibration_unique_eligible_count": unique_eligible_count,
        "calibration_manifest_stats": manifest_stats,
        "color_order": args.color_order,
        "input_shape": [1, 3, target_height, target_width],
        "normalization": "x / 127.5 - 1.0 with aspect resize and zero padding",
        "calibration_images": [str(sample.path) for sample in selected],
        "calibration_group_ids": [sample.group_id for sample in selected],
    }
    with report_path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                key: value
                for key, value in payload.items()
                if key not in {"calibration_images", "calibration_group_ids"}
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _compile_for_latency(
    core: Any,
    model: Any,
    device: str,
    threads: int,
) -> Any:
    config: dict[str, Any] = {
        "PERFORMANCE_HINT": "LATENCY",
        "NUM_STREAMS": "1",
    }
    if threads > 0:
        config["INFERENCE_NUM_THREADS"] = threads
    try:
        return core.compile_model(model, device, config)
    except Exception as exc:
        raise RuntimeError(
            f"OpenVINO failed to compile the model for {device} with one stream: {exc}"
        ) from exc


def command_benchmark(args: argparse.Namespace) -> int:
    if args.warmup < 0 or args.iterations < 1:
        raise ValueError("--warmup must be >= 0 and --iterations must be >= 1")
    if args.threads < 0:
        raise ValueError("--threads must be >= 0")
    ov = _require_openvino()
    core, model = _load_model(args.model)
    input_port = model.input(0)
    target_height, target_width = _static_nchw(input_port)
    characters = load_characters(args.dictionary, use_space_char=args.use_space_char)
    samples = _collect_samples(args.image_dir, args.labels, args.data_root)
    loaded = [(sample, _read_image(sample.path)) for sample in samples]

    compiled_model = _compile_for_latency(core, model, args.device, args.threads)
    compiled_input = compiled_model.input(0)
    infer_request = compiled_model.create_infer_request()

    def infer(tensor: np.ndarray) -> np.ndarray:
        infer_request.infer({compiled_input: tensor})
        return np.array(infer_request.get_output_tensor(0).data, copy=True)

    for index in range(args.warmup):
        image = loaded[index % len(loaded)][1]
        tensor = preprocess_plate(
            image,
            target_height=target_height,
            target_width=target_width,
            color_order=args.color_order,
        )
        ctc_decode(infer(tensor), characters)

    timings: dict[str, list[float]] = {
        "preprocess": [],
        "inference": [],
        "decode": [],
        "total": [],
    }
    latest: dict[Path, tuple[str, float]] = {}
    for index in range(args.iterations):
        sample, image = loaded[index % len(loaded)]
        total_start = time.perf_counter_ns()
        tensor = preprocess_plate(
            image,
            target_height=target_height,
            target_width=target_width,
            color_order=args.color_order,
        )
        inference_start = time.perf_counter_ns()
        scores = infer(tensor)
        decode_start = time.perf_counter_ns()
        text, confidence = ctc_decode(scores, characters)
        end = time.perf_counter_ns()
        timings["preprocess"].append((inference_start - total_start) / 1e6)
        timings["inference"].append((decode_start - inference_start) / 1e6)
        timings["decode"].append((end - decode_start) / 1e6)
        timings["total"].append((end - total_start) / 1e6)
        latest[sample.path] = (text, confidence)

    rows: list[dict[str, Any]] = []
    for sample, _ in loaded:
        text, confidence = latest.get(sample.path, ("", 0.0))
        rows.append(
            {
                "image": str(sample.path),
                "label": sample.label,
                "text": text,
                "confidence": confidence,
                "exact_match": text == sample.label if sample.label is not None else None,
            }
        )

    latency = {stage: _latency_stats(values) for stage, values in timings.items()}
    quality = _quality(rows)
    total_stats = latency["total"]
    gates = {
        "p50_under_20ms": total_stats["p50_ms"] < 20.0,
        "p95_under_20ms": total_stats["p95_ms"] < 20.0,
        "exact_accuracy_at_least_98pct": (
            quality["exact_accuracy"] is not None and quality["exact_accuracy"] >= 0.98
        ),
        "character_accuracy_at_least_99_5pct": (
            quality["character_accuracy"] is not None
            and quality["character_accuracy"] >= 0.995
        ),
    }
    result = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "engine": "openvino",
        "openvino_version": getattr(ov, "__version__", "unknown"),
        "model": str(args.model.resolve()),
        "dictionary": str(args.dictionary.resolve()),
        "device": args.device,
        "batch_size": 1,
        "concurrency": 1,
        "streams": 1,
        "threads": args.threads if args.threads > 0 else "openvino_auto",
        "input_name": _port_name(input_port),
        "input_shape": list(input_port.shape),
        "output_name": _port_name(model.output(0)),
        "output_shape": [str(value) for value in model.output(0).partial_shape],
        "color_order": args.color_order,
        "warmup": args.warmup,
        "iterations": args.iterations,
        "sample_count": len(rows),
        "disk_io_included": False,
        "latency": latency,
        "quality": quality,
        "gates": gates,
        "samples": rows,
    }

    run_dir = args.output.resolve() / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (run_dir / "results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (run_dir / "latencies.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["iteration", "preprocess_ms", "inference_ms", "decode_ms", "total_ms"]
        )
        for index in range(args.iterations):
            writer.writerow(
                [index]
                + [
                    timings[stage][index]
                    for stage in ("preprocess", "inference", "decode", "total")
                ]
            )

    summary = {
        "run": str(run_dir),
        "color_order": args.color_order,
        **total_stats,
        **quality,
        "gates": gates,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert, INT8-calibrate, and benchmark a PP-OCR plate model with OpenVINO."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    convert = subparsers.add_parser(
        "convert", help="Save an ONNX/OpenVINO model as an uncompressed FP32 IR."
    )
    convert.add_argument("--model", type=Path, required=True)
    convert.add_argument("--output", type=Path, required=True, help="Output .xml path.")
    convert.set_defaults(handler=command_convert)

    quantize = subparsers.add_parser(
        "quantize", help="Quantize a model to INT8 with real, rectified plate crops."
    )
    quantize.add_argument("--model", type=Path, required=True)
    quantize.add_argument("--output", type=Path, required=True, help="Output INT8 .xml path.")
    quantize.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help=(
            "Canonical TSV manifest with image_path, label, group_id, source, readable; "
            "only source=real_verified and readable=1 rows are eligible."
        ),
    )
    quantize.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="Root for the canonical manifest's relative image_path values.",
    )
    quantize.add_argument(
        "--color-order",
        choices=("bgr", "rgb"),
        default=DEFAULT_COLOR_ORDER,
        help="Model tensor channel order (default: rgb).",
    )
    quantize.add_argument(
        "--min-samples",
        type=int,
        default=MIN_CALIBRATION_SAMPLES,
        help=(
            "Minimum distinct calibration images/groups "
            f"({MIN_CALIBRATION_SAMPLES}..{MAX_CALIBRATION_SAMPLES})."
        ),
    )
    quantize.add_argument(
        "--max-samples",
        type=int,
        default=MAX_CALIBRATION_SAMPLES,
        help=(
            "Maximum calibration subset size "
            f"({MIN_CALIBRATION_SAMPLES}..{MAX_CALIBRATION_SAMPLES})."
        ),
    )
    quantize.set_defaults(handler=command_quantize)

    benchmark = subparsers.add_parser(
        "benchmark", help="Run a synchronous batch=1, one-stream latency benchmark."
    )
    benchmark.add_argument("--model", type=Path, required=True)
    benchmark.add_argument(
        "--dictionary", type=Path, default=Path("ppocr_plate/plate_chars.txt")
    )
    benchmark.add_argument("--image-dir", type=Path, action="append", default=[])
    benchmark.add_argument("--labels", type=Path, help="Paddle image<TAB>label list.")
    benchmark.add_argument("--data-root", type=Path)
    benchmark.add_argument("--output", type=Path, default=Path("runs_ppocr_plate_openvino"))
    benchmark.add_argument("--device", default="CPU")
    benchmark.add_argument("--warmup", type=int, default=50)
    benchmark.add_argument("--iterations", type=int, default=1000)
    benchmark.add_argument(
        "--threads", type=int, default=0, help="0 lets OpenVINO choose the CPU thread count."
    )
    benchmark.add_argument(
        "--color-order",
        choices=("bgr", "rgb"),
        default=DEFAULT_COLOR_ORDER,
        help="Model tensor channel order (default: rgb).",
    )
    benchmark.add_argument("--use-space-char", action="store_true")
    benchmark.set_defaults(handler=command_benchmark)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except (
        FileExistsError,
        FileNotFoundError,
        NotADirectoryError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
