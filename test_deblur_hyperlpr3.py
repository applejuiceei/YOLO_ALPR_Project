"""Test the plate deblur ONNX model and HyperLPR3 OCR on static plate images."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent
LOCAL_DEPS = PROJECT_DIR / "python_deps"
LOCAL_OCR_DEPS = PROJECT_DIR / "python_deps_ocr"
for deps in (LOCAL_DEPS, LOCAL_OCR_DEPS):
    if deps.is_dir():
        sys.path.insert(0, str(deps))

import cv2
import numpy as np

from hyperlpr3_ocr import HyperLPR3OCR
from plate_rec_ocr import PlateRecONNX


DEFAULT_MODEL = PROJECT_DIR / "blur models" / "deblur_v2_e20" / "plate_restore_lite_v2_e20_320x96.onnx"
DEFAULT_OUTPUT = PROJECT_DIR / "blur models" / "deblur_v2_e20" / "static_hyperlpr3_test"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
MODEL_WIDTH = 320
MODEL_HEIGHT = 96


def collect_images(input_path: Path, recursive: bool, all_images: bool) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(f"Input does not exist: {input_path}")
    iterator = input_path.rglob("*") if recursive else input_path.glob("*")
    image_paths = sorted(path for path in iterator if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)
    if all_images:
        return image_paths
    return [path for path in image_paths if path.name.startswith("plate_rank")]


class PlateDeblurONNX:
    def __init__(self, model_path: Path) -> None:
        import onnxruntime as ort

        if not model_path.is_file():
            raise FileNotFoundError(f"Deblur ONNX model not found: {model_path}")
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    def restore(self, image_bgr: np.ndarray) -> np.ndarray:
        resized = cv2.resize(image_bgr, (MODEL_WIDTH, MODEL_HEIGHT), interpolation=cv2.INTER_CUBIC)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        tensor = np.transpose(rgb, (2, 0, 1))[None]
        output = self.session.run(None, {self.input_name: tensor})[0]
        restored = np.clip(output[0].transpose(1, 2, 0), 0.0, 1.0)
        restored_bgr = cv2.cvtColor((restored * 255.0 + 0.5).astype(np.uint8), cv2.COLOR_RGB2BGR)
        return restored_bgr


def recognize(ocr: HyperLPR3OCR, image: np.ndarray) -> tuple[str | None, float | None]:
    text, confidence = ocr.recognize(image)
    if text:
        text = PlateRecONNX.clean_plate_text(text)
    return text or None, confidence


def draw_label(image: np.ndarray, label: str) -> np.ndarray:
    canvas = image.copy()
    cv2.putText(canvas, label, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 255), 2, cv2.LINE_AA)
    return canvas


def comparison_image(original: np.ndarray, restored: np.ndarray, original_text: str, restored_text: str) -> np.ndarray:
    original_320 = cv2.resize(original, (MODEL_WIDTH, MODEL_HEIGHT), interpolation=cv2.INTER_CUBIC)
    restored_320 = cv2.resize(restored, (MODEL_WIDTH, MODEL_HEIGHT), interpolation=cv2.INTER_CUBIC)
    left = draw_label(original_320, f"input {original_text}")
    right = draw_label(restored_320, f"deblur {restored_text}")
    return cv2.hconcat([left, right])


def safe_name(path: Path, root: Path | None) -> str:
    if root and root.is_dir():
        try:
            rel = path.relative_to(root)
            return "__".join(rel.with_suffix("").parts)
        except ValueError:
            pass
    return path.stem


def result_dict(
    image_path: Path,
    restored_path: Path,
    comparison_path: Path,
    original_text: str | None,
    original_conf: float | None,
    deblur_text: str | None,
    deblur_conf: float | None,
) -> dict[str, Any]:
    original_like = bool(original_text and PlateRecONNX.is_plate_like(original_text))
    deblur_like = bool(deblur_text and PlateRecONNX.is_plate_like(deblur_text))
    return {
        "input": str(image_path),
        "restored": str(restored_path),
        "comparison": str(comparison_path),
        "original_text": original_text,
        "original_confidence": original_conf,
        "original_plate_like": original_like,
        "deblur_text": deblur_text,
        "deblur_confidence": deblur_conf,
        "deblur_plate_like": deblur_like,
        "changed": original_text != deblur_text,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deblur + HyperLPR3 OCR on static plate images.")
    parser.add_argument("--input", required=True, type=Path, help="A plate crop image or a directory of plate crop images.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="Deblur ONNX model path.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output directory.")
    parser.add_argument("--recursive", action="store_true", help="Search image files recursively when --input is a directory.")
    parser.add_argument("--all-images", action="store_true", help="Process every image under --input. By default, directories only use plate_rank*.jpg.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max image count. 0 means no limit.")
    args = parser.parse_args()

    image_paths = collect_images(args.input, args.recursive, args.all_images)
    if args.limit > 0:
        image_paths = image_paths[: args.limit]
    if not image_paths:
        raise FileNotFoundError(f"No supported images found under: {args.input}")

    restored_dir = args.output / "restored"
    comparison_dir = args.output / "comparison"
    restored_dir.mkdir(parents=True, exist_ok=True)
    comparison_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading deblur model: {args.model}")
    deblur = PlateDeblurONNX(args.model)
    print("Loading HyperLPR3...")
    ocr = HyperLPR3OCR()

    rows: list[dict[str, Any]] = []
    root = args.input if args.input.is_dir() else None
    for image_path in image_paths:
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            print(f"[SKIP] unreadable: {image_path}")
            continue
        original_text, original_conf = recognize(ocr, image)
        restored = deblur.restore(image)
        deblur_text, deblur_conf = recognize(ocr, restored)

        name = safe_name(image_path, root)
        restored_path = restored_dir / f"{name}_deblur.jpg"
        comparison_path = comparison_dir / f"{name}_comparison.jpg"
        cv2.imwrite(str(restored_path), restored, [cv2.IMWRITE_JPEG_QUALITY, 95])
        cv2.imwrite(
            str(comparison_path),
            comparison_image(
                image,
                restored,
                f"{original_text or '-'} {original_conf:.3f}" if original_conf is not None else original_text or "-",
                f"{deblur_text or '-'} {deblur_conf:.3f}" if deblur_conf is not None else deblur_text or "-",
            ),
            [cv2.IMWRITE_JPEG_QUALITY, 95],
        )
        row = result_dict(image_path, restored_path, comparison_path, original_text, original_conf, deblur_text, deblur_conf)
        rows.append(row)
        print(
            f"[OK] {image_path.name} | original={original_text or '-'} "
            f"{original_conf if original_conf is not None else '-'} | "
            f"deblur={deblur_text or '-'} {deblur_conf if deblur_conf is not None else '-'}"
        )

    with (args.output / "results.json").open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    with (args.output / "results.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)

    print(f"Output directory: {args.output}")
    print(f"Restored images: {restored_dir}")
    print(f"Comparison images: {comparison_dir}")
    print(f"OCR results: {args.output / 'results.csv'}")


if __name__ == "__main__":
    main()
