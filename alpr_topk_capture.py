import argparse
import json
import math
import os
import site
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("YOLO_CONFIG_DIR", str(Path(__file__).resolve().parent / "Ultralytics"))
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(Path(__file__).resolve().parent / "PaddleCache"))
LOCAL_DEPS_DIR = Path(__file__).resolve().parent / "python_deps"
if LOCAL_DEPS_DIR.exists():
    site.addsitedir(str(LOCAL_DEPS_DIR))
LOCAL_OCR_DEPS_DIR = Path(__file__).resolve().parent / "python_deps_ocr"
if LOCAL_OCR_DEPS_DIR.exists():
    site.addsitedir(str(LOCAL_OCR_DEPS_DIR))

import cv2
import numpy as np
from ultralytics import YOLO
from PIL import Image, ImageDraw, ImageFont


DEFAULT_VIDEO = r"D:\YOLO_ALPR_Project\测试图\14.mp4"
DEFAULT_OUTPUT = r"D:\YOLO_ALPR_Project\captures_topk"
DEFAULT_VEHICLE_MODEL = r"D:\YOLO_ALPR_Project\yolo11n.pt"
DEFAULT_PLATE_MODEL = r"D:\YOLO_ALPR_Project\best_obb.pt"

PLATE_WIDTH = 320
PLATE_HEIGHT = 96
ROI_MARGIN = 50
VEHICLE_CLASSES = [2, 5, 7]
CHINESE_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]


@dataclass
class Candidate:
    frame_idx: int
    track_id: int
    score: float
    subscores: dict[str, float]
    raw_metrics: dict[str, float]
    geometry: dict[str, float]
    vehicle_conf: float
    vehicle_box: list[int]
    plate_corners: list[list[float]]
    full_frame: np.ndarray
    vehicle_crop: np.ndarray
    plate_crop: np.ndarray
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
    full_frame: np.ndarray
    vehicle_crop: np.ndarray
    plate_crop: np.ndarray


@dataclass
class TrackState:
    candidates: list[Candidate] = field(default_factory=list)
    rejected_candidates: list[RejectedCandidate] = field(default_factory=list)
    seen_frames: int = 0
    plate_hits: int = 0
    vote_history: deque[str] = field(default_factory=deque)
    vote_events: deque[dict[str, Any]] = field(default_factory=deque)
    vote_counts: Counter[str] = field(default_factory=Counter)
    locked_text: str | None = None
    locked_conf: float | None = None
    locked_frame: int | None = None
    locked_consensus: dict[str, Any] | None = None
    last_box: list[int] | None = None
    last_detection_frame: int | None = None
    velocity_xyxy: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])


class SimpleIoUTracker:
    def __init__(self, iou_threshold: float = 0.3, max_age: int = 30) -> None:
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.next_id = 1
        self.tracks: dict[int, dict[str, Any]] = {}

    @staticmethod
    def iou(box_a: np.ndarray, box_b: np.ndarray) -> float:
        ax1, ay1, ax2, ay2 = box_a
        bx1, by1, bx2, by2 = box_b
        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)
        iw = max(0.0, ix2 - ix1)
        ih = max(0.0, iy2 - iy1)
        inter = iw * ih
        area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
        area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
        denom = area_a + area_b - inter
        return float(inter / denom) if denom > 0 else 0.0

    def update(
        self,
        detections: np.ndarray,
        confidences: np.ndarray | None,
        frame_idx: int,
    ) -> list[tuple[int, np.ndarray, float]]:
        detections = detections.astype(np.float32)
        if confidences is None:
            confidences = np.ones((len(detections),), dtype=np.float32)
        else:
            confidences = confidences.astype(np.float32).reshape(-1)
        assigned_tracks: set[int] = set()
        assigned_dets: set[int] = set()
        matches: list[tuple[int, int, float]] = []

        for track_id, track in self.tracks.items():
            for det_idx, det in enumerate(detections):
                matches.append((track_id, det_idx, self.iou(track["box"], det)))

        matches.sort(key=lambda item: item[2], reverse=True)
        for track_id, det_idx, iou_value in matches:
            if iou_value < self.iou_threshold:
                break
            if track_id in assigned_tracks or det_idx in assigned_dets:
                continue
            self.tracks[track_id]["box"] = detections[det_idx]
            self.tracks[track_id]["conf"] = float(confidences[det_idx])
            self.tracks[track_id]["last_seen"] = frame_idx
            assigned_tracks.add(track_id)
            assigned_dets.add(det_idx)

        for det_idx, det in enumerate(detections):
            if det_idx in assigned_dets:
                continue
            track_id = self.next_id
            self.next_id += 1
            self.tracks[track_id] = {"box": det, "conf": float(confidences[det_idx]), "last_seen": frame_idx}
            assigned_tracks.add(track_id)

        stale_ids = [
            track_id
            for track_id, track in self.tracks.items()
            if frame_idx - int(track["last_seen"]) > self.max_age
        ]
        for track_id in stale_ids:
            del self.tracks[track_id]

        active = []
        for track_id in assigned_tracks:
            if track_id in self.tracks:
                active.append((track_id, self.tracks[track_id]["box"].copy(), float(self.tracks[track_id].get("conf", 1.0))))
        active.sort(key=lambda item: item[0])
        return active


def order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def expand_rect(rect: np.ndarray, pad_x: float = 5.0, pad_y: float = 5.0) -> np.ndarray:
    expanded = rect.copy()
    expanded[0] = [expanded[0][0] - pad_x, expanded[0][1] - pad_y]
    expanded[1] = [expanded[1][0] + pad_x, expanded[1][1] - pad_y]
    expanded[2] = [expanded[2][0] + pad_x, expanded[2][1] + pad_y]
    expanded[3] = [expanded[3][0] - pad_x, expanded[3][1] + pad_y]
    return expanded


def polygon_area(points: np.ndarray) -> float:
    pts = points.astype(np.float32)
    x = pts[:, 0]
    y = pts[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def plate_geometry(points: np.ndarray) -> dict[str, float]:
    rect = order_points(points)
    top_w = float(np.linalg.norm(rect[1] - rect[0]))
    bottom_w = float(np.linalg.norm(rect[2] - rect[3]))
    left_h = float(np.linalg.norm(rect[3] - rect[0]))
    right_h = float(np.linalg.norm(rect[2] - rect[1]))
    width = (top_w + bottom_w) / 2.0
    height = (left_h + right_h) / 2.0
    aspect = width / max(height, 1e-6)
    center = rect.mean(axis=0)
    return {
        "width": width,
        "height": height,
        "aspect": aspect,
        "center_x": float(center[0]),
        "center_y": float(center[1]),
    }


def expanded_box_contains_point(box: list[int], x: float, y: float, pad_ratio: float, min_pad: float) -> bool:
    x1, y1, x2, y2 = box
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)
    pad_x = max(min_pad, w * pad_ratio)
    pad_y = max(min_pad, h * pad_ratio)
    return (x1 - pad_x) <= x <= (x2 + pad_x) and (y1 - pad_y) <= y <= (y2 + pad_y)


def plate_box_overlap_ratio(points: np.ndarray, vehicle_box: list[int]) -> float:
    px1 = float(points[:, 0].min())
    py1 = float(points[:, 1].min())
    px2 = float(points[:, 0].max())
    py2 = float(points[:, 1].max())
    vx1, vy1, vx2, vy2 = [float(v) for v in vehicle_box]
    ix1 = max(px1, vx1)
    iy1 = max(py1, vy1)
    ix2 = min(px2, vx2)
    iy2 = min(py2, vy2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    plate_box_area = max(1.0, (px2 - px1) * (py2 - py1))
    return float(inter / plate_box_area)


def vehicle_ready_for_plate(
    box: list[int],
    vehicle_conf: float,
    frame_shape: tuple[int, int, int],
    args: argparse.Namespace,
) -> tuple[bool, str]:
    if vehicle_conf < args.min_process_vehicle_conf:
        return False, f"vehicle conf {vehicle_conf:.2f} < {args.min_process_vehicle_conf}"
    x1, y1, x2, y2 = box
    width = max(0, x2 - x1)
    height = max(0, y2 - y1)
    area = width * height
    frame_h, frame_w = frame_shape[:2]
    area_ratio = area / max(1.0, float(frame_w * frame_h))
    if width < args.min_process_vehicle_width:
        return False, f"vehicle width {width} < {args.min_process_vehicle_width}"
    if height < args.min_process_vehicle_height:
        return False, f"vehicle height {height} < {args.min_process_vehicle_height}"
    if area < args.min_process_vehicle_area:
        return False, f"vehicle area {area} < {args.min_process_vehicle_area}"
    if area_ratio < args.min_process_vehicle_area_ratio:
        return False, f"vehicle area ratio {area_ratio:.4f} < {args.min_process_vehicle_area_ratio}"
    return True, ""


def passes_plate_filter(
    geometry: dict[str, float],
    plate_area: float,
    obb_score: float,
    vehicle_box: list[int],
    corners: np.ndarray,
    args: argparse.Namespace,
) -> tuple[bool, str]:
    if obb_score < args.min_plate_obb_conf:
        return False, f"plate OBB confidence {obb_score:.2f} < {args.min_plate_obb_conf}"
    if plate_area < args.min_plate_area:
        return False, f"plate area {plate_area:.1f} < {args.min_plate_area}"
    if plate_area > args.max_plate_area:
        return False, f"plate area {plate_area:.1f} > {args.max_plate_area}"
    vx1, vy1, vx2, vy2 = vehicle_box
    vehicle_area = max(1.0, float((vx2 - vx1) * (vy2 - vy1)))
    area_ratio = plate_area / vehicle_area
    if area_ratio > args.max_plate_vehicle_area_ratio:
        return False, f"plate/vehicle area ratio {area_ratio:.3f} > {args.max_plate_vehicle_area_ratio}"
    if geometry["aspect"] < args.min_plate_aspect or geometry["aspect"] > args.max_plate_aspect:
        return False, (
            f"plate aspect {geometry['aspect']:.2f} not in "
            f"[{args.min_plate_aspect}, {args.max_plate_aspect}]"
        )
    if args.require_plate_in_vehicle and not expanded_box_contains_point(
        vehicle_box,
        geometry["center_x"],
        geometry["center_y"],
        args.vehicle_box_pad_ratio,
        args.vehicle_box_min_pad,
    ):
        return False, "plate center outside vehicle box"
    overlap_ratio = plate_box_overlap_ratio(corners, vehicle_box)
    if overlap_ratio < args.min_plate_vehicle_overlap:
        return False, f"plate/vehicle overlap {overlap_ratio:.2f} < {args.min_plate_vehicle_overlap}"
    return True, ""


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def score_plate(plate_crop: np.ndarray, plate_area: float, obb_score: float) -> tuple[float, dict[str, float], dict[str, float]]:
    gray = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2GRAY)
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    contrast = float(gray.std())
    clipped_ratio = float(np.mean((gray <= 8) | (gray >= 247)))

    plate_area_score = clamp01(plate_area / 5000.0)
    sharpness_score = clamp01(math.log1p(lap_var) / math.log1p(1000.0))
    exposure_score = clamp01(1.0 - clipped_ratio * 2.0)
    contrast_score = clamp01(contrast / 64.0)
    obb_score_norm = clamp01(obb_score)

    subscores = {
        "plate_area_score": plate_area_score,
        "sharpness_score": sharpness_score,
        "exposure_score": exposure_score,
        "contrast_score": contrast_score,
        "obb_score": obb_score_norm,
    }
    total = (
        0.35 * plate_area_score
        + 0.30 * sharpness_score
        + 0.15 * exposure_score
        + 0.10 * contrast_score
        + 0.10 * obb_score_norm
    )
    raw_metrics = {
        "plate_area": float(plate_area),
        "laplacian_variance": lap_var,
        "gray_std": contrast,
        "clipped_ratio": clipped_ratio,
        "obb_confidence": float(obb_score),
    }
    return float(total), subscores, raw_metrics


def get_obb_confidence(obb: Any) -> float:
    try:
        conf = obb.conf
        if conf is None:
            return 1.0
        arr = conf.cpu().numpy().reshape(-1)
        return float(arr[0]) if arr.size else 1.0
    except Exception:
        return 1.0


def add_candidate(states: dict[int, TrackState], candidate: Candidate, topk: int) -> None:
    state = states.setdefault(candidate.track_id, TrackState())
    state.plate_hits += 1
    state.candidates.append(candidate)
    state.candidates.sort(key=lambda c: c.score, reverse=True)
    if len(state.candidates) > topk:
        state.candidates = state.candidates[:topk]


def add_rejected_candidate(states: dict[int, TrackState], candidate: RejectedCandidate, max_rejected: int) -> None:
    if max_rejected <= 0:
        return
    state = states.setdefault(candidate.track_id, TrackState())
    state.rejected_candidates.append(candidate)
    state.rejected_candidates.sort(key=lambda c: (c.obb_score, c.plate_area), reverse=True)
    if len(state.rejected_candidates) > max_rejected:
        state.rejected_candidates = state.rejected_candidates[:max_rejected]


def warp_plate(frame: np.ndarray, corners: np.ndarray) -> np.ndarray:
    rect = expand_rect(order_points(corners), pad_x=5, pad_y=5)
    dst = np.array(
        [[0, 0], [PLATE_WIDTH - 1, 0], [PLATE_WIDTH - 1, PLATE_HEIGHT - 1], [0, PLATE_HEIGHT - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(rect.astype(np.float32), dst)
    return cv2.warpPerspective(frame, matrix, (PLATE_WIDTH, PLATE_HEIGHT))


def safe_crop(frame: np.ndarray, box: list[int]) -> np.ndarray:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    x1 = max(0, min(w, x1))
    x2 = max(0, min(w, x2))
    y1 = max(0, min(h, y1))
    y2 = max(0, min(h, y2))
    if x2 <= x1 or y2 <= y1:
        return np.empty((0, 0, 3), dtype=frame.dtype)
    return frame[y1:y2, x1:x2].copy()


def resize_for_display(image: np.ndarray, max_width: int, max_height: int) -> np.ndarray:
    h, w = image.shape[:2]
    if w <= max_width and h <= max_height:
        return image
    scale = min(max_width / w, max_height / h)
    return cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def is_window_closed(window_name: str) -> bool:
    try:
        return cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        return True


def draw_status(
    frame: np.ndarray,
    track_id: int,
    box: list[int],
    corners: np.ndarray | None = None,
    score: float | None = None,
    vehicle_conf: float | None = None,
) -> None:
    vx1, vy1, vx2, vy2 = box
    cv2.rectangle(frame, (vx1, vy1), (vx2, vy2), (255, 0, 0), 2)
    label = f"ID:{track_id}"
    if vehicle_conf is not None:
        label += f" v:{vehicle_conf:.2f}"
    if score is not None:
        label += f" score:{score:.3f}"
    cv2.putText(
        frame,
        label,
        (vx1, max(24, vy1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 0, 0),
        2,
        cv2.LINE_AA,
    )
    if corners is not None:
        pts = corners.reshape((-1, 1, 2)).astype(np.int32)
        cv2.polylines(frame, [pts], isClosed=True, color=(0, 255, 0), thickness=2)


def load_chinese_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_path in CHINESE_FONT_CANDIDATES:
        if Path(font_path).exists():
            return ImageFont.truetype(font_path, size=size)
    return ImageFont.load_default()


def draw_unicode_text(
    frame: np.ndarray,
    text: str,
    pos: tuple[int, int],
    color: tuple[int, int, int],
    font_size: int = 28,
    background: tuple[int, int, int] | None = None,
) -> None:
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    font = load_chinese_font(font_size)
    x, y = pos
    bbox = draw.textbbox((x, y), text, font=font)
    if background is not None:
        pad = 4
        draw.rectangle(
            (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad),
            fill=(background[2], background[1], background[0]),
        )
    draw.text((x, y), text, fill=(color[2], color[1], color[0]), font=font)
    frame[:] = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def draw_plate_label(
    frame: np.ndarray,
    box: list[int],
    text: str,
    locked: bool,
    predicted: bool = False,
) -> None:
    x1, y1, x2, _ = box
    color = (0, 165, 255) if predicted else ((0, 220, 0) if locked else (0, 220, 255))
    label = f"PRED {text}" if predicted else (f"LOCK {text}" if locked else text)
    font_size = 30
    font = load_chinese_font(font_size)
    dummy = Image.new("RGB", (1, 1))
    bbox = ImageDraw.Draw(dummy).textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = max(0, min(frame.shape[1] - tw - 8, x1))
    ty = max(0, y1 - th - 14)
    draw_unicode_text(frame, label, (tx, ty), color=color, font_size=font_size, background=(0, 0, 0))


def update_track_motion(state: TrackState, box: list[int], frame_idx: int) -> None:
    if state.last_box is not None and state.last_detection_frame is not None:
        delta_frames = max(1, frame_idx - state.last_detection_frame)
        measured = [(current - previous) / delta_frames for current, previous in zip(box, state.last_box)]
        # Smooth detector jitter while still following a vehicle that accelerates toward the camera.
        state.velocity_xyxy = [0.7 * old + 0.3 * new for old, new in zip(state.velocity_xyxy, measured)]
    state.last_box = box.copy()
    state.last_detection_frame = frame_idx


def predict_track_box(
    state: TrackState,
    frame_idx: int,
    frame_shape: tuple[int, int, int],
    max_predict_frames: int,
) -> list[int] | None:
    if state.last_box is None or state.last_detection_frame is None:
        return None
    missing_frames = frame_idx - state.last_detection_frame
    if missing_frames <= 0 or missing_frames > max_predict_frames:
        return None

    h, w = frame_shape[:2]
    predicted = [int(round(value + velocity * missing_frames)) for value, velocity in zip(state.last_box, state.velocity_xyxy)]
    x1, y1, x2, y2 = predicted
    x1 = max(0, min(w - 1, x1))
    y1 = max(0, min(h - 1, y1))
    x2 = max(x1 + 1, min(w, x2))
    y2 = max(y1 + 1, min(h, y2))
    return [x1, y1, x2, y2]


def build_ocr_engine(engine: str) -> tuple[Any, Any, Any, bool]:
    is_plate_like = None
    use_vehicle_first = False
    if engine in ("plate-rec", "plate-rec-ort", "plate-rec-cv2"):
        from plate_rec_ocr import PlateRecONNX

        backend = {
            "plate-rec": "auto",
            "plate-rec-ort": "onnxruntime",
            "plate-rec-cv2": "cv2",
        }[engine]
        ocr = PlateRecONNX(backend=backend)
        return ocr, ocr.recognize, ocr.is_plate_like, use_vehicle_first

    if engine == "hyperlpr3":
        from hyperlpr3_ocr import HyperLPR3OCR
        from plate_rec_ocr import PlateRecONNX

        ocr = HyperLPR3OCR()
        use_vehicle_first = True
        return ocr, ocr.recognize, PlateRecONNX.is_plate_like, use_vehicle_first

    from paddleocr import PaddleOCR

    try:
        ocr = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False)
    except ValueError:
        ocr = PaddleOCR(use_textline_orientation=False, lang="ch")

    def recognize(image: Any) -> tuple[str | None, float | None]:
        return parse_ocr_result(ocr_image(ocr, image))

    return ocr, recognize, is_plate_like, use_vehicle_first


def build_weighted_consensus(events: deque[dict[str, Any]]) -> dict[str, Any] | None:
    if not events:
        return None

    groups: dict[int, list[dict[str, Any]]] = {}
    for event in events:
        groups.setdefault(len(event["text"]), []).append(event)
    target_length, target_events = max(
        groups.items(),
        key=lambda item: sum(float(event["weight"]) for event in item[1]),
    )

    position_votes = [Counter() for _ in range(target_length)]
    position_total = [0.0 for _ in range(target_length)]
    for event in target_events:
        weight = float(event["weight"])
        for index, char in enumerate(event["text"]):
            position_votes[index][char] += weight
            position_total[index] += weight

    text_chars = []
    position_details = []
    for index, votes in enumerate(position_votes):
        char, char_weight = votes.most_common(1)[0]
        total = position_total[index]
        ratio = float(char_weight / total) if total else 0.0
        text_chars.append(char)
        position_details.append(
            {
                "index": index,
                "char": char,
                "weight": float(char_weight),
                "total_weight": float(total),
                "ratio": ratio,
            }
        )

    return {
        "text": "".join(text_chars),
        "target_length": target_length,
        "event_count": len(target_events),
        "total_weight": float(sum(float(event["weight"]) for event in target_events)),
        "min_position_ratio": min(item["ratio"] for item in position_details),
        "mean_position_ratio": float(np.mean([item["ratio"] for item in position_details])),
        "positions": position_details,
    }


def add_vote(
    state: TrackState,
    text: str,
    confidence: float | None,
    frame_idx: int,
    args: argparse.Namespace,
    source: str,
    vehicle_conf: float,
    candidate_score: float | None = None,
    obb_conf: float | None = None,
) -> bool:
    if not text or len(text) < args.min_lock_text_len or state.locked_text:
        return False
    if confidence is not None and confidence < args.min_ocr_conf:
        return False

    ocr_conf = float(confidence) if confidence is not None else 1.0
    quality_weight = 1.0
    if source == "vehicle":
        quality_weight = max(0.5, vehicle_conf)
    else:
        quality_weight = (0.5 + 0.5 * (candidate_score if candidate_score is not None else 0.5))
        quality_weight *= 0.5 + 0.5 * (obb_conf if obb_conf is not None else 0.5)
    weight = ocr_conf * quality_weight

    state.vote_history.append(text)
    state.vote_events.append(
        {
            "frame_idx": frame_idx,
            "text": text,
            "confidence": confidence,
            "source": source,
            "vehicle_confidence": vehicle_conf,
            "candidate_score": candidate_score,
            "obb_confidence": obb_conf,
            "weight": weight,
        }
    )
    state.vote_counts[text] += 1
    while len(state.vote_history) > args.vote_window:
        old_text = state.vote_history.popleft()
        state.vote_events.popleft()
        state.vote_counts[old_text] -= 1
        if state.vote_counts[old_text] <= 0:
            del state.vote_counts[old_text]

    consensus = build_weighted_consensus(state.vote_events)
    if (
        consensus is not None
        and consensus["event_count"] >= args.vote_threshold
        and consensus["min_position_ratio"] >= args.min_char_vote_ratio
    ):
        state.locked_text = consensus["text"]
        state.locked_conf = consensus["mean_position_ratio"]
        state.locked_frame = frame_idx
        state.locked_consensus = consensus
        return True
    return False


def lock_log_message(track_id: int, state: TrackState, frame_idx: int) -> str:
    consensus = state.locked_consensus or {}
    event_count = consensus.get("event_count", 0)
    min_ratio = float(consensus.get("min_position_ratio", 0.0))
    return (
        f"[LOCK] track={track_id} plate={state.locked_text} frame={frame_idx} "
        f"events={event_count} min_char_ratio={min_ratio:.3f}"
    )


def run_ocr_for_saved_candidates(states: dict[int, TrackState], engine: str) -> None:
    print(f"Loading {engine} OCR for Top-K candidates...")
    try:
        _ocr, recognize, is_plate_like, use_vehicle_first = build_ocr_engine(engine)
    except Exception as exc:
        print(f"WARNING: OCR could not be initialized. Saving Top-K without OCR. Error: {exc}")
        return
    for state in states.values():
        for candidate in state.candidates:
            try:
                text = None
                confidence = None
                images = [candidate.vehicle_crop, candidate.plate_crop] if use_vehicle_first else [candidate.plate_crop]
                for image in images:
                    text, confidence = recognize(image)
                    if text:
                        break
            except Exception as exc:
                print(f"WARNING: OCR failed for track {candidate.track_id} frame {candidate.frame_idx}: {exc}")
                continue
            if text:
                candidate.ocr_engine = engine
                if is_plate_like is None or is_plate_like(text):
                    candidate.ocr_text = text
                    candidate.ocr_conf = confidence
                else:
                    candidate.ocr_raw_text = text
                    candidate.ocr_raw_conf = confidence


def run_single_ocr(ocr: Any, plate_crop: np.ndarray) -> tuple[str | None, float | None]:
    return parse_ocr_result(ocr_image(ocr, plate_crop))


def ocr_image(ocr: Any, image: Any) -> Any:
    try:
        return ocr.ocr(image, cls=False)
    except TypeError:
        return ocr.ocr(image)


def parse_ocr_result(result: Any) -> tuple[str | None, float | None]:
    if not result:
        return None, None

    try:
        if isinstance(result, list) and result and isinstance(result[0], list) and result[0]:
            first = result[0][0]
            if isinstance(first, (list, tuple)) and len(first) >= 2:
                text_score = first[1]
                if isinstance(text_score, (list, tuple)) and len(text_score) >= 2:
                    return str(text_score[0]), float(text_score[1])
    except Exception:
        pass

    try:
        first = result[0] if isinstance(result, list) else result
        getter = first.get if hasattr(first, "get") else None
        if getter:
            texts = getter("rec_texts") or getter("texts") or getter("text")
            scores = getter("rec_scores") or getter("scores") or getter("confidence")
            if isinstance(texts, list) and texts:
                score = scores[0] if isinstance(scores, list) and scores else None
                return str(texts[0]), float(score) if score is not None else None
            if isinstance(texts, str):
                return texts, float(scores) if isinstance(scores, (float, int)) else None
    except Exception:
        pass

    return None, None


def candidate_summary(candidate: Candidate, rank: int) -> dict[str, Any]:
    data: dict[str, Any] = {
        "rank": rank,
        "frame_idx": candidate.frame_idx,
        "track_id": candidate.track_id,
        "score": candidate.score,
        "subscores": candidate.subscores,
        "raw_metrics": candidate.raw_metrics,
        "geometry": candidate.geometry,
        "vehicle_confidence": candidate.vehicle_conf,
        "vehicle_box_xyxy": candidate.vehicle_box,
        "plate_corners_xy": candidate.plate_corners,
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


def save_outputs(states: dict[int, TrackState], run_dir: Path, args: argparse.Namespace, video_meta: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    tracks_index = []

    for track_id in sorted(states):
        state = states[track_id]
        if not state.candidates and not state.rejected_candidates and not state.vote_history and not state.locked_text:
            continue

        track_dir = run_dir / f"track_{track_id}"
        track_dir.mkdir(parents=True, exist_ok=True)
        summaries = []

        for rank, candidate in enumerate(state.candidates, start=1):
            cv2.imwrite(str(track_dir / f"full_rank{rank}.jpg"), candidate.full_frame)
            cv2.imwrite(str(track_dir / f"vehicle_rank{rank}.jpg"), candidate.vehicle_crop)
            cv2.imwrite(str(track_dir / f"plate_rank{rank}.jpg"), candidate.plate_crop)
            summaries.append(candidate_summary(candidate, rank))

        rejected_summaries = []
        if state.rejected_candidates:
            rejected_dir = track_dir / "rejected"
            rejected_dir.mkdir(parents=True, exist_ok=True)
            for rank, candidate in enumerate(state.rejected_candidates, start=1):
                cv2.imwrite(str(rejected_dir / f"full_reject{rank}.jpg"), candidate.full_frame)
                cv2.imwrite(str(rejected_dir / f"vehicle_reject{rank}.jpg"), candidate.vehicle_crop)
                cv2.imwrite(str(rejected_dir / f"plate_reject{rank}.jpg"), candidate.plate_crop)
                rejected_summaries.append(rejected_summary(candidate, rank))

        summary = {
            "track_id": track_id,
            "seen_frames": state.seen_frames,
            "plate_hits": state.plate_hits,
            "locked_text": state.locked_text,
            "locked_confidence": state.locked_conf,
            "locked_frame": state.locked_frame,
            "locked_consensus": state.locked_consensus,
            "vote_history": list(state.vote_history),
            "vote_events": list(state.vote_events),
            "vote_counts": dict(state.vote_counts),
            "topk": len(state.candidates),
            "candidates": summaries,
            "rejected_count": len(state.rejected_candidates),
            "rejected_candidates": rejected_summaries,
        }
        with (track_dir / "summary.json").open("w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        best_score = state.candidates[0].score if state.candidates else None
        best_frame_idx = state.candidates[0].frame_idx if state.candidates else None
        tracks_index.append(
            {
                "track_id": track_id,
                "seen_frames": state.seen_frames,
                "plate_hits": state.plate_hits,
                "best_score": best_score,
                "best_frame_idx": best_frame_idx,
                "locked_text": state.locked_text,
                "locked_confidence": state.locked_conf,
                "locked_frame": state.locked_frame,
                "locked_consensus": state.locked_consensus,
                "vote_history": list(state.vote_history),
                "vote_events": list(state.vote_events),
                "vote_counts": dict(state.vote_counts),
                "rejected_count": len(state.rejected_candidates),
                "dir": str(track_dir),
            }
        )

    run_summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "args": vars(args),
        "video": video_meta,
        "track_count": len(tracks_index),
        "tracks": tracks_index,
    }
    with (run_dir / "run_summary.json").open("w", encoding="utf-8") as f:
        json.dump(run_summary, f, ensure_ascii=False, indent=2)


def run_topk_capture(args: argparse.Namespace) -> Path:
    video_path = Path(args.video)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(args.output) / f"run_{timestamp}"

    print("Loading models...")
    vehicle_model = YOLO(args.vehicle_model)
    plate_model = YOLO(args.plate_model)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    video_meta = {
        "path": str(video_path),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": float(cap.get(cv2.CAP_PROP_FPS)),
        "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
    }
    print(f"Video: {video_meta['width']}x{video_meta['height']} @ {video_meta['fps']:.2f} FPS")

    states: dict[int, TrackState] = {}
    tracker = SimpleIoUTracker(iou_threshold=args.track_iou, max_age=args.track_max_age)
    frame_idx = 0
    total_plate_hits = 0
    should_stop = False
    live_recognize = None
    live_is_plate_like = None
    live_use_vehicle_first = False
    if args.live_ocr:
        print(f"Loading {args.ocr_engine} for live OCR voting...")
        try:
            _ocr, live_recognize, live_is_plate_like, live_use_vehicle_first = build_ocr_engine(args.ocr_engine)
        except Exception as exc:
            print(f"WARNING: Live OCR could not be initialized. Continuing without live OCR. Error: {exc}")
            live_recognize = None
    window_name = "Top-K ALPR Capture"
    if args.show_window:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(window_name, args.display_width, args.display_height)

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame_idx += 1
            raw_frame = frame.copy()
            display_frame = raw_frame.copy() if args.show_window else None
            h, w = frame.shape[:2]
            current_track_ids: set[int] = set()

            if args.tracker == "ultralytics":
                try:
                    v_results = vehicle_model.track(
                        frame,
                        imgsz=args.vehicle_imgsz,
                        persist=True,
                        classes=VEHICLE_CLASSES,
                        conf=args.vehicle_conf,
                        tracker=args.ultralytics_tracker,
                        verbose=False,
                    )
                except ModuleNotFoundError as exc:
                    if exc.name == "lap":
                        raise RuntimeError(
                            "Ultralytics tracker requires the 'lap' package. Install it, then rerun with "
                            "--tracker ultralytics, or use the default --tracker iou."
                        ) from exc
                    raise
                boxes_obj = v_results[0].boxes
                if boxes_obj is not None and len(boxes_obj) > 0 and boxes_obj.id is not None:
                    boxes = boxes_obj.xyxy.cpu().numpy().astype(int)
                    track_ids = boxes_obj.id.cpu().numpy().astype(int)
                    confs = boxes_obj.conf.cpu().numpy().astype(float) if boxes_obj.conf is not None else np.ones(len(boxes))
                    tracked_boxes = [
                        (int(tid), box.astype(np.float32), float(conf))
                        for box, tid, conf in zip(boxes, track_ids, confs)
                    ]
                else:
                    tracked_boxes = []
            else:
                v_results = vehicle_model(
                    frame,
                    imgsz=args.vehicle_imgsz,
                    classes=VEHICLE_CLASSES,
                    conf=args.vehicle_conf,
                    verbose=False,
                )
                boxes_obj = v_results[0].boxes
                if boxes_obj is not None and len(boxes_obj) > 0:
                    boxes = boxes_obj.xyxy.cpu().numpy().astype(int)
                    confs = boxes_obj.conf.cpu().numpy().astype(float) if boxes_obj.conf is not None else np.ones(len(boxes))
                    tracked_boxes = tracker.update(boxes, confs, frame_idx)
                else:
                    tracked_boxes = []

            if tracked_boxes:
                for track_id, box_arr, vehicle_conf in tracked_boxes:
                    current_track_ids.add(track_id)
                    state = states.setdefault(track_id, TrackState())
                    state.seen_frames += 1

                    vx1, vy1, vx2, vy2 = [int(v) for v in box_arr.tolist()]
                    vehicle_box = [vx1, vy1, vx2, vy2]
                    update_track_motion(state, vehicle_box, frame_idx)
                    if display_frame is not None:
                        draw_status(display_frame, track_id, vehicle_box, vehicle_conf=vehicle_conf)
                        if state.locked_text:
                            draw_plate_label(display_frame, vehicle_box, state.locked_text, locked=True)

                    if state.locked_text and args.skip_locked_detection:
                        continue

                    ready_for_plate, wait_reason = vehicle_ready_for_plate(vehicle_box, vehicle_conf, raw_frame.shape, args)
                    if not ready_for_plate:
                        if display_frame is not None and args.show_waiting:
                            cv2.putText(
                                display_frame,
                                "WAIT " + wait_reason[:42],
                                (vx1, min(h - 10, vy2 + 24)),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.55,
                                (0, 165, 255),
                                1,
                                cv2.LINE_AA,
                            )
                        continue

                    cx1 = max(0, vx1 - ROI_MARGIN)
                    cy1 = max(0, vy1 - ROI_MARGIN)
                    cx2 = min(w, vx2 + ROI_MARGIN)
                    cy2 = min(h, vy2 + ROI_MARGIN)
                    roi_crop = raw_frame[cy1:cy2, cx1:cx2].copy()
                    if roi_crop.size == 0:
                        continue
                    vehicle_crop = safe_crop(raw_frame, vehicle_box)
                    if vehicle_crop.size == 0:
                        continue

                    ocr_text = None
                    ocr_conf = None
                    ocr_vote_recorded = False
                    if live_recognize is not None and live_use_vehicle_first:
                        try:
                            ocr_text, ocr_conf = live_recognize(vehicle_crop)
                        except Exception as exc:
                            print(f"WARNING: live vehicle OCR failed at frame {frame_idx}, track {track_id}: {exc}")

                        if ocr_text:
                            locked_now = False
                            if live_is_plate_like is None or live_is_plate_like(ocr_text):
                                locked_now = add_vote(
                                    state,
                                    ocr_text,
                                    ocr_conf,
                                    frame_idx,
                                    args,
                                    source="vehicle",
                                    vehicle_conf=vehicle_conf,
                                )
                                ocr_vote_recorded = True
                                if locked_now:
                                    print(lock_log_message(track_id, state, frame_idx))
                            if display_frame is not None:
                                draw_unicode_text(
                                    display_frame,
                                    f"{ocr_text} {ocr_conf:.2f}" if ocr_conf is not None else ocr_text,
                                    (max(0, vx1), min(h - 36, vy2 + 8)),
                                    color=(0, 255, 255),
                                    font_size=28,
                                )
                                if state.locked_text:
                                    draw_plate_label(display_frame, vehicle_box, state.locked_text, locked=True)
                                elif not locked_now:
                                    draw_plate_label(display_frame, vehicle_box, ocr_text, locked=False)

                    if state.locked_text and args.skip_locked_detection:
                        continue

                    p_results = plate_model(
                        roi_crop,
                        imgsz=args.plate_imgsz,
                        conf=args.plate_conf,
                        verbose=False,
                    )
                    obb_result = p_results[0].obb
                    if obb_result is None or len(obb_result) == 0:
                        continue

                    best_obb = obb_result[0]
                    local_corners = best_obb.xyxyxyxy[0].cpu().numpy().astype(np.float32)
                    global_corners = local_corners + np.array([[cx1, cy1]], dtype=np.float32)
                    plate_crop = warp_plate(raw_frame, global_corners)
                    if plate_crop.size == 0:
                        continue

                    obb_score = get_obb_confidence(best_obb)
                    plate_area = polygon_area(global_corners)
                    geometry = plate_geometry(global_corners)
                    geometry["vehicle_overlap"] = plate_box_overlap_ratio(global_corners, vehicle_box)
                    keep_plate, reject_reason = passes_plate_filter(
                        geometry, plate_area, obb_score, vehicle_box, global_corners, args
                    )
                    if not keep_plate:
                        rejected = RejectedCandidate(
                            frame_idx=frame_idx,
                            track_id=track_id,
                            reason=reject_reason,
                            obb_score=obb_score,
                            plate_area=plate_area,
                            geometry=geometry,
                            vehicle_conf=vehicle_conf,
                            vehicle_box=vehicle_box,
                            plate_corners=global_corners.tolist(),
                            full_frame=raw_frame.copy(),
                            vehicle_crop=vehicle_crop,
                            plate_crop=plate_crop,
                        )
                        add_rejected_candidate(states, rejected, args.max_rejected_per_track)
                        if args.show_rejected and display_frame is not None:
                            draw_status(display_frame, track_id, vehicle_box, global_corners, None, vehicle_conf)
                            cv2.putText(
                                display_frame,
                                reject_reason[:48],
                                (max(0, int(geometry["center_x"]) - 80), max(20, int(geometry["center_y"]) - 10)),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.45,
                                (0, 0, 255),
                                1,
                                cv2.LINE_AA,
                            )
                        continue

                    score, subscores, raw_metrics = score_plate(plate_crop, plate_area, obb_score)
                    if live_recognize is not None and (not live_use_vehicle_first or not ocr_text):
                        try:
                            ocr_text, ocr_conf = live_recognize(plate_crop)
                        except Exception as exc:
                            print(f"WARNING: live plate OCR failed at frame {frame_idx}, track {track_id}: {exc}")

                    if display_frame is not None:
                        draw_status(display_frame, track_id, vehicle_box, global_corners, score, vehicle_conf)
                        if ocr_text:
                            locked_now = False
                            if not ocr_vote_recorded and (live_is_plate_like is None or live_is_plate_like(ocr_text)):
                                locked_now = add_vote(
                                    state,
                                    ocr_text,
                                    ocr_conf,
                                    frame_idx,
                                    args,
                                    source="plate",
                                    vehicle_conf=vehicle_conf,
                                    candidate_score=score,
                                    obb_conf=obb_score,
                                )
                                ocr_vote_recorded = True
                                if locked_now:
                                    print(lock_log_message(track_id, state, frame_idx))
                            draw_unicode_text(
                                display_frame,
                                f"{ocr_text} {ocr_conf:.2f}" if ocr_conf is not None else ocr_text,
                                (max(0, vx1), min(h - 36, vy2 + 8)),
                                color=(0, 255, 255),
                                font_size=28,
                            )
                            if state.locked_text:
                                draw_plate_label(display_frame, vehicle_box, state.locked_text, locked=True)
                            elif not locked_now:
                                draw_plate_label(display_frame, vehicle_box, ocr_text, locked=False)
                    elif ocr_text and not ocr_vote_recorded and (live_is_plate_like is None or live_is_plate_like(ocr_text)):
                        locked_now = add_vote(
                            state,
                            ocr_text,
                            ocr_conf,
                            frame_idx,
                            args,
                            source="plate",
                            vehicle_conf=vehicle_conf,
                            candidate_score=score,
                            obb_conf=obb_score,
                        )
                        ocr_vote_recorded = True
                        if locked_now:
                            print(lock_log_message(track_id, state, frame_idx))

                    candidate = Candidate(
                        frame_idx=frame_idx,
                        track_id=track_id,
                        score=score,
                        subscores=subscores,
                        raw_metrics=raw_metrics,
                        geometry=geometry,
                        vehicle_conf=vehicle_conf,
                        vehicle_box=vehicle_box,
                        plate_corners=global_corners.tolist(),
                        full_frame=raw_frame.copy(),
                        vehicle_crop=vehicle_crop,
                        plate_crop=plate_crop,
                        ocr_text=ocr_text if ocr_text and (live_is_plate_like is None or live_is_plate_like(ocr_text)) else None,
                        ocr_conf=ocr_conf if ocr_text and (live_is_plate_like is None or live_is_plate_like(ocr_text)) else None,
                        ocr_raw_text=ocr_text if ocr_text and live_is_plate_like is not None and not live_is_plate_like(ocr_text) else None,
                        ocr_raw_conf=ocr_conf if ocr_text and live_is_plate_like is not None and not live_is_plate_like(ocr_text) else None,
                        ocr_engine=args.ocr_engine if ocr_text else None,
                    )
                    add_candidate(states, candidate, args.topk)
                    total_plate_hits += 1

            if display_frame is not None:
                for track_id, state in states.items():
                    if not state.locked_text or track_id in current_track_ids:
                        continue
                    predicted_box = predict_track_box(
                        state,
                        frame_idx,
                        raw_frame.shape,
                        args.max_predict_frames,
                    )
                    if predicted_box is None:
                        continue
                    px1, py1, px2, py2 = predicted_box
                    cv2.rectangle(display_frame, (px1, py1), (px2, py2), (0, 165, 255), 2)
                    cv2.putText(
                        display_frame,
                        f"PRED ID:{track_id}",
                        (px1, max(24, py1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 165, 255),
                        2,
                        cv2.LINE_AA,
                    )
                    draw_plate_label(display_frame, predicted_box, state.locked_text, locked=True, predicted=True)

            if frame_idx % args.progress_interval == 0:
                active_tracks = sum(1 for s in states.values() if s.candidates)
                print(
                    f"Processed {frame_idx} frames | tracks_with_plates={active_tracks} | plate_hits={total_plate_hits}"
                )

            if display_frame is not None:
                cv2.putText(
                    display_frame,
                    f"frame:{frame_idx} plate_hits:{total_plate_hits}",
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
                shown = resize_for_display(display_frame, args.display_width, args.display_height)
                cv2.imshow(window_name, shown)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q") or is_window_closed(window_name):
                    print("Display window closed. Stopping early and saving current Top-K candidates.")
                    should_stop = True

            if args.max_frames and frame_idx >= args.max_frames:
                print(f"Stopping early at --max-frames={args.max_frames}")
                break
            if should_stop:
                break
    except KeyboardInterrupt:
        print("\nCtrl+C received. Saving current Top-K candidates before exit...")

    cap.release()
    if args.show_window:
        cv2.destroyWindow(window_name)

    if args.with_ocr:
        run_ocr_for_saved_candidates(states, args.ocr_engine)

    save_outputs(states, run_dir, args, video_meta)
    print(f"Saved Top-K capture run: {run_dir}")
    return run_dir


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract Top-K license plate candidates from a video.")
    parser.add_argument("--video", default=DEFAULT_VIDEO, help="Input video path.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Base output directory.")
    parser.add_argument("--vehicle-model", default=DEFAULT_VEHICLE_MODEL, help="YOLO vehicle model path.")
    parser.add_argument("--plate-model", default=DEFAULT_PLATE_MODEL, help="YOLO OBB plate model path.")
    parser.add_argument("--topk", type=int, default=5, help="Number of candidates to keep per track.")
    parser.add_argument("--vehicle-conf", type=float, default=0.55, help="Vehicle detection confidence threshold.")
    parser.add_argument("--plate-conf", type=float, default=0.25, help="Plate OBB confidence threshold.")
    parser.add_argument("--vehicle-imgsz", type=int, default=640, help="YOLO vehicle inference image size.")
    parser.add_argument("--plate-imgsz", type=int, default=320, help="YOLO plate inference image size.")
    parser.add_argument("--with-ocr", action="store_true", help="Run OCR on saved Top-K candidates.")
    parser.add_argument(
        "--ocr-engine",
        choices=["plate-rec", "plate-rec-ort", "plate-rec-cv2", "hyperlpr3", "paddle"],
        default="hyperlpr3",
        help="OCR engine used with --with-ocr.",
    )
    parser.add_argument(
        "--live-ocr",
        action="store_true",
        help="Run the selected OCR engine during processing, vote by track, and draw live text in preview.",
    )
    parser.add_argument("--vote-window", type=int, default=10, help="Maximum recent OCR texts kept for each track vote.")
    parser.add_argument("--vote-threshold", type=int, default=3, help="Minimum valid OCR events needed before weighted character consensus can lock.")
    parser.add_argument(
        "--min-char-vote-ratio",
        type=float,
        default=0.65,
        help="Minimum weighted agreement required at every character position before locking.",
    )
    parser.add_argument("--min-ocr-conf", type=float, default=0.7, help="Minimum OCR confidence allowed to enter live voting.")
    parser.add_argument("--min-lock-text-len", type=int, default=7, help="Minimum text length allowed for plate locking.")
    parser.add_argument(
        "--skip-locked-detection",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="After a track is locked, skip plate detection/OCR and only draw the locked text.",
    )
    parser.add_argument(
        "--max-predict-frames",
        type=int,
        default=12,
        help="Maximum frames to draw an orange predicted locked label after a vehicle detection is missed.",
    )
    parser.add_argument("--max-frames", type=int, default=0, help="Optional debug limit. 0 means full video.")
    parser.add_argument("--progress-interval", type=int, default=100, help="Progress print interval in frames.")
    parser.add_argument("--tracker", choices=["iou", "ultralytics"], default="iou", help="Vehicle tracking backend.")
    parser.add_argument(
        "--ultralytics-tracker",
        default="bytetrack.yaml",
        help="Ultralytics tracker yaml, e.g. bytetrack.yaml or botsort.yaml.",
    )
    parser.add_argument("--track-iou", type=float, default=0.3, help="IoU threshold for the built-in lightweight tracker.")
    parser.add_argument("--track-max-age", type=int, default=30, help="Frames to keep an unmatched track alive.")
    parser.add_argument(
        "--min-process-vehicle-conf",
        type=float,
        default=0.65,
        help="Skip plate/OCR processing until vehicle detection confidence reaches this value.",
    )
    parser.add_argument("--min-process-vehicle-width", type=int, default=90, help="Skip plate/OCR processing until vehicle box is at least this wide.")
    parser.add_argument("--min-process-vehicle-height", type=int, default=70, help="Skip plate/OCR processing until vehicle box is at least this tall.")
    parser.add_argument("--min-process-vehicle-area", type=int, default=8000, help="Skip plate/OCR processing until vehicle box area reaches this value.")
    parser.add_argument(
        "--min-process-vehicle-area-ratio",
        type=float,
        default=0.003,
        help="Skip plate/OCR processing until vehicle box area/frame area reaches this ratio.",
    )
    parser.add_argument("--min-plate-obb-conf", type=float, default=0.5, help="Reject OBB plates below this confidence.")
    parser.add_argument("--min-plate-area", type=float, default=250.0, help="Reject OBB plates below this polygon area.")
    parser.add_argument("--max-plate-area", type=float, default=8000.0, help="Reject implausibly large OBB plate polygons.")
    parser.add_argument("--max-rejected-per-track", type=int, default=5, help="Maximum rejected OBB debug samples saved per track.")
    parser.add_argument(
        "--max-plate-vehicle-area-ratio",
        type=float,
        default=0.04,
        help="Reject plates whose polygon area is too large relative to the vehicle box.",
    )
    parser.add_argument("--min-plate-aspect", type=float, default=2.0, help="Reject OBB plates below this aspect ratio.")
    parser.add_argument("--max-plate-aspect", type=float, default=6.0, help="Reject OBB plates above this aspect ratio.")
    parser.add_argument(
        "--require-plate-in-vehicle",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require plate center to be inside the vehicle box plus padding.",
    )
    parser.add_argument("--vehicle-box-pad-ratio", type=float, default=0.2, help="Relative padding for vehicle-box plate filter.")
    parser.add_argument("--vehicle-box-min-pad", type=float, default=20.0, help="Minimum pixel padding for vehicle-box plate filter.")
    parser.add_argument(
        "--min-plate-vehicle-overlap",
        type=float,
        default=0.5,
        help="Minimum fraction of the plate bounding box that must overlap the vehicle box.",
    )
    parser.add_argument("--show-rejected", action="store_true", help="Draw rejected plate OBBs in the preview window.")
    parser.add_argument("--show-waiting", action="store_true", help="Draw why small/far vehicles are not processed yet.")
    parser.add_argument("--show-window", action="store_true", help="Show a live OpenCV preview window.")
    parser.add_argument("--display-width", type=int, default=1280, help="Preview window width limit.")
    parser.add_argument("--display-height", type=int, default=720, help="Preview window height limit.")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.topk <= 0:
        raise ValueError("--topk must be positive")
    run_topk_capture(args)


if __name__ == "__main__":
    main()
