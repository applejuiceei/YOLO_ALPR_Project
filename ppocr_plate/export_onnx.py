from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Sequence

import numpy as np


PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_DICTIONARY = PACKAGE_ROOT / "plate_chars.txt"
EXPECTED_INPUT_SHAPE = (1, 3, 48, 160)
EXPECTED_CHARACTER_COUNT = 76
EXPECTED_OPSET = 13
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


class ExportError(RuntimeError):
    """An actionable Paddle-to-ONNX export or validation failure."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_version(name: str) -> str | None:
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None


def validate_sources(model_dir: Path, dictionary: Path) -> tuple[Path, Path, list[str]]:
    model_dir = model_dir.resolve()
    dictionary = dictionary.resolve()
    model_file = model_dir / "inference.pdmodel"
    params_file = model_dir / "inference.pdiparams"
    missing = [path for path in (model_file, params_file, dictionary) if not path.is_file()]
    if missing:
        raise ExportError("required file(s) not found:\n" + "\n".join(f"  - {p}" for p in missing))
    empty = [path for path in (model_file, params_file, dictionary) if path.stat().st_size == 0]
    if empty:
        raise ExportError("required file(s) are empty:\n" + "\n".join(f"  - {p}" for p in empty))

    try:
        characters = dictionary.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise ExportError(f"dictionary is not valid UTF-8: {dictionary}") from exc
    if len(characters) != EXPECTED_CHARACTER_COUNT:
        raise ExportError(
            f"dictionary must contain exactly {EXPECTED_CHARACTER_COUNT} non-blank characters; "
            f"found {len(characters)} in {dictionary}"
        )
    if any(len(character) != 1 for character in characters):
        raise ExportError("every dictionary line must contain exactly one character")
    if len(set(characters)) != len(characters):
        raise ExportError(f"dictionary contains duplicate characters: {dictionary}")
    if " " in characters:
        raise ExportError("the plate dictionary must not contain a space character")
    return model_file, params_file, characters


def _converter_arguments(model_dir: Path, output: Path) -> list[str]:
    return [
        "--model_dir",
        str(model_dir),
        "--model_filename",
        "inference.pdmodel",
        "--params_filename",
        "inference.pdiparams",
        "--save_file",
        str(output),
        "--opset_version",
        str(EXPECTED_OPSET),
        "--enable_onnx_checker",
        "True",
    ]


def _run_converter_command(command: Sequence[str], output: Path) -> None:
    completed = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        details = []
        if completed.stdout.strip():
            details.append("stdout:\n" + completed.stdout.strip())
        if completed.stderr.strip():
            details.append("stderr:\n" + completed.stderr.strip())
        if completed.returncode == 0:
            details.append(f"converter returned success but did not create a non-empty file: {output}")
        raise ExportError(
            f"paddle2onnx conversion failed with exit code {completed.returncode}"
            + ("\n" + "\n".join(details) if details else "")
        )


def _export_with_python_module(model_file: Path, params_file: Path, output: Path) -> None:
    try:
        import paddle2onnx
    except ImportError as exc:
        raise ExportError(
            "paddle2onnx is required. Install it in the active environment with "
            "`python -m pip install paddle2onnx`, then run this command again."
        ) from exc

    exporter = getattr(paddle2onnx, "export", None)
    if not callable(exporter):
        raise ExportError(
            "the installed paddle2onnx package exposes neither a CLI executable nor the "
            "`paddle2onnx.export` Python API; reinstall or upgrade paddle2onnx"
        )

    common: dict[str, Any] = {
        "model_file": str(model_file),
        "params_file": str(params_file),
        "opset_version": EXPECTED_OPSET,
        "enable_onnx_checker": True,
    }
    try:
        signature = inspect.signature(exporter)
        parameters = signature.parameters
    except (TypeError, ValueError):
        parameters = {}
    if "auto_update_opset" in parameters:
        common["auto_update_opset"] = False
    if "auto_upgrade_opset" in parameters:
        common["auto_upgrade_opset"] = False
    if "save_file" in parameters:
        common["save_file"] = str(output)

    try:
        result = exporter(**common)
    except Exception as exc:  # paddle2onnx raises several backend-specific exception types
        raise ExportError(f"paddle2onnx Python API conversion failed: {exc}") from exc

    if output.is_file() and output.stat().st_size > 0:
        return
    if isinstance(result, (bytes, bytearray, memoryview)):
        output.write_bytes(bytes(result))
        return
    if isinstance(result, (str, Path)) and Path(result).is_file():
        shutil.copyfile(Path(result), output)
        return
    raise ExportError(
        "paddle2onnx.export returned without producing ONNX bytes or a non-empty output file"
    )


def export_paddle_model(model_file: Path, params_file: Path, output: Path) -> dict[str, Any]:
    executable = shutil.which("paddle2onnx")
    if executable:
        command = [executable, *_converter_arguments(model_file.parent, output)]
        _run_converter_command(command, output)
        return {"backend": "cli", "command": command, "version": package_version("paddle2onnx")}

    if importlib.util.find_spec("paddle2onnx") is None:
        raise ExportError(
            "paddle2onnx is required but was not found. Install it in the active environment "
            "with `python -m pip install paddle2onnx`, then run this command again."
        )
    _export_with_python_module(model_file, params_file, output)
    return {"backend": "python_api", "version": package_version("paddle2onnx")}


def _require_onnx_dependencies() -> tuple[Any, Any]:
    missing: list[str] = []
    try:
        import onnx
    except ImportError:
        onnx = None
        missing.append("onnx")
    try:
        import onnxruntime as ort
    except ImportError:
        ort = None
        missing.append("onnxruntime")
    if missing:
        raise ExportError(
            "ONNX validation requires missing package(s): "
            + ", ".join(missing)
            + ". Install them with `python -m pip install onnx onnxruntime`."
        )
    return onnx, ort


def _set_dimension(dimension: Any, value: int) -> None:
    dimension.ClearField("dim_param")
    dimension.dim_value = value


def fix_and_check_graph(path: Path, onnx: Any, class_count: int) -> dict[str, Any]:
    try:
        model = onnx.load(str(path))
    except Exception as exc:
        raise ExportError(f"cannot load converted ONNX model {path}: {exc}") from exc

    initializers = {initializer.name for initializer in model.graph.initializer}
    graph_inputs = [value for value in model.graph.input if value.name not in initializers]
    graph_outputs = list(model.graph.output)
    if len(graph_inputs) != 1:
        raise ExportError(f"expected exactly one ONNX image input, found {len(graph_inputs)}")
    if len(graph_outputs) != 1:
        raise ExportError(f"expected exactly one ONNX CTC output, found {len(graph_outputs)}")

    input_shape = graph_inputs[0].type.tensor_type.shape.dim
    if len(input_shape) != len(EXPECTED_INPUT_SHAPE):
        raise ExportError(
            f"ONNX input must be rank 4 NCHW, found rank {len(input_shape)} on {graph_inputs[0].name}"
        )
    for dimension, value in zip(input_shape, EXPECTED_INPUT_SHAPE):
        _set_dimension(dimension, value)

    output_shape = graph_outputs[0].type.tensor_type.shape.dim
    if len(output_shape) != 3:
        raise ExportError(
            f"ONNX CTC output must be rank 3 [batch,time,classes], found rank {len(output_shape)}"
        )
    _set_dimension(output_shape[0], 1)
    _set_dimension(output_shape[-1], class_count)

    default_domain_versions = [
        int(opset.version) for opset in model.opset_import if opset.domain in ("", "ai.onnx")
    ]
    if default_domain_versions != [EXPECTED_OPSET]:
        raise ExportError(
            f"converted model must use ai.onnx opset {EXPECTED_OPSET}; found {default_domain_versions}"
        )
    try:
        onnx.checker.check_model(model)
        onnx.save(model, str(path))
        reloaded = onnx.load(str(path))
        onnx.checker.check_model(reloaded)
    except Exception as exc:
        raise ExportError(f"ONNX checker rejected the converted model: {exc}") from exc
    return {
        "checker_passed": True,
        "opsets": {opset.domain or "ai.onnx": int(opset.version) for opset in model.opset_import},
    }


def _json_shape(shape: Sequence[Any]) -> list[int | str | None]:
    return [value if isinstance(value, (int, str)) else None for value in shape]


def validate_with_onnxruntime(path: Path, ort: Any, class_count: int) -> dict[str, Any]:
    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.inter_op_num_threads = 1
    options.intra_op_num_threads = 1
    available = ort.get_available_providers()
    providers = ["CPUExecutionProvider"] if "CPUExecutionProvider" in available else None
    try:
        session = ort.InferenceSession(
            str(path), sess_options=options, providers=providers
        )
    except Exception as exc:
        raise ExportError(f"ONNX Runtime cannot create a session for {path}: {exc}") from exc

    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or len(outputs) != 1:
        raise ExportError(
            f"ONNX Runtime sees {len(inputs)} inputs and {len(outputs)} outputs; expected one each"
        )
    input_info = inputs[0]
    output_info = outputs[0]
    actual_input_shape = tuple(input_info.shape)
    if actual_input_shape != EXPECTED_INPUT_SHAPE:
        raise ExportError(
            f"fixed ONNX input must be {list(EXPECTED_INPUT_SHAPE)}, found {list(actual_input_shape)}"
        )
    if input_info.type != "tensor(float)":
        raise ExportError(f"ONNX input must be float32, found {input_info.type}")

    try:
        result = session.run(
            [output_info.name],
            {input_info.name: np.zeros(EXPECTED_INPUT_SHAPE, dtype=np.float32)},
        )[0]
    except Exception as exc:
        raise ExportError(f"ONNX Runtime zero-input inference failed: {exc}") from exc
    actual_output_shape = tuple(int(value) for value in np.asarray(result).shape)
    if len(actual_output_shape) != 3:
        raise ExportError(
            f"runtime CTC output must be rank 3 [batch,time,classes], found {actual_output_shape}"
        )
    if actual_output_shape[0] != 1:
        raise ExportError(f"runtime output batch must be fixed to 1, found {actual_output_shape[0]}")
    if actual_output_shape[-1] != class_count:
        raise ExportError(
            f"runtime output must contain {class_count} CTC classes, "
            f"found {actual_output_shape[-1]}"
        )

    return {
        "provider": session.get_providers()[0] if session.get_providers() else None,
        "input": {
            "name": input_info.name,
            "type": input_info.type,
            "shape": _json_shape(input_info.shape),
        },
        "output": {
            "name": output_info.name,
            "type": output_info.type,
            "declared_shape": _json_shape(output_info.shape),
            "actual_shape": list(actual_output_shape),
        },
        "zero_input_inference_passed": True,
    }


def _collect_parity_paths(args: argparse.Namespace) -> list[Path]:
    if args.parity_samples < 1:
        raise ExportError("--parity-samples must be at least 1")
    if args.labels is not None and args.data_root is None:
        raise ExportError("--data-root is required when --labels is provided")
    if args.data_root is not None and args.labels is None:
        raise ExportError("--data-root is only valid together with --labels")

    paths: list[Path] = []
    if args.image_dir:
        image_root = args.image_dir.resolve()
        if not image_root.is_dir():
            raise ExportError(f"parity image directory does not exist: {image_root}")
        paths.extend(
            path.resolve()
            for path in sorted(image_root.rglob("*"))
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )
    elif args.labels is not None:
        labels_path = args.labels.resolve()
        data_root = args.data_root.resolve()
        if not labels_path.is_file():
            raise ExportError(f"parity labels file does not exist: {labels_path}")
        if not data_root.is_dir():
            raise ExportError(f"parity data root does not exist: {data_root}")
        for line_number, raw_line in enumerate(
            labels_path.read_text(encoding="utf-8-sig").splitlines(), start=1
        ):
            if not raw_line.strip():
                continue
            image_value = raw_line.split("\t", 1)[0].strip()
            if not image_value:
                raise ExportError(f"{labels_path}:{line_number}: empty image path")
            candidate = Path(image_value)
            resolved = (
                candidate.resolve()
                if candidate.is_absolute()
                else (data_root / candidate).resolve()
            )
            try:
                resolved.relative_to(data_root)
            except ValueError as exc:
                raise ExportError(
                    f"{labels_path}:{line_number}: image path escapes --data-root: "
                    f"{image_value!r}"
                ) from exc
            paths.append(resolved)

    unique_paths = sorted(set(paths), key=lambda path: str(path).casefold())
    if (args.image_dir or args.labels is not None) and not unique_paths:
        raise ExportError("no parity images were found in the requested source")
    selected = unique_paths[: args.parity_samples]
    missing = [path for path in selected if not path.is_file()]
    if missing:
        raise ExportError(
            "parity image file(s) not found:\n" + "\n".join(f"  - {path}" for path in missing)
        )
    return selected


def _require_parity_dependencies() -> tuple[Any, Any, Any, Any]:
    try:
        import cv2
    except ImportError as exc:
        raise ExportError(
            "real-crop parity requires OpenCV. Install it with "
            "`python -m pip install opencv-python`."
        ) from exc
    try:
        import paddle.inference as paddle_infer
    except ImportError as exc:
        raise ExportError(
            "real-crop parity requires PaddlePaddle inference. Install the PaddlePaddle "
            "version compatible with the exported inference model."
        ) from exc
    try:
        from .runtime import ctc_decode, preprocess_plate
    except ImportError:
        try:
            from runtime import ctc_decode, preprocess_plate
        except ImportError as exc:
            raise ExportError(
                "real-crop parity requires ppocr_plate.runtime and its NumPy/OpenCV "
                "dependencies"
            ) from exc
    return cv2, paddle_infer, ctc_decode, preprocess_plate


def _read_parity_image(path: Path, cv2: Any) -> np.ndarray:
    try:
        encoded = np.fromfile(str(path), dtype=np.uint8)
    except OSError as exc:
        raise ExportError(f"cannot read parity image {path}: {exc}") from exc
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
    if image is None:
        raise ExportError(f"cannot decode parity image: {path}")
    return image


def _create_paddle_predictor(model_file: Path, params_file: Path, paddle_infer: Any) -> Any:
    try:
        config = paddle_infer.Config(str(model_file), str(params_file))
        config.disable_gpu()
        config.switch_ir_optim(True)
        config.enable_memory_optim()
        config.set_cpu_math_library_num_threads(1)
        if hasattr(config, "disable_glog_info"):
            config.disable_glog_info()
        predictor = paddle_infer.create_predictor(config)
    except Exception as exc:
        raise ExportError(
            "Paddle inference predictor could not load the exported model for parity: "
            f"{exc}"
        ) from exc
    input_names = predictor.get_input_names()
    output_names = predictor.get_output_names()
    if len(input_names) != 1 or len(output_names) != 1:
        raise ExportError(
            "Paddle parity requires exactly one image input and one CTC output; "
            f"predictor exposes {len(input_names)} inputs and {len(output_names)} outputs"
        )
    return predictor


def validate_paddle_onnx_parity(
    *,
    model_file: Path,
    params_file: Path,
    onnx_path: Path,
    ort: Any,
    characters: Sequence[str],
    image_paths: Sequence[Path],
) -> dict[str, Any]:
    if not image_paths:
        return {
            "performed": False,
            "reason": "no --image-dir or --labels parity source was provided",
            "preprocess": "RGB float32 NCHW [1,3,48,160], x / 127.5 - 1",
        }

    cv2, paddle_infer, ctc_decode, preprocess_plate = _require_parity_dependencies()
    predictor = _create_paddle_predictor(model_file, params_file, paddle_infer)
    paddle_input_name = predictor.get_input_names()[0]
    paddle_output_name = predictor.get_output_names()[0]
    paddle_input = predictor.get_input_handle(paddle_input_name)
    paddle_output = predictor.get_output_handle(paddle_output_name)

    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.inter_op_num_threads = 1
    options.intra_op_num_threads = 1
    try:
        session = ort.InferenceSession(
            str(onnx_path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
    except Exception as exc:
        raise ExportError(f"ONNX Runtime cannot load the parity model: {exc}") from exc
    if len(session.get_inputs()) != 1 or len(session.get_outputs()) != 1:
        raise ExportError("ONNX parity requires exactly one input and one output")
    onnx_input_name = session.get_inputs()[0].name
    onnx_output_name = session.get_outputs()[0].name

    sample_results: list[dict[str, Any]] = []
    mismatches: list[str] = []
    absolute_difference_sum = 0.0
    absolute_difference_count = 0
    maximum_absolute_difference = 0.0
    expected_classes = len(characters) + 1

    for image_path in image_paths:
        image = _read_parity_image(image_path, cv2)
        tensor = preprocess_plate(
            image,
            target_height=EXPECTED_INPUT_SHAPE[2],
            target_width=EXPECTED_INPUT_SHAPE[3],
            color_order="rgb",
        )
        if tensor.shape != EXPECTED_INPUT_SHAPE or tensor.dtype != np.float32:
            raise ExportError(
                f"shared RGB preprocessor returned {tensor.dtype} {list(tensor.shape)} for "
                f"{image_path}; expected float32 {list(EXPECTED_INPUT_SHAPE)}"
            )
        try:
            paddle_input.reshape(list(EXPECTED_INPUT_SHAPE))
            paddle_input.copy_from_cpu(tensor)
            if not predictor.run():
                raise ExportError(f"Paddle predictor returned failure for {image_path}")
            paddle_scores = np.asarray(paddle_output.copy_to_cpu())
        except ExportError:
            raise
        except Exception as exc:
            raise ExportError(f"Paddle parity inference failed for {image_path}: {exc}") from exc
        try:
            onnx_scores = np.asarray(
                session.run([onnx_output_name], {onnx_input_name: tensor})[0]
            )
        except Exception as exc:
            raise ExportError(f"ONNX parity inference failed for {image_path}: {exc}") from exc

        if not np.isfinite(paddle_scores).all():
            raise ExportError(f"Paddle output contains NaN or Inf for parity image {image_path}")
        if not np.isfinite(onnx_scores).all():
            raise ExportError(f"ONNX output contains NaN or Inf for parity image {image_path}")
        if paddle_scores.shape != onnx_scores.shape:
            raise ExportError(
                f"Paddle/ONNX output shape mismatch for {image_path}: "
                f"{list(paddle_scores.shape)} versus {list(onnx_scores.shape)}"
            )
        if (
            paddle_scores.ndim != 3
            or paddle_scores.shape[0] != 1
            or paddle_scores.shape[-1] != expected_classes
        ):
            raise ExportError(
                f"parity output must be [1,time,{expected_classes}] for {image_path}, got "
                f"{list(paddle_scores.shape)}"
            )

        difference = np.abs(
            paddle_scores.astype(np.float64, copy=False)
            - onnx_scores.astype(np.float64, copy=False)
        )
        sample_max = float(difference.max()) if difference.size else 0.0
        sample_mean = float(difference.mean()) if difference.size else 0.0
        maximum_absolute_difference = max(maximum_absolute_difference, sample_max)
        absolute_difference_sum += float(difference.sum())
        absolute_difference_count += int(difference.size)

        paddle_text, paddle_confidence = ctc_decode(paddle_scores, characters)
        onnx_text, onnx_confidence = ctc_decode(onnx_scores, characters)
        text_matches = paddle_text == onnx_text
        if not text_matches:
            mismatches.append(
                f"{image_path}: Paddle={paddle_text!r}, ONNX={onnx_text!r}"
            )
        sample_results.append(
            {
                "image": str(image_path),
                "output_shape": list(paddle_scores.shape),
                "paddle_text": paddle_text,
                "paddle_confidence": float(paddle_confidence),
                "onnx_text": onnx_text,
                "onnx_confidence": float(onnx_confidence),
                "text_matches": text_matches,
                "max_abs_diff": sample_max,
                "mean_abs_diff": sample_mean,
            }
        )

    if mismatches:
        preview = "\n".join(f"  - {item}" for item in mismatches[:8])
        raise ExportError(
            f"Paddle/ONNX decoded text parity failed for {len(mismatches)} of "
            f"{len(image_paths)} sample(s):\n{preview}"
        )
    return {
        "performed": True,
        "passed": True,
        "sample_count": len(sample_results),
        "preprocess": "RGB float32 NCHW [1,3,48,160], x / 127.5 - 1",
        "paddle_input_name": paddle_input_name,
        "paddle_output_name": paddle_output_name,
        "onnx_input_name": onnx_input_name,
        "onnx_output_name": onnx_output_name,
        "max_abs_diff": maximum_absolute_difference,
        "mean_abs_diff": (
            absolute_difference_sum / absolute_difference_count
            if absolute_difference_count
            else 0.0
        ),
        "all_outputs_finite": True,
        "all_output_shapes_equal": True,
        "all_decoded_texts_equal": True,
        "samples": sample_results,
    }


def build_metadata(
    *,
    model_file: Path,
    params_file: Path,
    dictionary: Path,
    characters: Sequence[str],
    output: Path,
    converter: dict[str, Any],
    checker: dict[str, Any],
    runtime: dict[str, Any],
    parity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    class_count = len(characters) + 1
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "model": {
                "path": str(model_file),
                "sha256": sha256_file(model_file),
                "size_bytes": model_file.stat().st_size,
            },
            "parameters": {
                "path": str(params_file),
                "sha256": sha256_file(params_file),
                "size_bytes": params_file.stat().st_size,
            },
        },
        "dictionary": {
            "path": str(dictionary),
            "sha256": sha256_file(dictionary),
            "character_count_without_blank": len(characters),
            "ctc_blank_index": 0,
            "class_count_with_blank": class_count,
        },
        "converter": converter,
        "onnx": {
            "path": str(output),
            "sha256": sha256_file(output),
            "size_bytes": output.stat().st_size,
            **checker,
        },
        "contract": {
            "input_shape": list(EXPECTED_INPUT_SHAPE),
            "input_dtype": "float32",
            "output_layout": "batch,time,classes",
            "class_count_with_blank": class_count,
            "time_steps_may_be_dynamic": True,
            "batch_is_fixed": True,
        },
        "runtime_validation": runtime,
        "paddle_onnx_parity": parity
        or {
            "performed": False,
            "reason": "no --image-dir or --labels parity source was provided",
        },
        "dependencies": {
            "paddle2onnx": package_version("paddle2onnx"),
            "onnx": package_version("onnx"),
            "onnxruntime": package_version("onnxruntime"),
            "paddlepaddle": package_version("paddlepaddle"),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert a Paddle inference directory to the fixed [1,3,48,160] plate CTC "
            "ONNX contract (output classes = dictionary entries + CTC blank)."
        )
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        required=True,
        help="directory containing inference.pdmodel and inference.pdiparams",
    )
    parser.add_argument("--output", type=Path, required=True, help="destination .onnx file")
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY)
    parity_source = parser.add_mutually_exclusive_group()
    parity_source.add_argument(
        "--image-dir",
        type=Path,
        help="optional directory of real plate crops for Paddle/ONNX parity validation",
    )
    parity_source.add_argument(
        "--labels",
        type=Path,
        help="optional Paddle image<TAB>label file used to select parity crops",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        help="root for relative paths in --labels (required with --labels)",
    )
    parser.add_argument(
        "--parity-samples",
        type=int,
        default=16,
        help="maximum deterministic real-crop parity samples (default: 16)",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        help="metadata JSON path (default: <output>.metadata.json)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing output and metadata only after a new model passes validation",
    )
    return parser.parse_args()


def command_export(args: argparse.Namespace) -> tuple[Path, Path]:
    model_file, params_file, characters = validate_sources(args.model_dir, args.dictionary)
    parity_paths = _collect_parity_paths(args)
    output = args.output.resolve()
    metadata_path = (
        args.metadata.resolve()
        if args.metadata
        else Path(str(output) + ".metadata.json")
    )
    if output.suffix.lower() != ".onnx":
        raise ExportError(f"--output must use the .onnx extension: {output}")
    if output == metadata_path:
        raise ExportError("ONNX output and metadata JSON paths must be different")
    existing = [path for path in (output, metadata_path) if path.exists()]
    if existing and not args.overwrite:
        raise ExportError(
            "refusing to overwrite existing artifact(s); pass --overwrite explicitly:\n"
            + "\n".join(f"  - {path}" for path in existing)
        )

    onnx, ort = _require_onnx_dependencies()
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ppocr_onnx_", dir=str(output.parent)) as temp_dir:
        temporary_output = Path(temp_dir) / output.name
        converter = export_paddle_model(model_file, params_file, temporary_output)
        class_count = len(characters) + 1
        checker = fix_and_check_graph(temporary_output, onnx, class_count)
        runtime = validate_with_onnxruntime(temporary_output, ort, class_count)
        parity = validate_paddle_onnx_parity(
            model_file=model_file,
            params_file=params_file,
            onnx_path=temporary_output,
            ort=ort,
            characters=characters,
            image_paths=parity_paths,
        )

        output_metadata = build_metadata(
            model_file=model_file,
            params_file=params_file,
            dictionary=args.dictionary.resolve(),
            characters=characters,
            output=temporary_output,
            converter=converter,
            checker=checker,
            runtime=runtime,
            parity=parity,
        )
        output_metadata["onnx"]["path"] = str(output)
        temporary_metadata = Path(temp_dir) / "metadata.json"
        temporary_metadata.write_text(
            json.dumps(output_metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_output.replace(output)
        temporary_metadata.replace(metadata_path)
    return output, metadata_path


def main() -> int:
    args = parse_args()
    try:
        output, metadata_path = command_export(args)
    except (ExportError, OSError) as exc:
        print(f"export_onnx: error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"onnx": str(output), "metadata": str(metadata_path), "validated": True},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
