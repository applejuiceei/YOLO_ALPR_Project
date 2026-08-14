from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np


DEFAULT_REC_MODEL = r"D:\YOLO_ALPR_Project\RK3588_dev\plate_rec_sim.onnx"
DEFAULT_DICT = r"D:\YOLO_ALPR_Project\RK3588_dev\dict.txt"
PROVINCES = set(
    "\u4eac\u6d25\u6caa\u6e1d\u5180\u8c6b\u4e91\u8fbd\u9ed1\u6e58\u7696\u9c81\u65b0\u82cf"
    "\u6d59\u8d63\u9102\u6842\u7518\u664b\u8499\u9655\u5409\u95fd\u8d35\u7ca4\u9752\u85cf"
    "\u5ddd\u5b81\u743c"
)


class PlateRecONNX:
    """Wrapper for the RK3588 plate recognition ONNX model."""

    def __init__(
        self,
        model_path: str | Path = DEFAULT_REC_MODEL,
        dict_path: str | Path = DEFAULT_DICT,
        backend: str = "auto",
    ) -> None:
        self.model_path = Path(model_path)
        self.dict_path = Path(dict_path)
        self.charset = self._load_dict(self.dict_path)
        self.backend = backend
        self.net = None
        self.session = None
        self.input_name = None

        if backend in ("auto", "onnxruntime", "ort"):
            try:
                import onnxruntime as ort

                self.session = ort.InferenceSession(str(self.model_path), providers=["CPUExecutionProvider"])
                self.input_name = self.session.get_inputs()[0].name
                self.backend = "onnxruntime"
                return
            except Exception:
                if backend in ("onnxruntime", "ort"):
                    raise

        if backend in ("auto", "cv2", "opencv"):
            self.net = cv2.dnn.readNetFromONNX(str(self.model_path))
            self.backend = "cv2"
            return

        raise ValueError(f"Unsupported plate-rec backend: {backend}")

    @staticmethod
    def _load_dict(path: Path) -> list[str]:
        chars = ["blank"]
        chars.extend(path.read_text(encoding="utf-8").splitlines())
        chars.append(" ")
        return chars

    @staticmethod
    def _preprocess(image: np.ndarray) -> np.ndarray:
        resized = cv2.resize(image, (320, 48), interpolation=cv2.INTER_LINEAR)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        return np.transpose(rgb.astype(np.float32), (2, 0, 1))[None]

    @staticmethod
    def clean_plate_text(text: str) -> str:
        text = PlateRecONNX.repair_mojibake(text.strip().upper().replace(" ", ""))
        return re.sub(r"[^0-9A-Z\u4e00-\u9fff]", "", text)

    @staticmethod
    def repair_mojibake(text: str) -> str:
        repaired: list[str] = []
        index = 0
        while index < len(text):
            if index + 1 < len(text) and ord(text[index]) <= 255 and ord(text[index + 1]) <= 255:
                try:
                    decoded = bytes([ord(text[index]), ord(text[index + 1])]).decode("gbk")
                    if "\u4e00" <= decoded <= "\u9fff":
                        repaired.append(decoded)
                        index += 2
                        continue
                except UnicodeDecodeError:
                    pass
            repaired.append(text[index])
            index += 1
        return "".join(repaired)

    @staticmethod
    def is_plate_like(text: str) -> bool:
        if len(text) not in (7, 8):
            return False
        if text[0] not in PROVINCES:
            return False
        if not ("A" <= text[1] <= "Z"):
            return False
        return all(ch.isdigit() or ("A" <= ch <= "Z") for ch in text[2:])

    def recognize(self, image: np.ndarray) -> tuple[str | None, float | None]:
        blob = self._preprocess(image)
        if self.backend == "onnxruntime":
            output = self.session.run(None, {self.input_name: blob})[0]
        else:
            self.net.setInput(blob)
            output = self.net.forward()

        text, confidence = self._ctc_decode(output)
        text = self.clean_plate_text(text)
        if not text:
            return None, None
        return text, confidence

    def _ctc_decode(self, output: np.ndarray) -> tuple[str, float | None]:
        scores = np.asarray(output)
        if scores.ndim == 3:
            scores = scores[0]
        if scores.ndim != 2:
            raise ValueError(f"Unexpected recognition output shape: {output.shape}")

        if scores.shape[1] != len(self.charset) and scores.shape[0] == len(self.charset):
            scores = scores.T

        indices = scores.argmax(axis=1)
        max_scores = scores.max(axis=1)
        result: list[str] = []
        result_scores: list[float] = []
        previous = 0
        for idx, score in zip(indices, max_scores):
            idx_int = int(idx)
            if idx_int != 0 and idx_int != previous and idx_int < len(self.charset):
                result.append(self.charset[idx_int])
                result_scores.append(float(score))
            previous = idx_int

        confidence = float(np.mean(result_scores)) if result_scores else None
        return "".join(result), confidence
