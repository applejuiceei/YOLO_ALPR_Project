from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np


def load_characters(path: str | Path, use_space_char: bool = False) -> list[str]:
    characters = Path(path).read_text(encoding="utf-8").splitlines()
    if not characters:
        raise ValueError(f"empty character dictionary: {path}")
    if any(len(character) != 1 for character in characters):
        raise ValueError("each dictionary line must contain exactly one character")
    if len(set(characters)) != len(characters):
        raise ValueError(f"duplicate entries in character dictionary: {path}")
    if use_space_char:
        characters.append(" ")
    return characters


def preprocess_plate(
    image: np.ndarray,
    target_height: int = 48,
    target_width: int = 160,
    color_order: str = "rgb",
) -> np.ndarray:
    """Match PaddleOCR RecResizeImg: aspect resize, zero pad, then [-1, 1]."""
    if image is None or image.size == 0 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("plate image must be a non-empty HWC BGR image")
    if target_height <= 0 or target_width <= 0:
        raise ValueError("target dimensions must be positive")
    if color_order not in {"bgr", "rgb"}:
        raise ValueError("color_order must be 'bgr' or 'rgb'")

    source_height, source_width = image.shape[:2]
    resized_width = min(
        target_width,
        max(1, int(math.ceil(target_height * source_width / max(1, source_height)))),
    )
    resized = cv2.resize(image, (resized_width, target_height), interpolation=cv2.INTER_LINEAR)
    if color_order == "rgb":
        resized = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    normalized = resized.astype(np.float32) / 127.5 - 1.0
    chw = np.transpose(normalized, (2, 0, 1))
    padded = np.zeros((3, target_height, target_width), dtype=np.float32)
    padded[:, :, :resized_width] = chw
    return np.ascontiguousarray(padded[None])


def _as_probabilities(scores: np.ndarray) -> np.ndarray:
    row_sums = scores.sum(axis=1)
    looks_like_probabilities = (
        float(scores.min()) >= -1e-5
        and float(scores.max()) <= 1.00001
        and np.allclose(row_sums, 1.0, rtol=1e-3, atol=1e-3)
    )
    if looks_like_probabilities:
        return scores
    shifted = scores - scores.max(axis=1, keepdims=True)
    exponential = np.exp(shifted)
    return exponential / np.maximum(exponential.sum(axis=1, keepdims=True), 1e-12)


def ctc_decode(
    output: np.ndarray | Sequence[np.ndarray], characters: Sequence[str]
) -> tuple[str, float]:
    if isinstance(output, (list, tuple)):
        if not output:
            return "", 0.0
        output = output[0]
    scores = np.asarray(output)
    if scores.ndim == 3:
        if scores.shape[0] != 1:
            raise ValueError(f"batch size must be 1, got output shape {scores.shape}")
        scores = scores[0]
    if scores.ndim != 2:
        raise ValueError(f"expected 2D CTC scores, got output shape {scores.shape}")

    expected_classes = len(characters) + 1
    if scores.shape[1] != expected_classes and scores.shape[0] == expected_classes:
        scores = scores.T
    if scores.shape[1] != expected_classes:
        raise ValueError(
            f"model has {scores.shape[1]} classes but dictionary requires {expected_classes} "
            "including CTC blank"
        )

    probabilities = _as_probabilities(scores.astype(np.float32, copy=False))
    indices = probabilities.argmax(axis=1)
    maxima = probabilities.max(axis=1)
    text: list[str] = []
    confidences: list[float] = []
    previous = 0
    for index, confidence in zip(indices, maxima):
        class_index = int(index)
        if class_index != 0 and class_index != previous:
            text.append(characters[class_index - 1])
            confidences.append(float(confidence))
        previous = class_index
    return "".join(text).strip(), float(np.mean(confidences)) if confidences else 0.0


class PlateCTCRecognizer:
    """ONNX Runtime adapter shared by the generic baseline and future plate model."""

    def __init__(
        self,
        model_path: str | Path,
        dict_path: str | Path,
        *,
        color_order: str = "rgb",
        use_space_char: bool = False,
        threads: int = 0,
        providers: Sequence[str] | None = None,
    ) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise ImportError("onnxruntime is required for PlateCTCRecognizer") from exc

        self.model_path = Path(model_path).resolve()
        self.dict_path = Path(dict_path).resolve()
        self.characters = load_characters(self.dict_path, use_space_char=use_space_char)
        self.color_order = color_order

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.inter_op_num_threads = 1
        if threads > 0:
            options.intra_op_num_threads = threads
        self.session = ort.InferenceSession(
            str(self.model_path),
            sess_options=options,
            providers=list(providers or ["CPUExecutionProvider"]),
        )
        self.input = self.session.get_inputs()[0]
        self.output = self.session.get_outputs()[0]
        shape = self.input.shape
        if len(shape) != 4 or not isinstance(shape[2], int) or not isinstance(shape[3], int):
            raise ValueError(f"recognition model must have fixed NCHW input, got {shape}")
        self.target_height = int(shape[2])
        self.target_width = int(shape[3])

        output_shape = self.output.shape
        if len(output_shape) >= 1 and isinstance(output_shape[-1], int):
            expected_classes = len(self.characters) + 1
            if int(output_shape[-1]) != expected_classes:
                raise ValueError(
                    f"model output has {output_shape[-1]} classes; dictionary and blank require "
                    f"{expected_classes}"
                )

    def prepare(self, image: np.ndarray) -> np.ndarray:
        return preprocess_plate(
            image,
            target_height=self.target_height,
            target_width=self.target_width,
            color_order=self.color_order,
        )

    def infer_scores(self, tensor: np.ndarray) -> np.ndarray:
        return np.asarray(
            self.session.run([self.output.name], {self.input.name: tensor})[0]
        )

    def recognize(self, image: np.ndarray) -> tuple[str, float]:
        return ctc_decode(self.infer_scores(self.prepare(image)), self.characters)

    def metadata(self) -> dict[str, Any]:
        return {
            "model": str(self.model_path),
            "dictionary": str(self.dict_path),
            "character_count_without_blank": len(self.characters),
            "input_name": self.input.name,
            "input_shape": self.input.shape,
            "output_name": self.output.name,
            "output_shape": self.output.shape,
            "color_order": self.color_order,
        }
