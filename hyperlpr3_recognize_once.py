from __future__ import annotations

import argparse
import math
import site
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent
LOCAL_OCR_DEPS_DIR = PROJECT_DIR / "python_deps_ocr"
if LOCAL_OCR_DEPS_DIR.exists():
    site.addsitedir(str(LOCAL_OCR_DEPS_DIR))

import cv2

from benchmark_hyperlpr3_recognition import (
    clean_result,
    read_image,
    resolve_hyperlpr3_recognition_model,
)


DEFAULT_IMAGE = PROJECT_DIR / "Dataset" / "dataset" / "test" / "sharp" / "grab10003.jpg"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run HyperLPR3's recognition-only module on one rectified plate image "
            "and print preprocessing, ONNX inference, CTC decoding, and total OCR time."
        )
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=DEFAULT_IMAGE,
        help=f"rectified plate image (default: {DEFAULT_IMAGE})",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=0,
        help="unmeasured warm-up calls before the single timed call (default: 0)",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="show the input image; press Q or Esc to close",
    )
    args = parser.parse_args()
    if args.warmup < 0:
        parser.error("--warmup must be >= 0")
    return args


def elapsed_ms(started_ns: int) -> float:
    return (time.perf_counter_ns() - started_ns) / 1_000_000.0


def recognize_once(recognizer: Any, image: Any) -> dict[str, Any]:
    total_started = time.perf_counter_ns()

    started = time.perf_counter_ns()
    tensor = recognizer._preprocess(image)
    preprocess_ms = elapsed_ms(started)

    started = time.perf_counter_ns()
    raw_output = recognizer._run_session(tensor)
    inference_ms = elapsed_ms(started)

    started = time.perf_counter_ns()
    decoded = recognizer._postprocess(raw_output)
    decode_ms = elapsed_ms(started)

    total_ms = elapsed_ms(total_started)
    text, confidence = clean_result(decoded)
    if confidence is not None and not math.isfinite(float(confidence)):
        confidence = None
    return {
        "text": text,
        "confidence": float(confidence) if confidence is not None else None,
        "preprocess_ms": preprocess_ms,
        "inference_ms": inference_ms,
        "decode_ms": decode_ms,
        "total_ms": total_ms,
        "input_shape": list(tensor.shape),
    }


def print_result(
    *,
    image_path: Path,
    model_path: Path,
    model_load_ms: float,
    image_load_ms: float,
    warmup: int,
    result: dict[str, Any],
) -> None:
    confidence = result["confidence"]
    confidence_text = f"{confidence:.6f}" if confidence is not None else "None"
    print()
    print("=== HyperLPR3 纯识别单次结果 ===")
    print(f"图片: {image_path}")
    print(f"模型: {model_path}")
    print(f"识别文字: {result['text'] or '<empty>'}")
    print(f"置信度: {confidence_text}")
    print(f"模型输入: {result['input_shape']}")
    print(f"预热次数: {warmup}")
    print()
    print(f"模型加载:   {model_load_ms:9.3f} ms  (不计入OCR总耗时)")
    print(f"图片读取:   {image_load_ms:9.3f} ms  (不计入OCR总耗时)")
    print(f"OCR预处理:  {result['preprocess_ms']:9.3f} ms")
    print(f"ONNX推理:   {result['inference_ms']:9.3f} ms")
    print(f"CTC解码:    {result['decode_ms']:9.3f} ms")
    print(f"OCR总耗时:  {result['total_ms']:9.3f} ms")
    print("================================")


def show_image(image: Any) -> None:
    title = "HyperLPR3 recognition-only - Q/ESC to close"
    cv2.imshow(title, image)
    while True:
        key = cv2.waitKey(0) & 0xFF
        if key in (ord("q"), ord("Q"), 27):
            break
    cv2.destroyAllWindows()


def main() -> int:
    args = parse_args()
    image_path = args.image.resolve()

    started = time.perf_counter_ns()
    image = read_image(image_path)
    image_load_ms = elapsed_ms(started)

    import onnxruntime as ort
    from hyperlpr3.inference.recognition import PPRCNNRecognitionORT

    ort.set_default_logger_severity(3)
    model_path = resolve_hyperlpr3_recognition_model()
    started = time.perf_counter_ns()
    recognizer = PPRCNNRecognitionORT(str(model_path), input_size=(48, 160))
    model_load_ms = elapsed_ms(started)

    for _index in range(args.warmup):
        recognizer(image)

    result = recognize_once(recognizer, image)
    print_result(
        image_path=image_path,
        model_path=model_path,
        model_load_ms=model_load_ms,
        image_load_ms=image_load_ms,
        warmup=args.warmup,
        result=result,
    )
    if args.show:
        show_image(image)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        raise SystemExit(130)
