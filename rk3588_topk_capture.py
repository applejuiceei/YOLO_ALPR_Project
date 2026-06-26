"""RK3588/RKNN implementation of the current Top-K ALPR capture workflow.

Run this file on the board. It intentionally uses only rknnlite, OpenCV, and
NumPy so the policy layer can stay close to alpr_topk_capture.py without
requiring Ultralytics or PyTorch on the RK3588.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from rknnlite.api import RKNNLite


PLATE_WIDTH = 320
PLATE_HEIGHT = 96
VEHICLE_CLASSES = {2, 5, 7}


@dataclass
class Candidate:
    frame_idx: int
    track_id: int
    score: float
    subscores: dict[str, float]
    metrics: dict[str, float]
    obb_score: float
    plate_area: float
    corners: list[list[float]]
    vehicle_box: list[int]
    vehicle_conf: float
    full_frame: np.ndarray = field(repr=False)
    vehicle_crop: np.ndarray = field(repr=False)
    plate_crop: np.ndarray = field(repr=False)
    ocr_text: str | None = None
    ocr_conf: float | None = None
    ocr_raw_text: str | None = None
    ocr_raw_conf: float | None = None
    ocr_engine: str | None = None


@dataclass
class RejectedCandidate:
    frame_idx: int
    track_id: int
    reason: str
    obb_score: float
    plate_area: float
    geometry: dict[str, float]
    vehicle_conf: float
    vehicle_box: list[int]
    plate_corners: list[list[float]]
    full_frame: np.ndarray = field(repr=False)
    vehicle_crop: np.ndarray = field(repr=False)
    plate_crop: np.ndarray = field(repr=False)


@dataclass
class TrackState:
    candidates: list[Candidate] = field(default_factory=list)
    rejected_candidates: list[RejectedCandidate] = field(default_factory=list)
    rejected: Counter[str] = field(default_factory=Counter)
    seen_frames: int = 0
    plate_hits: int = 0
    vote_history: deque[str] = field(default_factory=deque)
    vote_events: deque[dict[str, Any]] = field(default_factory=deque)
    vote_counts: Counter[str] = field(default_factory=Counter)
    locked_text: str | None = None
    locked_confidence: float | None = None
    locked_frame: int | None = None
    locked_consensus: dict[str, Any] | None = None
    phase: str = "NEW"
    lock_deferred_reason: str | None = None
    lock_attempts: int = 0
    plate_anchor: dict[str, float] | None = None
    locked_plate_anchor: dict[str, float] | None = None
    last_box: list[int] | None = None
    last_detection_frame: int | None = None
    last_vehicle_conf: float = 0.0
    velocity_xyxy: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    kalman: Any = field(default=None, repr=False)
    last_plate_attempt_frame: int | None = None
    plate_attempts: int = 0


class BoxKalmanFilter:
    """Constant-velocity Kalman filter over vehicle center, size, and their velocities."""

    def __init__(self, box: list[int]) -> None:
        cx, cy, width, height = self._xyxy_to_measurement(box)
        self.x = np.array([[cx], [cy], [width], [height], [0.0], [0.0], [0.0], [0.0]], dtype=np.float32)
        self.p = np.eye(8, dtype=np.float32) * 25.0
        self.q = np.eye(8, dtype=np.float32) * 0.06
        self.r = np.diag([16.0, 16.0, 25.0, 25.0]).astype(np.float32)
        self.h = np.zeros((4, 8), dtype=np.float32)
        self.h[0, 0] = self.h[1, 1] = self.h[2, 2] = self.h[3, 3] = 1.0

    @staticmethod
    def _xyxy_to_measurement(box: list[int]) -> tuple[float, float, float, float]:
        x1, y1, x2, y2 = [float(value) for value in box]
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)
        return x1 + width * 0.5, y1 + height * 0.5, width, height

    @staticmethod
    def _transition(delta_frames: int) -> np.ndarray:
        dt = float(max(1, delta_frames))
        f = np.eye(8, dtype=np.float32)
        for index in range(4):
            f[index, index + 4] = dt
        return f

    def update(self, box: list[int], delta_frames: int) -> None:
        f = self._transition(delta_frames)
        self.x = f @ self.x
        self.p = f @ self.p @ f.T + self.q * float(max(1, delta_frames))
        z = np.array(self._xyxy_to_measurement(box), dtype=np.float32).reshape(4, 1)
        innovation = z - self.h @ self.x
        s = self.h @ self.p @ self.h.T + self.r
        k = self.p @ self.h.T @ np.linalg.inv(s)
        self.x = self.x + k @ innovation
        self.p = (np.eye(8, dtype=np.float32) - k @ self.h) @ self.p

    def predicted_box(self, delta_frames: int, frame_shape: tuple[int, int, int]) -> list[int] | None:
        f = self._transition(delta_frames)
        x = f @ self.x
        cx, cy, width, height = [float(value) for value in x[:4, 0]]
        if width < 2.0 or height < 2.0:
            return None
        h, w = frame_shape[:2]
        x1 = int(round(cx - width * 0.5))
        y1 = int(round(cy - height * 0.5))
        x2 = int(round(cx + width * 0.5))
        y2 = int(round(cy + height * 0.5))
        x1 = max(0, min(w - 1, x1))
        y1 = max(0, min(h - 1, y1))
        x2 = max(x1 + 1, min(w, x2))
        y2 = max(y1 + 1, min(h, y2))
        return [x1, y1, x2, y2]

    def snapshot(self) -> dict[str, list[float]]:
        return {
            "cx_cy_w_h": [round(float(value), 3) for value in self.x[:4, 0]],
            "vx_vy_vw_vh": [round(float(value), 3) for value in self.x[4:, 0]],
        }


class RKNNRunner:
    def __init__(self, path: Path, name: str) -> None:
        self.name = name
        self.rknn = RKNNLite(verbose=False)
        ret = self.rknn.load_rknn(str(path))
        if ret != 0:
            raise RuntimeError(f"{name}: load_rknn failed ({ret}): {path}")
        ret = self.rknn.init_runtime()
        if ret != 0:
            raise RuntimeError(f"{name}: init_runtime failed ({ret})")

    def infer_rgb(self, image_rgb: np.ndarray) -> np.ndarray:
        output = self.rknn.inference(inputs=[np.ascontiguousarray(image_rgb[None, ...])])
        if not output:
            raise RuntimeError(f"{self.name}: empty RKNN output")
        return np.asarray(output[0], dtype=np.float32)

    def close(self) -> None:
        self.rknn.release()


class V4L2CtlCapture:
    """Use v4l2-ctl's mmap streamer because this board's OpenCV V4L2 path drops to about 10 FPS."""

    def __init__(self, device: str, width: int, height: int, fourcc: str, color_mode: str) -> None:
        self.width = width
        self.height = height
        self.fourcc = fourcc
        self.color_mode = color_mode
        self.frame_size = width * height * 2 if color_mode == "uyvy" else width * height * 3 // 2
        command = [
            "v4l2-ctl",
            "-d",
            device,
            f"--set-fmt-video=width={width},height={height},pixelformat={fourcc}",
            "--stream-mmap=4",
            "--stream-to=-",
        ]
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)

    def _read_exact(self, size: int) -> bytes:
        if self.process.stdout is None:
            return b""
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            data = self.process.stdout.read(remaining)
            if not data:
                return b""
            chunks.append(data)
            remaining -= len(data)
        return b"".join(chunks)

    def read(self) -> tuple[bool, np.ndarray | None]:
        data = self._read_exact(self.frame_size)
        if len(data) != self.frame_size:
            return False, None
        raw = np.frombuffer(data, dtype=np.uint8)
        return True, decode_mipi_frame(raw, self.width, self.height, self.color_mode)

    def isOpened(self) -> bool:
        return self.process.poll() is None

    def get(self, property_id: int) -> float:
        if property_id == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self.width)
        if property_id == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self.height)
        if property_id == cv2.CAP_PROP_FPS:
            return 30.0
        return 0.0

    def release(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)


class SimpleIoUTracker:
    def __init__(self, iou_threshold: float, max_age: int, center_threshold: float = 0.70) -> None:
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.center_threshold = center_threshold
        self.next_id = 1
        self.tracks: dict[int, dict[str, Any]] = {}

    @staticmethod
    def iou(a: np.ndarray, b: np.ndarray) -> float:
        x1, y1 = max(a[0], b[0]), max(a[1], b[1])
        x2, y2 = min(a[2], b[2]), min(a[3], b[3])
        inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        union = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1]) + max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1]) - inter
        return float(inter / union) if union > 0 else 0.0

    @staticmethod
    def center_affinity(a: np.ndarray, b: np.ndarray) -> float:
        acx, acy = (a[0] + a[2]) * 0.5, (a[1] + a[3]) * 0.5
        bcx, bcy = (b[0] + b[2]) * 0.5, (b[1] + b[3]) * 0.5
        aw, ah = max(1.0, a[2] - a[0]), max(1.0, a[3] - a[1])
        bw, bh = max(1.0, b[2] - b[0]), max(1.0, b[3] - b[1])
        norm = max(20.0, 0.5 * (aw + ah + bw + bh))
        distance = math.hypot(acx - bcx, acy - bcy)
        scale_ratio = min(aw * ah, bw * bh) / max(aw * ah, bw * bh)
        return max(0.0, 1.0 - distance / norm) * max(0.0, scale_ratio)

    def update(self, boxes: np.ndarray, confidences: np.ndarray, frame_idx: int) -> list[tuple[int, np.ndarray, float]]:
        matches = []
        for tid, track in self.tracks.items():
            for did, box in enumerate(boxes):
                iou_score = self.iou(track["box"], box)
                center_score = self.center_affinity(track["box"], box)
                score = max(iou_score, 0.85 * center_score)
                matches.append((tid, did, score, iou_score, center_score))
        assigned_tracks: set[int] = set()
        assigned_detections: set[int] = set()
        for track_id, det_id, score, iou_score, center_score in sorted(matches, key=lambda item: item[2], reverse=True):
            if iou_score < self.iou_threshold and center_score < self.center_threshold:
                continue
            if track_id in assigned_tracks or det_id in assigned_detections:
                continue
            self.tracks[track_id] = {"box": boxes[det_id].astype(np.float32), "conf": float(confidences[det_id]), "last_seen": frame_idx}
            assigned_tracks.add(track_id)
            assigned_detections.add(det_id)
        for det_id, box in enumerate(boxes):
            if det_id in assigned_detections:
                continue
            track_id = self.next_id
            self.next_id += 1
            self.tracks[track_id] = {"box": box.astype(np.float32), "conf": float(confidences[det_id]), "last_seen": frame_idx}
            assigned_tracks.add(track_id)
        stale = [track_id for track_id, track in self.tracks.items() if frame_idx - track["last_seen"] > self.max_age]
        for track_id in stale:
            del self.tracks[track_id]
        return [(track_id, self.tracks[track_id]["box"].copy(), self.tracks[track_id]["conf"]) for track_id in sorted(assigned_tracks)]

def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def order_points(points: np.ndarray) -> np.ndarray:
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    ordered = points[np.argsort(angles)]
    return np.roll(ordered, -np.argmin(ordered.sum(axis=1)), axis=0).astype(np.float32)


def polygon_area(points: np.ndarray) -> float:
    return float(cv2.contourArea(points.astype(np.float32)))


def geometry(points: np.ndarray) -> dict[str, float]:
    rect = order_points(points)
    width = float((np.linalg.norm(rect[1] - rect[0]) + np.linalg.norm(rect[2] - rect[3])) / 2.0)
    height = float((np.linalg.norm(rect[3] - rect[0]) + np.linalg.norm(rect[2] - rect[1])) / 2.0)
    center = rect.mean(axis=0)
    return {"width": width, "height": height, "aspect": width / max(1e-6, height), "center_x": float(center[0]), "center_y": float(center[1])}


def plate_overlap(points: np.ndarray, vehicle_box: list[int]) -> float:
    px1, py1 = points.min(axis=0)
    px2, py2 = points.max(axis=0)
    vx1, vy1, vx2, vy2 = vehicle_box
    inter = max(0.0, min(px2, vx2) - max(px1, vx1)) * max(0.0, min(py2, vy2) - max(py1, vy1))
    return float(inter / max(1.0, (px2 - px1) * (py2 - py1)))


def safe_crop(image: np.ndarray, box: list[int]) -> np.ndarray:
    height, width = image.shape[:2]
    x1, y1, x2, y2 = box
    x1, x2 = max(0, min(width, x1)), max(0, min(width, x2))
    y1, y2 = max(0, min(height, y1)), max(0, min(height, y2))
    return image[y1:y2, x1:x2].copy() if x2 > x1 and y2 > y1 else np.empty((0, 0, 3), dtype=image.dtype)


class PlateLabelRenderer:
    """Render cached Unicode labels without converting every video frame through Pillow."""

    def __init__(self, font_path: Path | None, font_size: int) -> None:
        self.font_path = font_path
        self.font_size = font_size
        self.cache: dict[tuple[str, tuple[int, int, int]], np.ndarray] = {}
        self._font: Any | None = None
        self._available: bool | None = None

    def _get_font(self) -> Any | None:
        if self._available is False:
            return None
        if self._font is not None:
            return self._font
        try:
            from PIL import ImageFont

            if self.font_path is None or not self.font_path.exists():
                raise FileNotFoundError("CJK font file is unavailable")
            self._font = ImageFont.truetype(str(self.font_path), self.font_size)
            self._available = True
            return self._font
        except Exception as exc:
            if self._available is not False:
                print(f"WARNING: Unicode label rendering disabled: {exc}", flush=True)
            self._available = False
            return None

    def draw(self, frame: np.ndarray, text: str, origin: tuple[int, int], color: tuple[int, int, int]) -> None:
        font = self._get_font()
        if font is None:
            safe_text = text.encode("ascii", "replace").decode("ascii")
            cv2.putText(frame, safe_text, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
            return
        key = (text, color)
        sprite = self.cache.get(key)
        if sprite is None:
            from PIL import Image, ImageDraw

            probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
            draw = ImageDraw.Draw(probe)
            bbox = draw.textbbox((0, 0), text, font=font, stroke_width=1)
            width, height = bbox[2] - bbox[0] + 12, bbox[3] - bbox[1] + 10
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 190))
            draw = ImageDraw.Draw(canvas)
            draw.text((6 - bbox[0], 4 - bbox[1]), text, font=font, fill=(color[2], color[1], color[0], 255), stroke_width=1, stroke_fill=(0, 0, 0, 255))
            sprite = cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGBA2BGRA)
            self.cache[key] = sprite
        x, y = origin
        x = max(0, min(frame.shape[1] - 1, x))
        y = max(0, min(frame.shape[0] - 1, y - sprite.shape[0]))
        width = min(sprite.shape[1], frame.shape[1] - x)
        height = min(sprite.shape[0], frame.shape[0] - y)
        if width <= 0 or height <= 0:
            return
        patch, source = frame[y : y + height, x : x + width], sprite[:height, :width]
        alpha = source[:, :, 3:4].astype(np.float32) / 255.0
        patch[:] = (source[:, :, :3] * alpha + patch * (1.0 - alpha)).astype(np.uint8)


def decode_mipi_frame(raw: np.ndarray, width: int, height: int, mode: str) -> np.ndarray:
    """Turn V4L2 raw UYVY/NV12/NV21 data into BGR, or retain OpenCV-converted BGR."""
    if mode == "opencv":
        if raw.ndim != 3 or raw.shape[2] != 3:
            raise ValueError(f"OpenCV MIPI conversion returned unexpected shape: {raw.shape}")
        return raw
    expected_size = width * height * 2 if mode == "uyvy" else width * height * 3 // 2
    if raw.size != expected_size:
        raise ValueError(
            f"MIPI {mode} buffer size mismatch: got {raw.size}, expected {expected_size} for {width}x{height}."
        )
    if mode == "uyvy":
        packed = raw.reshape(height, width, 2)
        code = cv2.COLOR_YUV2BGR_UYVY
    else:
        packed = raw.reshape(height * 3 // 2, width)
        code = cv2.COLOR_YUV2BGR_NV12 if mode == "nv12" else cv2.COLOR_YUV2BGR_NV21
    return cv2.cvtColor(packed, code)


def gray_world_white_balance(frame: np.ndarray) -> np.ndarray:
    means = frame.reshape(-1, 3).mean(axis=0)
    target = float(means.mean())
    gains = np.clip(target / np.maximum(means, 1.0), 0.5, 2.5)
    return np.clip(frame.astype(np.float32) * gains, 0, 255).astype(np.uint8)


def warp_plate(frame: np.ndarray, corners: np.ndarray) -> np.ndarray:
    rect = order_points(corners)
    rect += np.array([[-5, -5], [5, -5], [5, 5], [-5, 5]], dtype=np.float32)
    destination = np.array([[0, 0], [PLATE_WIDTH - 1, 0], [PLATE_WIDTH - 1, PLATE_HEIGHT - 1], [0, PLATE_HEIGHT - 1]], dtype=np.float32)
    return cv2.warpPerspective(frame, cv2.getPerspectiveTransform(rect, destination), (PLATE_WIDTH, PLATE_HEIGHT))


def quality_score(plate: np.ndarray, plate_area: float, obb_score: float) -> tuple[float, dict[str, float], dict[str, float]]:
    gray = cv2.cvtColor(plate, cv2.COLOR_BGR2GRAY)
    laplacian = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    contrast = float(gray.std())
    clipped = float(np.mean((gray <= 8) | (gray >= 247)))
    subscores = {
        "plate_area_score": clamp01(plate_area / 5000.0),
        "sharpness_score": clamp01(math.log1p(laplacian) / math.log1p(1000.0)),
        "exposure_score": clamp01(1.0 - clipped * 2.0),
        "contrast_score": clamp01(contrast / 64.0),
        "obb_score": clamp01(obb_score),
    }
    score = 0.35 * subscores["plate_area_score"] + 0.30 * subscores["sharpness_score"] + 0.15 * subscores["exposure_score"] + 0.10 * subscores["contrast_score"] + 0.10 * subscores["obb_score"]
    return score, subscores, {"plate_area": plate_area, "laplacian_variance": laplacian, "gray_std": contrast, "clipped_ratio": clipped, "obb_confidence": obb_score}


def decode_vehicle(output: np.ndarray, frame_shape: tuple[int, int, int], confidence: float, nms_iou: float) -> tuple[np.ndarray, np.ndarray]:
    data = np.squeeze(output)
    if data.shape == (84, 8400):
        data = data.T
    if data.ndim != 2 or data.shape[1] < 8:
        raise ValueError(f"Unexpected vehicle output shape: {output.shape}")
    model_h = model_w = 640.0
    frame_h, frame_w = frame_shape[:2]
    candidates: list[list[float]] = []
    scores: list[float] = []
    classes: list[int] = []
    for row in data:
        class_id = int(np.argmax(row[4:]))
        score = float(row[4 + class_id])
        if class_id not in VEHICLE_CLASSES or score < confidence:
            continue
        cx, cy, width, height = row[:4]
        x1 = max(0.0, (cx - width / 2.0) * frame_w / model_w)
        y1 = max(0.0, (cy - height / 2.0) * frame_h / model_h)
        x2 = min(float(frame_w), (cx + width / 2.0) * frame_w / model_w)
        y2 = min(float(frame_h), (cy + height / 2.0) * frame_h / model_h)
        if x2 > x1 and y2 > y1:
            candidates.append([x1, y1, x2 - x1, y2 - y1])
            scores.append(score)
            classes.append(class_id)
    keep: list[int] = []
    for class_id in VEHICLE_CLASSES:
        indices = [index for index, value in enumerate(classes) if value == class_id]
        if not indices:
            continue
        chosen = cv2.dnn.NMSBoxes([candidates[index] for index in indices], [scores[index] for index in indices], confidence, nms_iou)
        keep.extend(indices[int(index)] for index in np.asarray(chosen).reshape(-1))
    boxes = np.array([[candidates[index][0], candidates[index][1], candidates[index][0] + candidates[index][2], candidates[index][1] + candidates[index][3]] for index in keep], dtype=np.float32)
    return boxes, np.array([scores[index] for index in keep], dtype=np.float32)


def decode_obbs(output: np.ndarray, roi: np.ndarray, roi_origin: tuple[int, int], model_size: int, threshold: float) -> list[tuple[np.ndarray, float]]:
    data = np.squeeze(output)
    if data.ndim == 2 and data.shape[0] == 6:
        data = data.T
    if data.ndim != 2 or data.shape[1] != 6:
        raise ValueError(f"Unexpected OBB output shape: {output.shape}")
    scale_x, scale_y = roi.shape[1] / float(model_size), roi.shape[0] / float(model_size)
    ox, oy = roi_origin
    results: list[tuple[np.ndarray, float]] = []
    for cx, cy, width, height, score, angle in data:
        if score < threshold:
            continue
        cx, cy, width, height = cx * scale_x, cy * scale_y, width * scale_x, height * scale_y
        cos_a, sin_a = math.cos(float(angle)), math.sin(float(angle))
        half_w, half_h = width / 2.0, height / 2.0
        corners = np.array(
            [
                [cx - half_w * cos_a + half_h * sin_a, cy - half_w * sin_a - half_h * cos_a],
                [cx + half_w * cos_a + half_h * sin_a, cy + half_w * sin_a - half_h * cos_a],
                [cx + half_w * cos_a - half_h * sin_a, cy + half_w * sin_a + half_h * cos_a],
                [cx - half_w * cos_a - half_h * sin_a, cy - half_w * sin_a + half_h * cos_a],
            ],
            dtype=np.float32,
        )
        corners += np.array([ox, oy], dtype=np.float32)
        results.append((order_points(corners), float(score)))
    return sorted(results, key=lambda item: item[1], reverse=True)


def load_dictionary(path: Path) -> list[str]:
    return [""] + [line.rstrip("\r\n") for line in path.read_text(encoding="utf-8").splitlines()] + [" "]


def decode_ocr(output: np.ndarray, dictionary: list[str]) -> tuple[str, float]:
    probabilities = np.squeeze(output)
    if probabilities.ndim != 2:
        raise ValueError(f"Unexpected OCR output shape: {output.shape}")
    indices = probabilities.argmax(axis=1)
    confidence_values = probabilities.max(axis=1)
    text_parts: list[str] = []
    kept_confidences: list[float] = []
    previous = 0
    for index, confidence in zip(indices, confidence_values):
        index = int(index)
        if index != 0 and index != previous and index < len(dictionary):
            text_parts.append(dictionary[index])
            kept_confidences.append(float(confidence))
        previous = index
    return "".join(text_parts).strip(), float(np.mean(kept_confidences)) if kept_confidences else 0.0


def clean_plate_text(text: str) -> str:
    text = repair_mojibake(text.strip().upper().replace(" ", ""))
    return "".join(char for char in text if char.isdigit() or ("A" <= char <= "Z") or "\u4e00" <= char <= "\u9fff")


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


def build_hyperlpr3() -> Any:
    try:
        import hyperlpr3 as lpr3
    except ImportError as exc:
        raise ImportError("HyperLPR3 is unavailable. Install on the board: python3 -m pip install onnxruntime hyperlpr3") from exc
    return lpr3.LicensePlateCatcher()


def recognize_hyperlpr3(catcher: Any, image: np.ndarray) -> tuple[str, float]:
    best_text, best_confidence = "", 0.0
    for item in catcher(image) or []:
        if not isinstance(item, (list, tuple)) or not item:
            continue
        text = clean_plate_text(str(item[0]))
        confidence = float(item[1]) if len(item) > 1 and isinstance(item[1], (float, int, np.floating)) else 0.0
        if text and confidence > best_confidence:
            best_text, best_confidence = text, confidence
    return best_text, best_confidence


def vehicle_ready(box: list[int], confidence: float, frame: np.ndarray, args: argparse.Namespace) -> tuple[bool, str]:
    return vehicle_ready_for_shape(box, confidence, frame.shape, args)


def vehicle_ready_for_shape(
    box: list[int],
    confidence: float,
    frame_shape: tuple[int, int, int],
    args: argparse.Namespace,
) -> tuple[bool, str]:
    x1, y1, x2, y2 = box
    width, height = max(0, x2 - x1), max(0, y2 - y1)
    area = width * height
    process_roi = resolve_process_roi(args, frame_shape)
    if not box_center_in_roi(box, process_roi):
        return False, "vehicle center outside process ROI"
    if confidence < args.min_process_vehicle_conf:
        return False, "vehicle confidence"
    if width < args.min_process_vehicle_width or height < args.min_process_vehicle_height:
        return False, "vehicle dimensions"
    if area < args.min_process_vehicle_area:
        return False, "vehicle area"
    if area / float(frame_shape[0] * frame_shape[1]) < args.min_process_vehicle_area_ratio:
        return False, "vehicle area ratio"
    return True, ""


def resolve_process_roi(args: argparse.Namespace, frame_shape: tuple[int, int, int]) -> list[int] | None:
    values = getattr(args, "process_roi", None)
    if not values:
        return None
    frame_h, frame_w = frame_shape[:2]
    x1, y1, x2, y2 = [float(value) for value in values]
    if all(0.0 <= value <= 1.0 for value in (x1, y1, x2, y2)):
        x1, x2 = x1 * frame_w, x2 * frame_w
        y1, y2 = y1 * frame_h, y2 * frame_h
    x1 = max(0, min(frame_w - 1, int(round(x1))))
    y1 = max(0, min(frame_h - 1, int(round(y1))))
    x2 = max(x1 + 1, min(frame_w, int(round(x2))))
    y2 = max(y1 + 1, min(frame_h, int(round(y2))))
    return [x1, y1, x2, y2]


def box_center_in_roi(box: list[int], roi: list[int] | None) -> bool:
    if roi is None:
        return True
    x1, y1, x2, y2 = box
    rx1, ry1, rx2, ry2 = roi
    cx = (x1 + x2) * 0.5
    cy = (y1 + y2) * 0.5
    return rx1 <= cx <= rx2 and ry1 <= cy <= ry2


def draw_process_roi(frame: np.ndarray, roi: list[int] | None) -> None:
    if roi is None:
        return
    x1, y1, x2, y2 = roi
    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 180, 0), 2)
    cv2.putText(frame, "PROCESS ROI", (x1, max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 180, 0), 2, cv2.LINE_AA)


def update_phase(state: TrackState) -> str:
    if state.locked_text:
        state.phase = "LOCKED"
    elif state.vote_events:
        state.phase = "VERIFYING"
    elif state.plate_attempts or state.plate_hits:
        state.phase = "SEARCHING"
    elif state.seen_frames:
        state.phase = "NEW"
    else:
        state.phase = "NEW"
    return state.phase


def adaptive_vehicle_detection_due(
    states: dict[int, TrackState],
    frame_idx: int,
    processed_frames: int,
    frame_shape: tuple[int, int, int],
    args: argparse.Namespace,
) -> bool:
    base_due = processed_frames == 1 or (processed_frames - 1) % args.vehicle_detect_interval == 0
    if base_due or not args.rk_adaptive:
        return base_due
    if (processed_frames - 1) % args.adaptive_unlocked_detect_interval != 0:
        return False
    for state in states.values():
        if state.locked_text or state.last_box is None or state.last_detection_frame is None:
            continue
        if frame_idx - state.last_detection_frame > args.adaptive_active_frames:
            continue
        ready, _reason = vehicle_ready_for_shape(state.last_box, state.last_vehicle_conf, frame_shape, args)
        if ready:
            return True
    return False


def allow_predicted_plate(state: TrackState, frame_idx: int, args: argparse.Namespace) -> bool:
    if args.plate_on_predicted:
        return True
    if not args.rk_adaptive or state.locked_text or state.last_detection_frame is None:
        return False
    if len(state.vote_events) < args.adaptive_predicted_min_votes:
        return False
    return frame_idx - state.last_detection_frame <= args.adaptive_predicted_max_missing


def find_locked_reassociation(
    states: dict[int, TrackState],
    current_track_id: int,
    box: list[int],
    frame_idx: int,
    frame_shape: tuple[int, int, int],
    args: argparse.Namespace,
) -> int | None:
    if not args.rk_adaptive or not args.locked_reassociate:
        return None
    candidate_box = np.asarray(box, dtype=np.float32)
    best_track_id: int | None = None
    best_score = 0.0
    for track_id, state in states.items():
        if track_id == current_track_id or not state.locked_text or state.last_box is None or state.last_detection_frame is None:
            continue
        missing = frame_idx - state.last_detection_frame
        if missing < 0 or missing > args.locked_reassoc_max_missing:
            continue
        reference_box = predict_box(state, frame_idx, frame_shape, args.locked_reassoc_max_missing)
        if reference_box is None:
            reference_box = state.last_box
        reference_box = np.asarray(reference_box, dtype=np.float32)
        iou_score = SimpleIoUTracker.iou(reference_box, candidate_box)
        center_score = SimpleIoUTracker.center_affinity(reference_box, candidate_box)
        trajectory_score = fixed_camera_away_affinity(state.last_box, candidate_box, frame_shape)
        if (
            iou_score < args.locked_reassoc_iou
            and center_score < args.locked_reassoc_center
            and trajectory_score < args.locked_reassoc_trajectory
        ):
            continue
        score = max(iou_score, center_score, trajectory_score)
        if score > best_score:
            best_track_id = track_id
            best_score = score
    return best_track_id


def fixed_camera_away_affinity(
    previous_box: list[int] | np.ndarray,
    candidate_box: list[int] | np.ndarray,
    frame_shape: tuple[int, int, int],
) -> float:
    previous = np.asarray(previous_box, dtype=np.float32)
    candidate = np.asarray(candidate_box, dtype=np.float32)
    frame_h, frame_w = frame_shape[:2]
    prev_cx, prev_cy = (previous[0] + previous[2]) * 0.5, (previous[1] + previous[3]) * 0.5
    cand_cx, cand_cy = (candidate[0] + candidate[2]) * 0.5, (candidate[1] + candidate[3]) * 0.5
    prev_area = max(1.0, float((previous[2] - previous[0]) * (previous[3] - previous[1])))
    cand_area = max(1.0, float((candidate[2] - candidate[0]) * (candidate[3] - candidate[1])))
    horizontal_score = max(0.0, 1.0 - abs(prev_cx - cand_cx) / max(1.0, 0.35 * frame_w))
    if cand_cy <= prev_cy:
        vertical_score = 1.0
    else:
        vertical_score = max(0.0, 1.0 - (cand_cy - prev_cy) / max(1.0, 0.18 * frame_h))
    if cand_area <= prev_area * 1.25:
        area_score = 1.0
    else:
        area_score = max(0.0, 1.0 - (cand_area / prev_area - 1.25) / 2.0)
    return float(horizontal_score * vertical_score * area_score)


def vehicle_ready_for_lock(
    box: list[int],
    confidence: float,
    frame_shape: tuple[int, int, int],
    args: argparse.Namespace,
    candidate_score: float | None = None,
    obb_conf: float | None = None,
) -> tuple[bool, str]:
    process_roi = resolve_process_roi(args, frame_shape)
    if not box_center_in_roi(box, process_roi):
        return False, "lock blocked outside process ROI"
    x1, y1, x2, y2 = box
    width, height = max(0, x2 - x1), max(0, y2 - y1)
    area = width * height
    frame_h, frame_w = frame_shape[:2]
    area_ratio = area / max(1.0, float(frame_w * frame_h))
    if confidence < args.min_lock_vehicle_conf:
        return False, "lock vehicle confidence"
    if width < args.min_lock_vehicle_width or height < args.min_lock_vehicle_height:
        return False, "lock vehicle dimensions"
    if area < args.min_lock_vehicle_area:
        return False, "lock vehicle area"
    if area_ratio < args.min_lock_vehicle_area_ratio:
        return False, "lock vehicle area ratio"
    if candidate_score is not None and candidate_score < args.min_lock_candidate_score:
        return False, "lock candidate score"
    if obb_conf is not None and obb_conf < args.min_lock_obb_conf:
        return False, "lock OBB confidence"
    return True, ""


def filter_plate(points: np.ndarray, score: float, box: list[int], args: argparse.Namespace) -> tuple[bool, str, float, dict[str, float]]:
    plate_area = polygon_area(points)
    info = geometry(points)
    vehicle_area = max(1.0, float((box[2] - box[0]) * (box[3] - box[1])))
    if plate_area < args.min_plate_area or plate_area > args.max_plate_area:
        return False, "plate area", plate_area, info
    if score < args.min_plate_obb_conf:
        return False, "plate confidence", plate_area, info
    if plate_area / vehicle_area > args.max_plate_vehicle_area_ratio:
        return False, "plate vehicle ratio", plate_area, info
    if not args.min_plate_aspect <= info["aspect"] <= args.max_plate_aspect:
        return False, "plate aspect", plate_area, info
    if plate_overlap(points, box) < args.min_plate_vehicle_overlap:
        return False, "plate overlap", plate_area, info
    return True, "", plate_area, info


def add_candidate(state: TrackState, candidate: Candidate, topk: int) -> None:
    state.plate_hits += 1
    anchor = plate_anchor_from_corners(np.asarray(candidate.corners, dtype=np.float32), candidate.vehicle_box)
    if anchor is not None:
        state.plate_anchor = anchor
        if state.locked_text and state.locked_plate_anchor is None:
            state.locked_plate_anchor = anchor
    state.candidates.append(candidate)
    state.candidates.sort(key=lambda item: item.score, reverse=True)
    del state.candidates[topk:]


def add_rejected_candidate(state: TrackState, candidate: RejectedCandidate, max_rejected: int) -> None:
    state.rejected[candidate.reason] += 1
    if max_rejected <= 0:
        return
    state.rejected_candidates.append(candidate)
    del state.rejected_candidates[max_rejected:]


def consensus(events: deque[dict[str, Any]]) -> dict[str, Any] | None:
    if not events:
        return None
    groups: dict[int, list[dict[str, Any]]] = {}
    for event in events:
        groups.setdefault(len(event["text"]), []).append(event)
    target_events = max(groups.values(), key=lambda items: sum(item["weight"] for item in items))
    votes = [Counter() for _ in range(len(target_events[0]["text"]))]
    totals = [0.0] * len(votes)
    for event in target_events:
        for index, char in enumerate(event["text"]):
            votes[index][char] += event["weight"]
            totals[index] += event["weight"]
    chars, ratios = [], []
    for index, vote in enumerate(votes):
        char, weight = vote.most_common(1)[0]
        chars.append(char)
        ratios.append(float(weight / totals[index]) if totals[index] else 0.0)
    scored_ratios = ratios[1:] if len(ratios) >= 7 else ratios
    return {
        "text": "".join(chars),
        "event_count": len(target_events),
        "min_position_ratio": min(scored_ratios),
        "mean_position_ratio": float(np.mean(scored_ratios)),
        "province_position_ratio": ratios[0] if ratios else 0.0,
        "all_position_ratios": ratios,
    }


def adaptive_exact_lock(events: deque[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any] | None:
    if not events:
        return None
    groups: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        groups.setdefault(event["text"], []).append(event)
    text, text_events = max(
        groups.items(),
        key=lambda item: (len(item[1]), sum(float(event["weight"]) for event in item[1])),
    )
    strong_events = [
        event
        for event in text_events
        if event.get("source") == "plate" and not event.get("predicted")
    ]
    distinct_frames = {int(event["frame_idx"]) for event in text_events}
    if len(text_events) < args.adaptive_min_exact_votes:
        return {
            "deferred_reason": "exact text votes",
            "best_text": text,
            "exact_count": len(text_events),
            "required_exact_count": args.adaptive_min_exact_votes,
        }
    if len(strong_events) < args.adaptive_min_strong_votes:
        return {
            "deferred_reason": "strong plate votes",
            "best_text": text,
            "strong_count": len(strong_events),
            "required_strong_count": args.adaptive_min_strong_votes,
        }
    if len(distinct_frames) < args.adaptive_min_vote_frames:
        return {
            "deferred_reason": "distinct vote frames",
            "best_text": text,
            "frame_count": len(distinct_frames),
            "required_frame_count": args.adaptive_min_vote_frames,
        }
    return {
        "text": text,
        "event_count": len(text_events),
        "total_window_events": len(events),
        "exact_count": len(text_events),
        "strong_count": len(strong_events),
        "distinct_frames": sorted(distinct_frames),
        "mean_confidence": float(np.mean([float(event["confidence"]) for event in text_events])),
        "mean_position_ratio": 1.0,
        "min_position_ratio": 1.0,
        "lock_strategy": "rk_adaptive_exact_text",
    }


def vote(
    state: TrackState,
    text: str,
    confidence: float,
    frame_idx: int,
    candidate: Candidate,
    args: argparse.Namespace,
    frame_shape: tuple[int, int, int],
    source: str = "plate",
    predicted: bool = False,
) -> bool:
    if state.locked_text or len(text) < args.min_lock_text_len or confidence < args.min_ocr_conf:
        return False
    weight = confidence * (0.5 + 0.5 * candidate.score) * (0.5 + 0.5 * candidate.obb_score)
    state.vote_history.append(text)
    state.vote_events.append(
        {
            "frame_idx": frame_idx,
            "text": text,
            "confidence": confidence,
            "source": source,
            "predicted": predicted,
            "vehicle_confidence": candidate.vehicle_conf,
            "candidate_score": candidate.score,
            "obb_confidence": candidate.obb_score,
            "weight": weight,
        }
    )
    state.vote_counts[text] += 1
    while len(state.vote_events) > args.vote_window:
        state.vote_events.popleft()
        old_text = state.vote_history.popleft()
        state.vote_counts[old_text] -= 1
        if state.vote_counts[old_text] <= 0:
            del state.vote_counts[old_text]
    state.lock_attempts += 1
    if args.rk_adaptive:
        result = adaptive_exact_lock(state.vote_events, args)
        if result is None or "text" not in result:
            if result is not None:
                state.lock_deferred_reason = result.get("deferred_reason")
                state.locked_consensus = result
            return False
    else:
        result = consensus(state.vote_events)
        if not (result and result["event_count"] >= args.vote_threshold and result["min_position_ratio"] >= args.min_char_vote_ratio):
            return False
    if result:
        lock_ready, lock_reason = vehicle_ready_for_lock(
            candidate.vehicle_box,
            candidate.vehicle_conf,
            frame_shape,
            args,
            candidate_score=candidate.score,
            obb_conf=candidate.obb_score,
        )
        if not lock_ready:
            state.locked_consensus = {**result, "deferred_reason": lock_reason}
            state.lock_deferred_reason = lock_reason
            return False
        state.locked_text = result["text"]
        state.locked_confidence = result["mean_position_ratio"]
        state.locked_frame = frame_idx
        state.locked_consensus = result
        state.locked_plate_anchor = state.plate_anchor
        return True
    return False


def plate_anchor_from_corners(corners: np.ndarray, vehicle_box: list[int]) -> dict[str, float] | None:
    vx1, vy1, vx2, vy2 = [float(value) for value in vehicle_box]
    vehicle_w = max(1.0, vx2 - vx1)
    vehicle_h = max(1.0, vy2 - vy1)
    if corners.size == 0:
        return None
    px1, py1 = corners.min(axis=0)
    px2, py2 = corners.max(axis=0)
    if px2 <= px1 or py2 <= py1:
        return None
    return {
        "x1": float((px1 - vx1) / vehicle_w),
        "y1": float((py1 - vy1) / vehicle_h),
        "x2": float((px2 - vx1) / vehicle_w),
        "y2": float((py2 - vy1) / vehicle_h),
    }


def box_from_plate_anchor(
    anchor: dict[str, float] | None,
    vehicle_box: list[int],
    frame_shape: tuple[int, int, int],
) -> list[int] | None:
    if anchor is None:
        return None
    vx1, vy1, vx2, vy2 = [float(value) for value in vehicle_box]
    vehicle_w = max(1.0, vx2 - vx1)
    vehicle_h = max(1.0, vy2 - vy1)
    h, w = frame_shape[:2]
    x1 = int(round(vx1 + anchor["x1"] * vehicle_w))
    y1 = int(round(vy1 + anchor["y1"] * vehicle_h))
    x2 = int(round(vx1 + anchor["x2"] * vehicle_w))
    y2 = int(round(vy1 + anchor["y2"] * vehicle_h))
    x1 = max(0, min(w - 1, x1))
    y1 = max(0, min(h - 1, y1))
    x2 = max(x1 + 1, min(w, x2))
    y2 = max(y1 + 1, min(h, y2))
    return [x1, y1, x2, y2]


def update_motion(state: TrackState, box: list[int], confidence: float, frame_idx: int) -> None:
    if state.last_box is not None and state.last_detection_frame is not None:
        delta = max(1, frame_idx - state.last_detection_frame)
        measured = [(current - previous) / delta for current, previous in zip(box, state.last_box)]
        state.velocity_xyxy = [0.7 * old + 0.3 * new for old, new in zip(state.velocity_xyxy, measured)]
        if state.kalman is None:
            state.kalman = BoxKalmanFilter(state.last_box)
        state.kalman.update(box, delta)
    else:
        state.kalman = BoxKalmanFilter(box)
    state.last_box = box.copy()
    state.last_detection_frame = frame_idx
    state.last_vehicle_conf = confidence


def predict_box(state: TrackState, frame_idx: int, shape: tuple[int, int, int], max_frames: int) -> list[int] | None:
    if state.last_box is None or state.last_detection_frame is None:
        return None
    missing = frame_idx - state.last_detection_frame
    if not 0 < missing <= max_frames:
        return None
    if state.kalman is not None:
        predicted = state.kalman.predicted_box(missing, shape)
        if predicted is not None:
            return predicted
    height, width = shape[:2]
    result = [int(round(value + velocity * missing)) for value, velocity in zip(state.last_box, state.velocity_xyxy)]
    result[0], result[2] = max(0, result[0]), min(width, result[2])
    result[1], result[3] = max(0, result[1]), min(height, result[3])
    return result if result[2] > result[0] and result[3] > result[1] else None


def draw_track(
    frame: np.ndarray,
    box: list[int],
    track_id: int,
    state: TrackState,
    renderer: PlateLabelRenderer,
    predicted: bool = False,
) -> None:
    if state.locked_text:
        color = (0, 165, 255) if predicted else (0, 255, 0)
        label = "LOCK " + state.locked_text
        cv2.rectangle(frame, (box[0], box[1]), (box[2], box[3]), color, 2)
        plate_box = box_from_plate_anchor(state.locked_plate_anchor or state.plate_anchor, box, frame.shape)
        if plate_box is not None:
            cv2.rectangle(frame, (plate_box[0], plate_box[1]), (plate_box[2], plate_box[3]), color, 2)
        # Keep the recognized plate tied to the vehicle, even when the plate anchor is tiny.
        renderer.draw(frame, label, (box[0], max(22, box[1] - 8)), color)
        return
    color = (255, 0, 0) if not predicted else (0, 165, 255)
    label = f"PRED ID:{track_id}" if predicted else f"ID:{track_id}"
    cv2.rectangle(frame, (box[0], box[1]), (box[2], box[3]), color, 2)
    cv2.putText(frame, label, (box[0], max(22, box[1] - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)


def candidate_summary(candidate: Candidate, rank: int) -> dict[str, Any]:
    corners = np.asarray(candidate.corners, dtype=np.float32)
    plate_info = geometry(corners) if corners.size else {}
    if corners.size:
        plate_info["vehicle_overlap"] = plate_overlap(corners, candidate.vehicle_box)
    data: dict[str, Any] = {
        "rank": rank,
        "frame_idx": candidate.frame_idx,
        "track_id": candidate.track_id,
        "score": candidate.score,
        "subscores": candidate.subscores,
        "raw_metrics": candidate.metrics,
        "geometry": plate_info,
        "vehicle_confidence": candidate.vehicle_conf,
        "vehicle_box_xyxy": candidate.vehicle_box,
        "plate_corners_xy": candidate.corners,
        "files": {
            "full": f"full_rank{rank}.jpg",
            "vehicle": f"vehicle_rank{rank}.jpg",
            "plate": f"plate_rank{rank}.jpg",
        },
    }
    if candidate.ocr_text is not None:
        data["ocr"] = {
            "text": candidate.ocr_text,
            "confidence": candidate.ocr_conf,
            "engine": candidate.ocr_engine,
        }
    if candidate.ocr_raw_text is not None:
        data["ocr_raw"] = {
            "text": candidate.ocr_raw_text,
            "confidence": candidate.ocr_raw_conf,
            "engine": candidate.ocr_engine,
        }
    return data


def rejected_summary(candidate: RejectedCandidate, rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "frame_idx": candidate.frame_idx,
        "track_id": candidate.track_id,
        "reason": candidate.reason,
        "obb_score": candidate.obb_score,
        "plate_area": candidate.plate_area,
        "geometry": candidate.geometry,
        "vehicle_confidence": candidate.vehicle_conf,
        "vehicle_box_xyxy": candidate.vehicle_box,
        "plate_corners_xy": candidate.plate_corners,
        "files": {
            "full": f"rejected/full_reject{rank}.jpg",
            "vehicle": f"rejected/vehicle_reject{rank}.jpg",
            "plate": f"rejected/plate_reject{rank}.jpg",
        },
    }


def jsonable_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        key: str(value) if isinstance(value, Path) else value
        for key, value in vars(args).items()
    }


def save_results(states: dict[int, TrackState], output_dir: Path, run_stats: dict[str, Any], args: argparse.Namespace) -> None:
    run_summary: dict[str, Any] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "args": jsonable_args(args),
        "stats": dict(run_stats),
        "track_count": 0,
        "tracks": {},
        "ignored_tracks": {},
    }
    for track_id, state in sorted(states.items()):
        candidates = sorted(state.candidates, key=lambda item: item.score, reverse=True)
        if not candidates and not state.rejected_candidates and not state.vote_history and not state.locked_text:
            continue
        summary = {
            "track_id": track_id,
            "phase": update_phase(state),
            "seen_frames": state.seen_frames,
            "plate_hits": state.plate_hits,
            "locked_text": state.locked_text,
            "locked_confidence": state.locked_confidence,
            "locked_frame": state.locked_frame,
            "locked_consensus": state.locked_consensus,
            "lock_deferred_reason": state.lock_deferred_reason,
            "lock_attempts": state.lock_attempts,
            "plate_anchor": state.plate_anchor,
            "locked_plate_anchor": state.locked_plate_anchor,
            "motion_model": "kalman_box_cv_with_plate_anchor",
            "kalman_state": state.kalman.snapshot() if state.kalman is not None else None,
            "last_box": state.last_box,
            "last_detection_frame": state.last_detection_frame,
            "last_plate_attempt_frame": state.last_plate_attempt_frame,
            "plate_attempts": state.plate_attempts,
            "vote_history": list(state.vote_history),
            "vote_events": list(state.vote_events),
            "vote_counts": dict(state.vote_counts),
            "rejected_reasons": dict(state.rejected),
            "rejected_count": len(state.rejected_candidates),
            "rejected_candidates": [],
            "topk": len(candidates),
            "candidates": [],
        }
        if not candidates and not state.rejected_candidates and not state.vote_history and not state.locked_text:
            run_summary["ignored_tracks"][str(track_id)] = {
                "plate_hits": state.plate_hits,
                "rejected_reasons": dict(state.rejected),
                "reason": "no accepted Top-K candidate",
            }
            continue
        track_dir = output_dir / f"track_{track_id}"
        track_dir.mkdir(parents=True, exist_ok=True)
        for rank, candidate in enumerate(candidates, 1):
            cv2.imwrite(str(track_dir / f"full_rank{rank}.jpg"), candidate.full_frame)
            cv2.imwrite(str(track_dir / f"vehicle_rank{rank}.jpg"), candidate.vehicle_crop)
            cv2.imwrite(str(track_dir / f"plate_rank{rank}.jpg"), candidate.plate_crop)
            summary["candidates"].append(candidate_summary(candidate, rank))
        if state.rejected_candidates:
            rejected_dir = track_dir / "rejected"
            rejected_dir.mkdir(parents=True, exist_ok=True)
            for rank, rejected in enumerate(state.rejected_candidates, 1):
                cv2.imwrite(str(rejected_dir / f"full_reject{rank}.jpg"), rejected.full_frame)
                cv2.imwrite(str(rejected_dir / f"vehicle_reject{rank}.jpg"), rejected.vehicle_crop)
                cv2.imwrite(str(rejected_dir / f"plate_reject{rank}.jpg"), rejected.plate_crop)
                summary["rejected_candidates"].append(rejected_summary(rejected, rank))
        (track_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        run_summary["tracks"][str(track_id)] = summary
    run_summary["track_count"] = len(run_summary["tracks"])
    (output_dir / "run_summary.json").write_text(json.dumps(run_summary, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="RK3588 Top-K ALPR capture using existing RKNN vehicle/OBB/OCR models.")
    parser.add_argument("--video", required=True, help="Video path, camera numeric ID, or mipi.")
    parser.add_argument("--camera-device", default="/dev/video22", help="V4L2 device used when --video mipi (default: 4K MIPI main path).")
    parser.add_argument("--camera-width", type=int, default=1920, help="Requested MIPI capture width; use 0 to keep the driver setting.")
    parser.add_argument("--camera-height", type=int, default=1080, help="Requested MIPI capture height; use 0 to keep the driver setting.")
    parser.add_argument("--camera-fps", type=float, default=25.0, help="Requested MIPI capture FPS; use 0 to keep the driver setting.")
    parser.add_argument("--mipi-fourcc", choices=("UYVY", "NV12", "NV21"), default="UYVY", help="Requested MIPI output pixel format. Default matches video22's stable mode.")
    parser.add_argument("--mipi-color-mode", choices=("uyvy", "nv12", "nv21", "opencv"), default="uyvy", help="MIPI pixel decoding. Keep this aligned with --mipi-fourcc unless using OpenCV conversion.")
    parser.add_argument("--mipi-backend", choices=("v4l2ctl", "opencv"), default="v4l2ctl", help="MIPI capture backend. v4l2ctl uses native mmap and avoids this board's slow OpenCV V4L2 path.")
    parser.add_argument("--mipi-gray-world", action="store_true", help="Apply a lightweight software white-balance correction to MIPI frames.")
    parser.add_argument("--mipi-buffer-size", type=int, default=1, help="Requested V4L2 capture queue depth; lower values reduce live-preview latency.")
    parser.add_argument("--vehicle-model", type=Path, default=Path("vehicle.rknn"))
    parser.add_argument("--plate-model", type=Path, default=Path("best_obb.rknn"))
    parser.add_argument("--plate-imgsz", type=int, default=640, help="Static square input size of the selected RKNN OBB model.")
    parser.add_argument("--ocr-model", type=Path, default=Path("plate_rec.rknn"))
    parser.add_argument("--dict", type=Path, default=Path("dict.txt"))
    parser.add_argument("--ocr-engine", choices=("none", "hyperlpr3", "rknn"), default="hyperlpr3")
    parser.add_argument("--hyperlpr-pre-ocr", action="store_true", help="Run HyperLPR3 on the whole vehicle crop before OBB so OCR voting is not gated by plate OBB hits.")
    parser.add_argument("--lock-on-plate-detect", action="store_true", help="Lock and follow a vehicle as soon as an accepted plate OBB is detected, without requiring OCR.")
    parser.add_argument("--plate-detected-label", default="PLATE", help="Label drawn above vehicles locked by plate detection when OCR is disabled.")
    parser.add_argument("--output", type=Path, default=Path("captures_topk_rknn"))
    parser.add_argument("--topk", type=int, default=5)
    parser.add_argument("--vehicle-conf", type=float, default=0.55)
    parser.add_argument("--plate-conf", type=float, default=0.25)
    parser.add_argument("--min-process-vehicle-conf", type=float, default=0.65)
    parser.add_argument("--min-process-vehicle-width", type=int, default=90)
    parser.add_argument("--min-process-vehicle-height", type=int, default=70)
    parser.add_argument("--min-process-vehicle-area", type=int, default=8000)
    parser.add_argument("--min-process-vehicle-area-ratio", type=float, default=0.003)
    parser.add_argument(
        "--process-roi",
        type=float,
        nargs=4,
        metavar=("X1", "Y1", "X2", "Y2"),
        help="Only process vehicles whose center falls inside this ROI. Values <=1 are treated as normalized frame coordinates.",
    )
    parser.add_argument("--draw-process-roi", action="store_true", help="Draw --process-roi on published/saved frames.")
    parser.add_argument("--min-lock-vehicle-conf", type=float, default=0.70)
    parser.add_argument("--min-lock-vehicle-width", type=int, default=120)
    parser.add_argument("--min-lock-vehicle-height", type=int, default=90)
    parser.add_argument("--min-lock-vehicle-area", type=int, default=12000)
    parser.add_argument("--min-lock-vehicle-area-ratio", type=float, default=0.004)
    parser.add_argument("--min-lock-candidate-score", type=float, default=0.0)
    parser.add_argument("--min-lock-obb-conf", type=float, default=0.0)
    parser.add_argument("--min-plate-obb-conf", type=float, default=0.50)
    parser.add_argument("--min-plate-area", type=float, default=250.0)
    parser.add_argument("--max-plate-area", type=float, default=8000.0)
    parser.add_argument("--max-rejected-per-track", type=int, default=5, help="Maximum rejected OBB debug samples saved per track.")
    parser.add_argument("--max-plate-vehicle-area-ratio", type=float, default=0.04)
    parser.add_argument("--min-plate-aspect", type=float, default=2.0)
    parser.add_argument("--max-plate-aspect", type=float, default=6.0)
    parser.add_argument("--min-plate-vehicle-overlap", type=float, default=0.5)
    parser.add_argument("--vehicle-box-pad-ratio", type=float, default=0.2)
    parser.add_argument("--vehicle-box-min-pad", type=int, default=20)
    parser.add_argument("--track-iou", type=float, default=0.3)
    parser.add_argument("--track-center-threshold", type=float, default=0.45, help="Fallback center/scale matching threshold when IoU drops during fast scale changes.")
    parser.add_argument("--track-max-age", type=int, default=30)
    parser.add_argument("--vehicle-detect-interval", type=int, default=1, help="Run vehicle RKNN every N processed frames; 1 matches the Windows reference behavior.")
    parser.add_argument("--rk-adaptive", action="store_true", help="Enable RK-specific state-machine scheduling and exact-text locking while keeping Windows-equivalent mode available by default.")
    parser.add_argument("--adaptive-unlocked-detect-interval", type=int, default=1, help="Vehicle detection interval used for active unlocked tracks in --rk-adaptive mode.")
    parser.add_argument("--adaptive-active-frames", type=int, default=18, help="Keep active unlocked tracks in high-frequency vehicle detection for this many frames after the last real detection.")
    parser.add_argument("--adaptive-predicted-min-votes", type=int, default=2, help="Minimum OCR vote events before --rk-adaptive allows plate attempts on predicted boxes.")
    parser.add_argument("--adaptive-predicted-max-missing", type=int, default=2, help="Maximum frames since the last real detection for adaptive predicted-box plate attempts.")
    parser.add_argument("--adaptive-min-exact-votes", type=int, default=3, help="Minimum same-text OCR votes required to lock in --rk-adaptive mode.")
    parser.add_argument("--adaptive-min-strong-votes", type=int, default=2, help="Minimum same-text votes from non-predicted plate OCR required to lock in --rk-adaptive mode.")
    parser.add_argument("--adaptive-min-vote-frames", type=int, default=3, help="Minimum distinct frame count for same-text lock votes in --rk-adaptive mode.")
    parser.add_argument("--locked-reassociate", action=argparse.BooleanOptionalAction, default=True, help="In --rk-adaptive mode, transfer locked plate state to a short-lived new track when the tracker changes IDs.")
    parser.add_argument("--locked-reassoc-max-missing", type=int, default=180, help="Maximum frames since the locked track's last real detection for reassociation.")
    parser.add_argument("--locked-reassoc-iou", type=float, default=0.01, help="Minimum IoU for locked-track reassociation.")
    parser.add_argument("--locked-reassoc-center", type=float, default=0.12, help="Minimum center/scale affinity for locked-track reassociation.")
    parser.add_argument("--locked-reassoc-trajectory", type=float, default=0.25, help="Minimum fixed-camera away-motion affinity for locked-track reassociation.")
    parser.add_argument("--plate-on-predicted", action="store_true", help="Also run plate OBB/OCR on predicted vehicle boxes before a plate is locked.")
    parser.add_argument("--plate-attempt-interval", type=int, default=1, help="Minimum frame gap between plate OBB/OCR attempts for the same track.")
    parser.add_argument("--vote-window", type=int, default=10)
    parser.add_argument("--vote-threshold", type=int, default=3)
    parser.add_argument("--min-char-vote-ratio", type=float, default=0.65)
    parser.add_argument("--min-ocr-conf", type=float, default=0.70, help="Minimum OCR confidence allowed to enter live voting.")
    parser.add_argument("--min-lock-text-len", type=int, default=7)
    parser.add_argument("--max-predict-frames", type=int, default=12, help="Legacy prediction limit kept for compatibility.")
    parser.add_argument("--max-unlocked-predict-frames", type=int, default=2, help="Maximum prediction-only frames for unlocked tracks.")
    parser.add_argument("--max-locked-predict-frames", type=int, default=180, help="Maximum prediction-only frames for locked tracks.")
    parser.add_argument("--cjk-font", type=Path, default=Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"), help="TrueType/TTC font used for Chinese locked-plate labels.")
    parser.add_argument("--label-font-size", type=int, default=28)
    parser.add_argument("--progress-interval", type=int, default=100)
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--start-frame", type=int, default=0, help="Seek to this zero-based video frame before processing.")
    parser.add_argument("--save-video", action="store_true")
    parser.add_argument("--publish-frame", type=Path, help="Optional JPEG path updated for an MJPEG preview server, for example /tmp/frame.jpg.")
    parser.add_argument("--publish-interval", type=int, default=2, help="Publish every N processed frames when --publish-frame is set.")
    parser.add_argument("--preview-jpeg-quality", type=int, default=80, help="JPEG quality for --publish-frame, 1-100.")
    args = parser.parse_args()
    if args.vehicle_detect_interval <= 0:
        raise ValueError("--vehicle-detect-interval must be positive")
    if args.adaptive_unlocked_detect_interval <= 0:
        raise ValueError("--adaptive-unlocked-detect-interval must be positive")
    if args.adaptive_active_frames < 0 or args.adaptive_predicted_max_missing < 0:
        raise ValueError("adaptive frame limits must be non-negative")
    if args.adaptive_predicted_min_votes < 0:
        raise ValueError("--adaptive-predicted-min-votes must be non-negative")
    if args.adaptive_min_exact_votes <= 0 or args.adaptive_min_strong_votes <= 0 or args.adaptive_min_vote_frames <= 0:
        raise ValueError("adaptive lock vote thresholds must be positive")
    if args.locked_reassoc_max_missing < 0:
        raise ValueError("--locked-reassoc-max-missing must be non-negative")
    if args.plate_attempt_interval <= 0:
        raise ValueError("--plate-attempt-interval must be positive")
    if args.max_rejected_per_track < 0:
        raise ValueError("--max-rejected-per-track must be non-negative")
    if args.max_unlocked_predict_frames < 0 or args.max_locked_predict_frames < 0:
        raise ValueError("prediction frame limits must be non-negative")
    if args.process_roi and (args.process_roi[2] <= args.process_roi[0] or args.process_roi[3] <= args.process_roi[1]):
        raise ValueError("--process-roi must be X1 Y1 X2 Y2 with X2 > X1 and Y2 > Y1")
    if not 1 <= args.preview_jpeg_quality <= 100:
        raise ValueError("--preview-jpeg-quality must be between 1 and 100")

    output_dir = args.output / f"run_{datetime.now():%Y%m%d_%H%M%S}"
    output_dir.mkdir(parents=True, exist_ok=False)
    dictionary = load_dictionary(args.dict) if args.ocr_engine == "rknn" else []
    vehicle_model = RKNNRunner(args.vehicle_model, "vehicle")
    plate_model = RKNNRunner(args.plate_model, "plate_obb")
    ocr_model = RKNNRunner(args.ocr_model, "plate_rec") if args.ocr_engine == "rknn" else None
    hyperlpr3 = build_hyperlpr3() if args.ocr_engine == "hyperlpr3" else None
    tracker = SimpleIoUTracker(args.track_iou, args.track_max_age, args.track_center_threshold)
    states: dict[int, TrackState] = {}
    label_renderer = PlateLabelRenderer(args.cjk_font, args.label_font_size)
    mipi_width, mipi_height = 0, 0
    if args.video == "mipi":
        mode_by_fourcc = {"UYVY": "uyvy", "NV12": "nv12", "NV21": "nv21"}
        if args.mipi_color_mode != "opencv" and args.mipi_color_mode != mode_by_fourcc[args.mipi_fourcc]:
            raise ValueError("--mipi-color-mode must match --mipi-fourcc unless --mipi-color-mode=opencv")
        if args.mipi_backend == "v4l2ctl":
            cap = V4L2CtlCapture(args.camera_device, args.camera_width, args.camera_height, args.mipi_fourcc, args.mipi_color_mode)
        else:
            cap = cv2.VideoCapture(args.camera_device, cv2.CAP_V4L2)
            if args.camera_width > 0:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.camera_width)
            if args.camera_height > 0:
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.camera_height)
            if args.camera_fps > 0:
                cap.set(cv2.CAP_PROP_FPS, args.camera_fps)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*args.mipi_fourcc))
            cap.set(cv2.CAP_PROP_BUFFERSIZE, args.mipi_buffer_size)
            cap.set(cv2.CAP_PROP_CONVERT_RGB, 1 if args.mipi_color_mode == "opencv" else 0)
    else:
        cap = cv2.VideoCapture(int(args.video) if args.video.isdigit() else args.video)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {args.video}")
    if args.video == "mipi":
        mipi_width, mipi_height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(
            f"MIPI capture: device={args.camera_device} "
            f"reported={mipi_width}x{mipi_height} fps={cap.get(cv2.CAP_PROP_FPS):.2f} "
            f"backend={args.mipi_backend} mode={args.mipi_color_mode} buffer={args.mipi_buffer_size}",
            flush=True,
        )
    if args.start_frame > 0 and args.video != "mipi":
        cap.set(cv2.CAP_PROP_POS_FRAMES, args.start_frame)
    writer: cv2.VideoWriter | None = None
    frame_idx = args.start_frame
    processed_frames = 0
    started = time.perf_counter()
    run_stats: Counter[str] = Counter()
    try:
        while True:
            ok, captured = cap.read()
            if not ok:
                break
            if args.video == "mipi" and args.mipi_backend == "opencv":
                frame = decode_mipi_frame(captured, mipi_width, mipi_height, args.mipi_color_mode)
            else:
                frame = captured
            if args.video == "mipi" and args.mipi_gray_world:
                frame = gray_world_white_balance(frame)
            frame_idx += 1
            processed_frames += 1
            raw_frame = frame.copy()
            process_roi = resolve_process_roi(args, frame.shape)
            if args.draw_process_roi:
                draw_process_roi(frame, process_roi)
            base_detect_due = processed_frames == 1 or (processed_frames - 1) % args.vehicle_detect_interval == 0
            detect_vehicle_now = adaptive_vehicle_detection_due(states, frame_idx, processed_frames, frame.shape, args)
            tracked: list[tuple[int, np.ndarray, float, bool]] = []
            if detect_vehicle_now:
                if args.rk_adaptive and not base_detect_due:
                    run_stats["vehicle_detection_frames_adaptive"] += 1
                vehicle_rgb = cv2.cvtColor(cv2.resize(frame, (640, 640)), cv2.COLOR_BGR2RGB)
                boxes, confidences = decode_vehicle(vehicle_model.infer_rgb(vehicle_rgb), frame.shape, args.vehicle_conf, 0.45)
                tracked = [(track_id, box, confidence, False) for track_id, box, confidence in tracker.update(boxes, confidences, frame_idx)]
                run_stats["vehicle_detection_frames"] += 1
            else:
                for track_id, state in states.items():
                    max_predict_frames = args.max_locked_predict_frames if state.locked_text else args.max_unlocked_predict_frames
                    predicted = predict_box(state, frame_idx, frame.shape, max_predict_frames)
                    if predicted:
                        tracked.append((track_id, np.asarray(predicted, dtype=np.float32), state.last_vehicle_conf, True))
                run_stats["vehicle_prediction_frames"] += 1
            seen_ids: set[int] = set()
            plate_hits = 0
            for track_id, tracked_box, vehicle_conf, is_predicted in tracked:
                box = [int(round(value)) for value in tracked_box]
                current_state = states.get(track_id)
                if current_state is None or not current_state.locked_text:
                    reassociated_track_id = find_locked_reassociation(states, track_id, box, frame_idx, frame.shape, args)
                    if reassociated_track_id is not None:
                        existing_state = states.get(track_id)
                        locked_state = states.pop(reassociated_track_id)
                        if existing_state is not None and existing_state is not locked_state:
                            locked_state.seen_frames += existing_state.seen_frames
                        states[track_id] = locked_state
                        run_stats["locked_reassociations"] += 1
                        print(
                            f"[REASSOC] locked track {reassociated_track_id} -> {track_id} "
                            f"plate={locked_state.locked_text} frame={frame_idx} predicted={is_predicted}",
                            flush=True,
                        )
                seen_ids.add(track_id)
                state = states.setdefault(track_id, TrackState())
                state.seen_frames += 1
                if not is_predicted:
                    update_motion(state, box, float(vehicle_conf), frame_idx)
                if state.locked_text:
                    draw_track(frame, box, track_id, state, label_renderer, predicted=is_predicted)
                    continue
                if is_predicted and not allow_predicted_plate(state, frame_idx, args):
                    draw_track(frame, box, track_id, state, label_renderer, predicted=True)
                    continue
                if (
                    state.last_plate_attempt_frame is not None
                    and frame_idx - state.last_plate_attempt_frame < args.plate_attempt_interval
                ):
                    if is_predicted:
                        draw_track(frame, box, track_id, state, label_renderer, predicted=True)
                    else:
                        draw_track(frame, box, track_id, state, label_renderer)
                    run_stats["skipped:plate attempt interval"] += 1
                    continue
                ready, reason = vehicle_ready(box, float(vehicle_conf), frame, args)
                if ready:
                    run_stats["vehicles_ready"] += 1
                    run_stats["vehicles_ready_predicted" if is_predicted else "vehicles_ready_detected"] += 1
                    state.last_plate_attempt_frame = frame_idx
                    state.plate_attempts += 1
                    run_stats["plate_attempts"] += 1
                    ocr_vote_recorded_this_frame = False
                    x1, y1, x2, y2 = box
                    pad_x = max(args.vehicle_box_min_pad, int((x2 - x1) * args.vehicle_box_pad_ratio))
                    pad_y = max(args.vehicle_box_min_pad, int((y2 - y1) * args.vehicle_box_pad_ratio))
                    rx1, ry1, rx2, ry2 = max(0, x1 - pad_x), max(0, y1 - pad_y), min(frame.shape[1], x2 + pad_x), min(frame.shape[0], y2 + pad_y)
                    roi = raw_frame[ry1:ry2, rx1:rx2]
                    vehicle_crop = safe_crop(raw_frame, box)
                    if args.hyperlpr_pre_ocr and args.ocr_engine == "hyperlpr3" and vehicle_crop.size:
                        text, ocr_conf = recognize_hyperlpr3(hyperlpr3, vehicle_crop)
                        run_stats["ocr_pre:hyperlpr3"] += 1
                        if text and ocr_conf >= args.min_ocr_conf:
                            pseudo_candidate = Candidate(
                                frame_idx,
                                track_id,
                                0.5,
                                {},
                                {},
                                0.5,
                                0.0,
                                [],
                                box,
                                float(vehicle_conf),
                                raw_frame.copy(),
                                vehicle_crop,
                                vehicle_crop,
                                text,
                                ocr_conf,
                            )
                            run_stats["ocr_pre_votes"] += 1
                            locked_by_pre_ocr = vote(state, text, ocr_conf, frame_idx, pseudo_candidate, args, raw_frame.shape, source="vehicle", predicted=is_predicted)
                            ocr_vote_recorded_this_frame = True
                            if locked_by_pre_ocr:
                                run_stats["ocr_pre_locks"] += 1
                                print(f"[LOCK] track={track_id} plate={state.locked_text} frame={frame_idx} events={state.locked_consensus['event_count']} source=hyperlpr_pre", flush=True)
                                draw_track(frame, box, track_id, state, label_renderer, predicted=is_predicted)
                                continue
                    if roi.size:
                        plate_rgb = cv2.cvtColor(cv2.resize(roi, (args.plate_imgsz, args.plate_imgsz)), cv2.COLOR_BGR2RGB)
                        for corners, obb_score in decode_obbs(plate_model.infer_rgb(plate_rgb), roi, (rx1, ry1), args.plate_imgsz, args.plate_conf):
                            run_stats["obb_candidates"] += 1
                            accepted, rejection, plate_area, info = filter_plate(corners, obb_score, box, args)
                            if not accepted:
                                rejected_plate = warp_plate(raw_frame, corners)
                                add_rejected_candidate(
                                    state,
                                    RejectedCandidate(
                                        frame_idx=frame_idx,
                                        track_id=track_id,
                                        reason=rejection,
                                        obb_score=float(obb_score),
                                        plate_area=float(plate_area),
                                        geometry=info,
                                        vehicle_conf=float(vehicle_conf),
                                        vehicle_box=box,
                                        plate_corners=corners.tolist(),
                                        full_frame=raw_frame.copy(),
                                        vehicle_crop=vehicle_crop,
                                        plate_crop=rejected_plate,
                                    ),
                                    args.max_rejected_per_track,
                                )
                                run_stats[f"rejected:{rejection}"] += 1
                                continue
                            plate = warp_plate(raw_frame, corners)
                            score, subscores, metrics = quality_score(plate, plate_area, obb_score)
                            candidate = Candidate(frame_idx, track_id, score, subscores, metrics, obb_score, plate_area, corners.tolist(), box, float(vehicle_conf), raw_frame.copy(), vehicle_crop, plate)
                            text, ocr_conf = "", 0.0
                            if args.ocr_engine == "none":
                                run_stats["ocr_skipped:none"] += 1
                            elif args.ocr_engine == "hyperlpr3":
                                text, ocr_conf = recognize_hyperlpr3(hyperlpr3, vehicle_crop)
                                if not text:
                                    text, ocr_conf = recognize_hyperlpr3(hyperlpr3, plate)
                            else:
                                ocr_rgb = cv2.cvtColor(cv2.resize(plate, (320, 48)), cv2.COLOR_BGR2RGB)
                                text, ocr_conf = decode_ocr(ocr_model.infer_rgb(ocr_rgb), dictionary)
                            if args.ocr_engine != "none":
                                run_stats[f"ocr:{args.ocr_engine}"] += 1
                            candidate.ocr_text, candidate.ocr_conf = text or None, ocr_conf
                            candidate.ocr_engine = args.ocr_engine if text else None
                            add_candidate(state, candidate, args.topk)
                            run_stats["accepted_candidates"] += 1
                            plate_hits += 1
                            if args.lock_on_plate_detect or args.ocr_engine == "none":
                                if not state.locked_text:
                                    state.locked_text = args.plate_detected_label
                                    state.locked_confidence = 1.0
                                    state.locked_frame = frame_idx
                                    state.locked_consensus = {
                                        "source": "plate_detect",
                                        "obb_confidence": float(obb_score),
                                        "candidate_score": float(score),
                                        "plate_area": float(plate_area),
                                    }
                                    state.locked_plate_anchor = state.plate_anchor
                                    run_stats["plate_detect_locks"] += 1
                                    print(f"[LOCK] track={track_id} label={state.locked_text} frame={frame_idx} source=plate_detect", flush=True)
                                draw_track(frame, box, track_id, state, label_renderer, predicted=is_predicted)
                                cv2.polylines(frame, [corners.astype(np.int32)], True, (0, 255, 255), 2)
                                break
                            if text and not ocr_vote_recorded_this_frame and vote(state, text, ocr_conf, frame_idx, candidate, args, raw_frame.shape, source="plate", predicted=is_predicted):
                                print(f"[LOCK] track={track_id} plate={state.locked_text} frame={frame_idx} events={state.locked_consensus['event_count']}", flush=True)
                            cv2.polylines(frame, [corners.astype(np.int32)], True, (0, 255, 255), 2)
                            break
                else:
                    run_stats[f"gated:{reason}"] += 1
                draw_track(frame, box, track_id, state, label_renderer)
            for track_id, state in states.items():
                if track_id not in seen_ids and state.locked_text:
                    predicted = predict_box(state, frame_idx, frame.shape, args.max_locked_predict_frames)
                    if predicted:
                        draw_track(frame, predicted, track_id, state, label_renderer, predicted=True)
            elapsed = max(1e-6, time.perf_counter() - started)
            total_plate_hits = sum(state.plate_hits for state in states.values())
            cv2.putText(
                frame,
                f"frame:{frame_idx} new_hits:{plate_hits} total_hits:{total_plate_hits} fps:{processed_frames / elapsed:.2f}",
                (20, 36),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )
            if args.save_video:
                if writer is None:
                    writer = cv2.VideoWriter(str(output_dir / "annotated.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), cap.get(cv2.CAP_PROP_FPS) or 25.0, (frame.shape[1], frame.shape[0]))
                writer.write(frame)
            if args.publish_frame is not None and processed_frames % max(1, args.publish_interval) == 0:
                args.publish_frame.parent.mkdir(parents=True, exist_ok=True)
                temporary = args.publish_frame.with_name(f"{args.publish_frame.stem}_tmp{args.publish_frame.suffix}")
                cv2.imwrite(str(temporary), frame, [cv2.IMWRITE_JPEG_QUALITY, args.preview_jpeg_quality])
                temporary.replace(args.publish_frame)
            if processed_frames % args.progress_interval == 0:
                print(
                    f"Processed {processed_frames} frames (video frame {frame_idx}) | "
                    f"tracks={len(states)} | new_hits={plate_hits} | total_hits={total_plate_hits} | "
                    f"fps={processed_frames / elapsed:.2f}",
                    flush=True,
                )
            if args.max_frames and processed_frames >= args.max_frames:
                break
    except KeyboardInterrupt:
        print("Interrupted by user; saving current Top-K results...", flush=True)
        run_stats["stop_reason"] = "keyboard_interrupt"
    except RuntimeError as exc:
        message = str(exc)
        if "empty RKNN output" in message:
            print(f"RKNN inference stopped with empty output ({message}); saving current Top-K results...", flush=True)
            run_stats["stop_reason"] = message
        else:
            run_stats["stop_reason"] = message
            raise
    finally:
        cap.release()
        if writer is not None:
            writer.release()
        vehicle_model.close()
        plate_model.close()
        if ocr_model is not None:
            ocr_model.close()
        run_stats["frames_processed"] = processed_frames
        run_stats["start_frame"] = args.start_frame
        run_stats["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        print(f"Saving Top-K capture run: {output_dir}", flush=True)
        save_results(states, output_dir, run_stats, args)
        print(f"Run stats: {dict(run_stats)}", flush=True)
    print(f"Saved Top-K capture run: {output_dir}", flush=True)


if __name__ == "__main__":
    main()
