"""Run the fixed-shape plate deblurring ONNX model on one image or a folder of plate crops."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable


PROJECT_DIR = Path(__file__).resolve().parent
LOCAL_ORT_DEPS = PROJECT_DIR / "python_deps_ocr"
if LOCAL_ORT_DEPS.is_dir():
    sys.path.insert(0, str(LOCAL_ORT_DEPS))

import cv2
import numpy as np
import onnxruntime as ort


DEFAULT_MODEL = PROJECT_DIR / "blur models" / "plate_restore_lite_320x96.onnx"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
MODEL_WIDTH = 320
MODEL_HEIGHT = 96


def collect_images(input_path: Path, recursive: bool) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(f"Input does not exist: {input_path}")
    iterator = input_path.rglob("*") if recursive else input_path.glob("*")
    return sorted(path for path in iterator if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)


def create_comparison(input_320: np.ndarray, restored: np.ndarray) -> np.ndarray:
    comparison = cv2.hconcat([input_320, restored])
    cv2.putText(comparison, "input", (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(comparison, "restored", (MODEL_WIDTH + 6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1, cv2.LINE_AA)
    return comparison


def load_onnx_predictor(model_path: Path) -> tuple[Callable[[np.ndarray], np.ndarray], str]:
    try:
        session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    except Exception as exc:
        external_data = Path(f"{model_path}.data")
        hint = f" Download the matching external data file too: {external_data.name}" if not external_data.is_file() else ""
        raise RuntimeError(f"Could not load ONNX model: {model_path}.{hint}") from exc
    input_info = session.get_inputs()[0]

    def predict(model_input: np.ndarray) -> np.ndarray:
        return session.run(None, {input_info.name: model_input})[0]

    return predict, f"ONNX input: name={input_info.name} shape={input_info.shape} provider={session.get_providers()[0]}"


def load_torch_predictor(model_path: Path) -> tuple[Callable[[np.ndarray], np.ndarray], str]:
    import pathlib
    import torch

    from train_deblur_colab import PlateRestoreNetLite

    # Colab checkpoints can serialize pathlib.PosixPath objects in their argument metadata.
    # Map that metadata type to the local Windows path implementation while loading.
    original_posix_path = pathlib.PosixPath
    pathlib.PosixPath = pathlib.WindowsPath
    try:
        checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
    finally:
        pathlib.PosixPath = original_posix_path
    model = PlateRestoreNetLite(**checkpoint["model_config"])
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    def predict(model_input: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            return model(torch.from_numpy(model_input)).numpy()

    return predict, "PyTorch checkpoint: CPU inference"


def restore_image(predict: Callable[[np.ndarray], np.ndarray], image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    input_320 = cv2.resize(image, (MODEL_WIDTH, MODEL_HEIGHT), interpolation=cv2.INTER_CUBIC)
    model_input = input_320.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
    output = predict(model_input)
    if output.shape != (1, 3, MODEL_HEIGHT, MODEL_WIDTH):
        raise ValueError(f"Unexpected ONNX output shape: {output.shape}")
    restored = np.clip(output[0].transpose(1, 2, 0), 0.0, 1.0)
    return input_320, (restored * 255.0 + 0.5).astype(np.uint8)


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore one or more cropped plate images using the ONNX deblurring model.")
    parser.add_argument("--input", required=True, type=Path, help="A cropped plate image or a directory containing cropped plate images.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="A self-contained .onnx model or the downloaded .pt checkpoint.")
    parser.add_argument("--output", type=Path, default=PROJECT_DIR / "blur models" / "static_test")
    parser.add_argument("--recursive", action="store_true", help="Search subdirectories when --input is a directory.")
    args = parser.parse_args()

    if not args.model.is_file():
        raise FileNotFoundError(f"ONNX model does not exist: {args.model}")
    image_paths = collect_images(args.input, args.recursive)
    if not image_paths:
        raise FileNotFoundError(f"No supported images under: {args.input}")

    args.output.mkdir(parents=True, exist_ok=True)
    if args.model.suffix.lower() == ".onnx":
        predict, model_info = load_onnx_predictor(args.model)
    elif args.model.suffix.lower() in {".pt", ".pth"}:
        predict, model_info = load_torch_predictor(args.model)
    else:
        raise ValueError("--model must be an .onnx, .pt, or .pth file")
    print(model_info)

    for image_path in image_paths:
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            print(f"[SKIP] unreadable: {image_path}")
            continue
        input_320, restored = restore_image(predict, image)
        stem = image_path.stem
        restored_path = args.output / f"{stem}_restored.jpg"
        comparison_path = args.output / f"{stem}_comparison.jpg"
        cv2.imwrite(str(restored_path), restored, [cv2.IMWRITE_JPEG_QUALITY, 100])
        cv2.imwrite(str(comparison_path), create_comparison(input_320, restored), [cv2.IMWRITE_JPEG_QUALITY, 100])
        print(f"[OK] {image_path.name} -> {restored_path.name}")

    print(f"Output directory: {args.output}")


if __name__ == "__main__":
    main()
