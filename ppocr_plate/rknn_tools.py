from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

try:
    from .runtime import ctc_decode, load_characters
except ImportError:  # Allow direct execution during board-side diagnostics.
    from runtime import ctc_decode, load_characters


TARGET_HEIGHT = 48
TARGET_WIDTH = 160
TARGET_SHAPE = (1, 3, TARGET_HEIGHT, TARGET_WIDTH)
MEAN_VALUES = [[127.5, 127.5, 127.5]]
STD_VALUES = [[127.5, 127.5, 127.5]]
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VERIFIED_REAL_SOURCE = "real_verified"
MIN_CALIBRATION_IMAGES = 1000
MAX_CALIBRATION_IMAGES = 2000
LATENCY_GATE_MS = 20.0
EXPECTED_NON_BLANK_CHARACTERS = 76


class RKNNToolError(RuntimeError):
    """Expected, user-actionable conversion or board benchmark error."""


@dataclass(frozen=True)
class Sample:
    path: Path
    label: str | None = None


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "readable"}


def _imread(path: Path) -> np.ndarray | None:
    """Read Unicode paths consistently on Windows and Linux."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def _prepare_rgb_uint8(image_bgr: np.ndarray) -> np.ndarray:
    """Create the uint8 RGB input consumed by RKNN's embedded normalization.

    Training-time zero padding represents normalized zero. Since RKNN applies
    ``(pixel - 127.5) / 127.5`` internally and uint8 cannot represent 127.5,
    padding uses the nearest value, 128.
    """
    if image_bgr is None or image_bgr.size == 0:
        raise RKNNToolError("plate image is empty")
    if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        raise RKNNToolError(f"plate image must be HWC BGR, got {image_bgr.shape}")
    height, width = image_bgr.shape[:2]
    resized_width = min(
        TARGET_WIDTH,
        max(1, int(np.ceil(TARGET_HEIGHT * width / max(height, 1)))),
    )
    resized_bgr = cv2.resize(
        image_bgr, (resized_width, TARGET_HEIGHT), interpolation=cv2.INTER_LINEAR
    )
    resized_rgb = cv2.cvtColor(resized_bgr, cv2.COLOR_BGR2RGB)
    padded = np.full((TARGET_HEIGHT, TARGET_WIDTH, 3), 128, dtype=np.uint8)
    padded[:, :resized_width] = resized_rgb
    return np.ascontiguousarray(padded[None])


def _safe_relative_path(raw_path: str, data_root: Path) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (data_root / candidate).resolve()
    root = data_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RKNNToolError(
            f"dataset path escapes --data-root: {raw_path!r} (root={root})"
        ) from exc
    return resolved


def _validate_onnx_contract(model_path: Path, requested_input_name: str | None) -> str:
    try:
        import onnx
    except ImportError as exc:
        raise RKNNToolError(
            "ONNX contract validation requires the 'onnx' package. Install it in the "
            "same supported x86 Linux environment as rknn-toolkit2."
        ) from exc

    try:
        model = onnx.load(str(model_path), load_external_data=False)
    except Exception as exc:
        raise RKNNToolError(f"failed to read ONNX model {model_path}: {exc}") from exc
    initializers = {item.name for item in model.graph.initializer}
    inputs = [item for item in model.graph.input if item.name not in initializers]
    if not inputs:
        raise RKNNToolError("ONNX model has no runtime input")
    if requested_input_name:
        matches = [item for item in inputs if item.name == requested_input_name]
        if not matches:
            names = ", ".join(item.name for item in inputs)
            raise RKNNToolError(
                f"ONNX input {requested_input_name!r} not found; available inputs: {names}"
            )
        model_input = matches[0]
    elif len(inputs) == 1:
        model_input = inputs[0]
    else:
        names = ", ".join(item.name for item in inputs)
        raise RKNNToolError(
            f"ONNX model has multiple inputs ({names}); select one with --input-name"
        )

    dimensions: list[int | str | None] = []
    tensor_shape = model_input.type.tensor_type.shape
    for dimension in tensor_shape.dim:
        if dimension.HasField("dim_value"):
            dimensions.append(int(dimension.dim_value))
        elif dimension.HasField("dim_param"):
            dimensions.append(dimension.dim_param)
        else:
            dimensions.append(None)
    if dimensions != list(TARGET_SHAPE):
        raise RKNNToolError(
            "plate OCR ONNX input must be fixed NCHW [1, 3, 48, 160], "
            f"but {model_input.name!r} is {dimensions}"
        )
    return model_input.name


def _read_real_calibration_rows(
    manifest_path: Path,
    data_root: Path,
    *,
    count: int,
    seed: int,
) -> list[Path]:
    if not manifest_path.is_file():
        raise RKNNToolError(f"calibration manifest not found: {manifest_path}")
    if count < MIN_CALIBRATION_IMAGES or count > MAX_CALIBRATION_IMAGES:
        raise RKNNToolError(
            f"--calibration-count must be {MIN_CALIBRATION_IMAGES}.."
            f"{MAX_CALIBRATION_IMAGES}; got {count}"
        )
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        required = {"image_path", "label", "group_id", "source", "readable"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise RKNNToolError(
                f"calibration manifest is missing columns: {', '.join(sorted(missing))}"
            )
        paths: list[Path] = []
        seen: set[Path] = set()
        seen_hashes: set[str] = set()
        seen_groups: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            source = (row.get("source") or "").strip().lower()
            if source != VERIFIED_REAL_SOURCE:
                continue
            if not _truthy(row.get("readable") or ""):
                continue
            raw_path = (row.get("image_path") or "").strip()
            if not raw_path:
                raise RKNNToolError(
                    f"empty image_path in calibration manifest row {row_number}"
                )
            path = _safe_relative_path(raw_path, data_root)
            if not path.is_file():
                raise RKNNToolError(
                    f"calibration image missing in row {row_number}: {path}"
                )
            group_id = (row.get("group_id") or "").strip()
            if not group_id:
                raise RKNNToolError(
                    f"empty group_id in calibration manifest row {row_number}"
                )
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if path in seen or digest in seen_hashes or group_id in seen_groups:
                continue
            seen.add(path)
            seen_hashes.add(digest)
            seen_groups.add(group_id)
            paths.append(path)

    if len(paths) < count:
        raise RKNNToolError(
            f"INT8 calibration needs {count} unique readable rows with "
            f"source={VERIFIED_REAL_SOURCE}; manifest contains only {len(paths)}"
        )
    rng = random.Random(seed)
    rng.shuffle(paths)
    return paths[:count]


def _materialize_calibration_dataset(paths: Sequence[Path], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    list_path = output_dir / "dataset.txt"
    prepared_paths: list[str] = []
    errors: list[str] = []
    for index, source_path in enumerate(paths):
        image = _imread(source_path)
        if image is None:
            errors.append(str(source_path))
            continue
        rgb = _prepare_rgb_uint8(image)[0]
        # cv2.imwrite expects BGR. The PNG itself therefore stores conventional RGB.
        encoded_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        destination = output_dir / f"calibration_{index:04d}.png"
        if not cv2.imwrite(str(destination), encoded_bgr):
            errors.append(str(source_path))
            continue
        prepared_paths.append(str(destination.resolve()))
    if errors:
        preview = "; ".join(errors[:5])
        raise RKNNToolError(
            f"failed to decode/materialize {len(errors)} calibration images: {preview}"
        )
    list_path.write_text("\n".join(prepared_paths) + "\n", encoding="utf-8")
    return list_path


def _check_rknn_return(operation: str, result: Any) -> None:
    if result not in (0, None):
        raise RKNNToolError(f"RKNN {operation} failed with return code {result}")


def convert_model(args: argparse.Namespace) -> int:
    try:
        from rknn.api import RKNN
    except ImportError as exc:
        raise RKNNToolError(
            "RKNN conversion requires rknn-toolkit2 in a Rockchip-supported x86 Linux "
            "Python environment; rknnlite2 on the board cannot convert models."
        ) from exc

    model_path = args.onnx.resolve()
    output_path = args.output.resolve()
    if not model_path.is_file():
        raise RKNNToolError(f"ONNX model not found: {model_path}")
    if output_path.exists() and not args.force:
        raise RKNNToolError(f"output exists: {output_path}; pass --force to replace it")
    metadata_path = output_path.with_suffix(output_path.suffix + ".json")
    if metadata_path.exists() and not args.force:
        raise RKNNToolError(
            f"metadata output exists: {metadata_path}; pass --force to replace it"
        )
    input_name = _validate_onnx_contract(model_path, args.input_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    calibration_paths: list[Path] = []
    if args.precision == "int8":
        if args.calibration_manifest is None or args.calibration_data_root is None:
            raise RKNNToolError(
                "INT8 requires --calibration-manifest and --calibration-data-root. "
                f"Only readable rows with source={VERIFIED_REAL_SOURCE} are accepted."
            )
        calibration_paths = _read_real_calibration_rows(
            args.calibration_manifest.resolve(),
            args.calibration_data_root.resolve(),
            count=args.calibration_count,
            seed=args.calibration_seed,
        )

    rknn = RKNN(verbose=args.verbose)
    started_at = time.perf_counter()
    try:
        config_kwargs: dict[str, Any] = {
            "target_platform": "rk3588",
            "mean_values": MEAN_VALUES,
            "std_values": STD_VALUES,
        }
        if args.precision == "int8":
            config_kwargs["quantized_dtype"] = "asymmetric_quantized-8"
        _check_rknn_return("config", rknn.config(**config_kwargs))
        _check_rknn_return("load_onnx", rknn.load_onnx(model=str(model_path)))

        if args.precision == "int8":
            with tempfile.TemporaryDirectory(prefix="ppocr_plate_rknn_cal_") as temp_dir:
                dataset_path = _materialize_calibration_dataset(
                    calibration_paths, Path(temp_dir)
                )
                _check_rknn_return(
                    "build",
                    rknn.build(do_quantization=True, dataset=str(dataset_path)),
                )
        else:
            _check_rknn_return("build", rknn.build(do_quantization=False))
        _check_rknn_return("export_rknn", rknn.export_rknn(str(output_path)))
    except RKNNToolError:
        raise
    except Exception as exc:
        raise RKNNToolError(f"RKNN conversion failed: {exc}") from exc
    finally:
        try:
            rknn.release()
        except Exception:
            pass

    metadata = {
        "created_at": datetime.now().astimezone().isoformat(),
        "source_onnx": str(model_path),
        "output_rknn": str(output_path),
        "target_platform": "rk3588",
        "precision": args.precision,
        "input_name": input_name,
        "input_shape_nchw": list(TARGET_SHAPE),
        "runtime_input": "uint8 NHWC RGB",
        "resize": "aspect-preserving to height 48, right-pad to width 160",
        "padding_value": 128,
        "mean_values": MEAN_VALUES[0],
        "std_values": STD_VALUES[0],
        "calibration": {
            "manifest": str(args.calibration_manifest.resolve())
            if args.calibration_manifest
            else None,
            "data_root": str(args.calibration_data_root.resolve())
            if args.calibration_data_root
            else None,
            "real_readable_images": len(calibration_paths),
            "seed": args.calibration_seed if calibration_paths else None,
        },
        "conversion_seconds": time.perf_counter() - started_at,
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"RKNN model: {output_path}")
    print(f"Metadata:   {metadata_path}")
    return 0


def _resolve_sample_path(raw_path: str, root: Path) -> Path:
    path = Path(raw_path)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _read_samples(source: Path, data_root: Path | None) -> list[Sample]:
    source = source.resolve()
    if source.is_dir():
        return [
            Sample(path)
            for path in sorted(source.rglob("*"))
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        ]
    if not source.is_file():
        raise RKNNToolError(f"image source not found: {source}")
    if source.suffix.lower() in IMAGE_SUFFIXES:
        return [Sample(source)]

    root = (data_root or source.parent).resolve()
    if source.suffix.lower() == ".tsv":
        with source.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            if "image_path" not in (reader.fieldnames or []):
                raise RKNNToolError(f"TSV lacks image_path column: {source}")
            samples = []
            for row in reader:
                if "readable" in row and not _truthy(row.get("readable") or ""):
                    continue
                raw_path = (row.get("image_path") or "").strip()
                if raw_path:
                    samples.append(
                        Sample(
                            _resolve_sample_path(raw_path, root),
                            (row.get("label") or "").strip() or None,
                        )
                    )
            return samples

    samples: list[Sample] = []
    for line_number, line in enumerate(
        source.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        raw_path = parts[0].strip()
        if not raw_path:
            raise RKNNToolError(f"empty image path at {source}:{line_number}")
        label = parts[1].strip() if len(parts) == 2 and parts[1].strip() else None
        samples.append(Sample(_resolve_sample_path(raw_path, root), label))
    return samples


def _preload_samples(samples: Sequence[Sample]) -> list[tuple[Sample, np.ndarray]]:
    loaded: list[tuple[Sample, np.ndarray]] = []
    errors: list[str] = []
    for sample in samples:
        image = _imread(sample.path)
        if image is None:
            errors.append(str(sample.path))
        else:
            loaded.append((sample, image))
    if errors:
        preview = "; ".join(errors[:5])
        raise RKNNToolError(f"failed to preload {len(errors)} images: {preview}")
    if not loaded:
        raise RKNNToolError("no plate images found")
    return loaded


def _core_mask(RKNNLite: Any, mode: str) -> int:
    mapping = {
        "auto": RKNNLite.NPU_CORE_AUTO,
        "single": RKNNLite.NPU_CORE_0,
        "core0": RKNNLite.NPU_CORE_0,
        "core1": RKNNLite.NPU_CORE_1,
        "core2": RKNNLite.NPU_CORE_2,
        "triple": RKNNLite.NPU_CORE_0_1_2,
    }
    return int(mapping[mode])


def _stats(values: Sequence[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "min": float(array.min()),
        "mean": float(array.mean()),
        "p50": float(np.percentile(array, 50)),
        "p95": float(np.percentile(array, 95)),
        "max": float(array.max()),
    }


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, start=1):
        current = [row]
        for column, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _accuracy(rows: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    labeled = [row for row in rows if row["label"] is not None]
    if not labeled:
        return None
    exact = sum(row["text"] == row["label"] for row in labeled)
    reference_characters = sum(len(row["label"]) for row in labeled)
    edit_errors = sum(_edit_distance(row["text"], row["label"]) for row in labeled)
    return {
        "labeled_samples": len(labeled),
        "exact_matches": exact,
        "exact_accuracy": exact / len(labeled),
        "character_accuracy": max(
            0.0, 1.0 - edit_errors / max(reference_characters, 1)
        ),
    }


def _sdk_version() -> str | None:
    try:
        from importlib.metadata import version

        for package in ("rknn-toolkit-lite2", "rknnlite2"):
            try:
                return version(package)
            except Exception:
                continue
    except Exception:
        pass
    return None


def benchmark_model(args: argparse.Namespace) -> int:
    try:
        from rknnlite.api import RKNNLite
    except ImportError as exc:
        raise RKNNToolError(
            "Board benchmarking requires rknn-toolkit-lite2 (rknnlite.api) on an "
            "RK3588 device. rknn-toolkit2 on the conversion host is not a substitute."
        ) from exc

    if args.warmup < 0 or args.iterations <= 0:
        raise RKNNToolError("--warmup must be >= 0 and --iterations must be > 0")
    if args.latency_gate_ms <= 0:
        raise RKNNToolError("--latency-gate-ms must be > 0")
    model_path = args.model.resolve()
    dict_path = args.dict.resolve()
    if not model_path.is_file():
        raise RKNNToolError(f"RKNN model not found: {model_path}")
    if not dict_path.is_file():
        raise RKNNToolError(f"character dictionary not found: {dict_path}")
    characters = load_characters(dict_path, use_space_char=False)
    if len(characters) != EXPECTED_NON_BLANK_CHARACTERS:
        raise RKNNToolError(
            "plate dictionary must match the verified HyperLPR3 character set: "
            f"{EXPECTED_NON_BLANK_CHARACTERS} non-blank characters plus one CTC blank; "
            f"got {len(characters)} non-blank characters"
        )
    samples = _preload_samples(_read_samples(args.images, args.data_root))

    runtime = RKNNLite(verbose=args.verbose)
    try:
        _check_rknn_return("load_rknn", runtime.load_rknn(str(model_path)))
        mask = _core_mask(RKNNLite, args.core_mode)
        _check_rknn_return("init_runtime", runtime.init_runtime(core_mask=mask))

        for index in range(args.warmup):
            _, image = samples[index % len(samples)]
            tensor = _prepare_rgb_uint8(image)
            outputs = runtime.inference(inputs=[tensor])
            if outputs is None:
                raise RKNNToolError("RKNN inference returned None during warmup")
            ctc_decode(outputs, characters)

        rows: list[dict[str, Any]] = []
        for iteration in range(args.iterations):
            sample, image = samples[iteration % len(samples)]
            total_start = time.perf_counter_ns()
            preprocess_start = total_start
            tensor = _prepare_rgb_uint8(image)
            inference_start = time.perf_counter_ns()
            outputs = runtime.inference(inputs=[tensor])
            decode_start = time.perf_counter_ns()
            if outputs is None:
                raise RKNNToolError(
                    f"RKNN inference returned None at measured iteration {iteration}"
                )
            text, confidence = ctc_decode(outputs, characters)
            total_end = time.perf_counter_ns()
            rows.append(
                {
                    "iteration": iteration,
                    "sample_path": str(sample.path),
                    "label": sample.label,
                    "text": text,
                    "confidence": confidence,
                    "preprocess_ms": (inference_start - preprocess_start) / 1e6,
                    "inference_ms": (decode_start - inference_start) / 1e6,
                    "decode_ms": (total_end - decode_start) / 1e6,
                    "total_ms": (total_end - total_start) / 1e6,
                }
            )
        quality_rows: list[dict[str, Any]] = []
        for sample, image in samples:
            outputs = runtime.inference(inputs=[_prepare_rgb_uint8(image)])
            if outputs is None:
                raise RKNNToolError(
                    f"RKNN inference returned None during quality pass: {sample.path}"
                )
            text, confidence = ctc_decode(outputs, characters)
            quality_rows.append(
                {
                    "sample_path": str(sample.path),
                    "label": sample.label,
                    "text": text,
                    "confidence": confidence,
                }
            )
    except RKNNToolError:
        raise
    except Exception as exc:
        raise RKNNToolError(f"RKNN board benchmark failed: {exc}") from exc
    finally:
        try:
            runtime.release()
        except Exception:
            pass

    stages = {
        name: _stats([float(row[name]) for row in rows])
        for name in ("preprocess_ms", "inference_ms", "decode_ms", "total_ms")
    }
    p95_pass = stages["total_ms"]["p95"] < args.latency_gate_ms
    accuracy = _accuracy(quality_rows)
    summary = {
        "created_at": datetime.now().astimezone().isoformat(),
        "platform": "rk3588",
        "backend": "rknnlite2",
        "rknnlite2_version": _sdk_version(),
        "model": str(model_path),
        "dictionary": str(dict_path),
        "non_blank_characters": len(characters),
        "ctc_classes": len(characters) + 1,
        "input_shape_nchw": list(TARGET_SHAPE),
        "runtime_input": "uint8 NHWC RGB",
        "mean_values": MEAN_VALUES[0],
        "std_values": STD_VALUES[0],
        "core_mode": args.core_mode,
        "core_mask": mask,
        "preloaded_samples": len(samples),
        "warmup": args.warmup,
        "iterations": args.iterations,
        "batch_size": 1,
        "concurrency": 1,
        "timing_scope": (
            "preprocess + RKNN inference + CTC decode; image reading and output writing "
            "excluded"
        ),
        "latency_ms": stages,
        "accuracy": accuracy,
        "gates": {
            "total_p95_limit_ms": args.latency_gate_ms,
            "total_p95_under_limit": p95_pass,
            "exact_accuracy_at_least_98pct": bool(
                accuracy and accuracy["exact_accuracy"] >= 0.98
            ),
            "character_accuracy_at_least_99_5pct": bool(
                accuracy and accuracy["character_accuracy"] >= 0.995
            ),
        },
    }

    run_dir = args.output.resolve() / (
        "run_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    json_path = run_dir / "results.json"
    csv_path = run_dir / "results.csv"
    json_path.write_text(
        json.dumps(
            {"summary": summary, "samples": quality_rows, "iterations": rows},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (run_dir / "samples.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(quality_rows[0]))
        writer.writeheader()
        writer.writerows(quality_rows)

    total = stages["total_ms"]
    inference = stages["inference_ms"]
    print(
        "RKNN OCR: "
        f"total P50={total['p50']:.3f} ms, P95={total['p95']:.3f} ms, "
        f"mean={total['mean']:.3f} ms; inference P95={inference['p95']:.3f} ms"
    )
    print(
        f"P95 < {args.latency_gate_ms:g} ms: " + ("PASS" if p95_pass else "FAIL")
    )
    print(f"Results: {run_dir}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    package_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Convert plate PP-OCR ONNX to RKNN and benchmark it on RK3588."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    convert = subparsers.add_parser(
        "convert", help="convert fixed 1x3x48x160 ONNX with rknn-toolkit2"
    )
    convert.add_argument("--onnx", type=Path, required=True)
    convert.add_argument("--output", type=Path, required=True)
    convert.add_argument("--precision", choices=("fp16", "int8"), default="fp16")
    convert.add_argument("--input-name", default=None)
    convert.add_argument("--calibration-manifest", type=Path)
    convert.add_argument("--calibration-data-root", type=Path)
    convert.add_argument("--calibration-count", type=int, default=2000)
    convert.add_argument("--calibration-seed", type=int, default=20260807)
    convert.add_argument("--force", action="store_true")
    convert.add_argument("--verbose", action="store_true")
    convert.set_defaults(handler=convert_model)

    benchmark = subparsers.add_parser(
        "benchmark", help="run preloaded, end-to-end OCR timing on an RK3588 board"
    )
    benchmark.add_argument("--model", type=Path, required=True)
    benchmark.add_argument(
        "--dict", type=Path, default=package_dir / "plate_chars.txt"
    )
    benchmark.add_argument(
        "--images",
        type=Path,
        required=True,
        help="image, directory, Paddle label txt, or canonical TSV manifest",
    )
    benchmark.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="base directory for relative paths in a txt/tsv input",
    )
    benchmark.add_argument(
        "--core-mode",
        choices=("auto", "single", "triple", "core0", "core1", "core2"),
        default="single",
    )
    benchmark.add_argument("--warmup", type=int, default=50)
    benchmark.add_argument("--iterations", type=int, default=1000)
    benchmark.add_argument("--latency-gate-ms", type=float, default=LATENCY_GATE_MS)
    benchmark.add_argument(
        "--output", type=Path, default=Path("runs_ppocr_plate_rknn")
    )
    benchmark.add_argument("--verbose", action="store_true")
    benchmark.set_defaults(handler=benchmark_model)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (RKNNToolError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
