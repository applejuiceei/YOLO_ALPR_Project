from __future__ import annotations

import numbers
from pathlib import Path
from time import perf_counter_ns
from typing import Any

import numpy as np

from plate_rec_ocr import PlateRecONNX


class HyperLPR3OCR:
    """Small adapter around hyperlpr3.LicensePlateCatcher."""

    def __init__(self) -> None:
        try:
            import hyperlpr3 as lpr3
        except ImportError as exc:
            raise ImportError(
                "HyperLPR3 is not installed. Install it with: python -m pip install hyperlpr3"
            ) from exc
        self.catcher = lpr3.LicensePlateCatcher()

    def recognize(self, image: np.ndarray) -> tuple[str | None, float | None]:
        results = self.catcher(image)
        return self._parse_results(results)

    @staticmethod
    def _parse_results(results: Any) -> tuple[str | None, float | None]:
        if not results:
            return None, None

        best_text = None
        best_conf = None
        for item in results:
            text = None
            confidence = None
            if isinstance(item, dict):
                text = item.get("code") or item.get("plate") or item.get("text")
                confidence = item.get("confidence") or item.get("score") or item.get("text_confidence")
            elif isinstance(item, (list, tuple)) and item:
                text = item[0]
                if len(item) > 1 and isinstance(item[1], numbers.Real):
                    confidence = float(item[1])
                else:
                    for value in item[1:]:
                        if isinstance(value, numbers.Real):
                            confidence = float(value)
                            break

            if not text:
                continue
            text = PlateRecONNX.clean_plate_text(str(text))
            if not text:
                continue
            if best_text is None or (confidence is not None and (best_conf is None or confidence > best_conf)):
                best_text = text
                best_conf = confidence

        return best_text, best_conf


class HyperLPR3RecognitionOCR:
    """Adapter around HyperLPR3's recognition-only ONNX model."""

    def __init__(self, model_path: str | Path | None = None) -> None:
        try:
            import onnxruntime as ort
            from hyperlpr3.config.settings import _DEFAULT_FOLDER_, onnx_runtime_config
            from hyperlpr3.inference.recognition import PPRCNNRecognitionORT
        except ImportError as exc:
            raise ImportError(
                "HyperLPR3 is not installed. Install it with: python -m pip install hyperlpr3"
            ) from exc

        ort.set_default_logger_severity(3)

        if model_path is None:
            resolved_model_path = (
                Path(_DEFAULT_FOLDER_) / onnx_runtime_config["rec_model_path"]
            ).resolve()
        else:
            resolved_model_path = Path(model_path).expanduser().resolve()
        if not resolved_model_path.is_file():
            raise FileNotFoundError(
                f"HyperLPR3 recognition model not found: {resolved_model_path}"
            )

        self.model_path = resolved_model_path
        self.recognizer = PPRCNNRecognitionORT(
            str(self.model_path), input_size=(48, 160)
        )
        self.last_ocr_ms: float | None = None

    def recognize(self, image: np.ndarray) -> tuple[str | None, float | None]:
        self.last_ocr_ms = None
        if not isinstance(image, np.ndarray):
            raise TypeError("image must be a numpy.ndarray")
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("image must be a non-empty HWC array with exactly 3 channels")
        if image.size == 0 or image.shape[0] <= 0 or image.shape[1] <= 0:
            raise ValueError("image must be a non-empty HWC array with exactly 3 channels")

        started_ns = perf_counter_ns()
        try:
            text, confidence = self.recognizer(image)
        finally:
            self.last_ocr_ms = (perf_counter_ns() - started_ns) / 1_000_000.0

        cleaned_text = PlateRecONNX.clean_plate_text(str(text)) if text else ""
        if not cleaned_text:
            return None, None

        finite_confidence = float(confidence)
        if not np.isfinite(finite_confidence):
            raise ValueError(
                f"HyperLPR3 recognition returned a non-finite confidence: {confidence!r}"
            )
        return cleaned_text, finite_confidence
