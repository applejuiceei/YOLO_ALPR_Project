from __future__ import annotations

import argparse
from collections import deque
import json
import os
import queue
import site
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("YOLO_CONFIG_DIR", str(Path(__file__).resolve().parent / "Ultralytics"))
LOCAL_DEPS_DIR = Path(__file__).resolve().parent / "python_deps"
if LOCAL_DEPS_DIR.exists():
    site.addsitedir(str(LOCAL_DEPS_DIR))
LOCAL_OCR_DEPS_DIR = Path(__file__).resolve().parent / "python_deps_ocr"
if LOCAL_OCR_DEPS_DIR.exists():
    site.addsitedir(str(LOCAL_OCR_DEPS_DIR))

import cv2
import numpy as np
from ultralytics import YOLO

from alpr_topk_capture_demo import (
    DEFAULT_PLATE_MODEL,
    DEFAULT_VEHICLE_MODEL,
    DEFAULT_VIDEO,
    ROI_MARGIN,
    VEHICLE_CLASSES,
    SimpleIoUTracker,
    TrackState,
    apply_event_vote,
    build_ocr_engine,
    draw_realtime_hud,
    get_obb_confidence,
    passes_plate_filter,
    plate_box_overlap_ratio,
    plate_geometry,
    polygon_area,
    perform_ocr_call,
    safe_crop,
    vehicle_ready_for_plate,
    warp_plate,
)


DEFAULT_OUTPUT = r"D:\YOLO_ALPR_Project\runs_realtime_async"


@dataclass
class FramePacket:
    frame_idx: int
    captured_at: float
    frame: np.ndarray


class LatestFrameBuffer:
    """Single-slot buffer: recognition always receives the newest available frame."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._packet: FramePacket | None = None
        self._in_use = False
        self._version = 0
        self._closed = False
        self.published = 0
        self.overwritten = 0

    def publish(self, packet: FramePacket) -> None:
        with self._condition:
            if self._closed:
                return
            if self._packet is not None:
                self.overwritten += 1
            self._packet = packet
            self._version += 1
            self.published += 1
            self._condition.notify()

    def get(self, last_version: int, timeout: float = 0.2) -> tuple[int, FramePacket | None]:
        with self._condition:
            self._condition.wait_for(
                lambda: self._closed or (self._packet is not None and self._version != last_version),
                timeout=timeout,
            )
            if self._packet is None or self._version == last_version:
                return last_version, None
            packet = self._packet
            version = self._version
            self._packet = None
            self._in_use = True
            return version, packet

    def task_done(self) -> None:
        with self._condition:
            self._in_use = False
            self._condition.notify_all()

    def wait_idle(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._in_use:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return True

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


@dataclass
class WorkerSnapshot:
    model_ready: bool = False
    load_seconds: float = 0.0
    processed_frames: int = 0
    emitted_results: int = 0
    failed_frames: int = 0
    last_frame_idx: int = 0
    last_total_ms: float = 0.0
    last_vehicle_ms: float = 0.0
    last_plate_ms: float = 0.0
    last_ocr_ms: float = 0.0
    total_processing_seconds: float = 0.0
    total_vehicle_ms: float = 0.0
    total_plate_ms: float = 0.0
    total_ocr_ms: float = 0.0
    ocr_calls: int = 0
    frames_with_plate_stage: int = 0
    frames_with_ocr: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        processed_fps = (
            self.processed_frames / self.total_processing_seconds
            if self.total_processing_seconds > 0
            else 0.0
        )
        average_ocr_ms = self.total_ocr_ms / self.ocr_calls if self.ocr_calls > 0 else 0.0
        return {
            "model_ready": self.model_ready,
            "load_seconds": round(self.load_seconds, 3),
            "processed_frames": self.processed_frames,
            "processed_fps": round(processed_fps, 3),
            "emitted_results": self.emitted_results,
            "failed_frames": self.failed_frames,
            "last_frame_idx": self.last_frame_idx,
            "last_total_ms": round(self.last_total_ms, 3),
            "last_vehicle_ms": round(self.last_vehicle_ms, 3),
            "last_plate_ms": round(self.last_plate_ms, 3),
            "last_ocr_ms": round(self.last_ocr_ms, 3),
            "total_vehicle_ms": round(self.total_vehicle_ms, 3),
            "total_plate_ms": round(self.total_plate_ms, 3),
            "total_ocr_ms": round(self.total_ocr_ms, 3),
            "ocr_calls": self.ocr_calls,
            "average_ocr_ms": round(average_ocr_ms, 3),
            "frames_with_plate_stage": self.frames_with_plate_stage,
            "frames_with_ocr": self.frames_with_ocr,
            "error": self.error,
        }


class SharedWorkerStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = WorkerSnapshot()

    def update(self, **values: Any) -> None:
        with self._lock:
            for key, value in values.items():
                setattr(self._snapshot, key, value)

    def add_processed(self, result_count: int, total_seconds: float, timings: dict[str, float], frame_idx: int) -> None:
        with self._lock:
            self._snapshot.processed_frames += 1
            self._snapshot.emitted_results += result_count
            self._snapshot.last_frame_idx = frame_idx
            self._snapshot.total_processing_seconds += total_seconds
            self._snapshot.last_total_ms = timings.get("total_ms", 0.0)
            self._snapshot.last_vehicle_ms = timings.get("vehicle_ms", 0.0)
            self._snapshot.last_plate_ms = timings.get("plate_ms", 0.0)
            self._snapshot.last_ocr_ms = timings.get("ocr_ms", 0.0)
            self._snapshot.total_vehicle_ms += timings.get("vehicle_ms", 0.0)
            self._snapshot.total_plate_ms += timings.get("plate_ms", 0.0)
            self._snapshot.total_ocr_ms += timings.get("ocr_ms", 0.0)
            self._snapshot.ocr_calls += int(timings.get("ocr_calls", 0.0))
            if timings.get("plate_ms", 0.0) > 0:
                self._snapshot.frames_with_plate_stage += 1
            if timings.get("ocr_ms", 0.0) > 0:
                self._snapshot.frames_with_ocr += 1

    def add_failure(self, error: str, frame_idx: int) -> None:
        with self._lock:
            self._snapshot.failed_frames += 1
            self._snapshot.last_frame_idx = frame_idx
            self._snapshot.error = error

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot.to_dict()


@dataclass
class RuntimeState:
    recognition_enabled: threading.Event = field(default_factory=threading.Event)
    stop_requested: threading.Event = field(default_factory=threading.Event)
    model_ready: threading.Event = field(default_factory=threading.Event)
    model_failed: threading.Event = field(default_factory=threading.Event)


class AsyncRecognizer:
    def __init__(
        self,
        args: argparse.Namespace,
        frames: LatestFrameBuffer,
        results: queue.Queue[dict[str, Any]],
        runtime: RuntimeState,
        stats: SharedWorkerStats,
    ) -> None:
        self.args = args
        self.frames = frames
        self.results = results
        self.runtime = runtime
        self.stats = stats
        self.vehicle_model: YOLO | None = None
        self.plate_model: YOLO | None = None
        self.recognize: Any = None
        self.ocr: Any = None
        self.is_plate_like: Any = None
        self.use_vehicle_first = False
        self.tracker = (
            SimpleIoUTracker(iou_threshold=args.track_iou, max_age=args.track_max_age)
            if args.tracking == "iou"
            else None
        )
        self.track_states: dict[int, TrackState] = {}

    def locked_tracks(self) -> list[dict[str, Any]]:
        return [
            {
                "track_id": track_id,
                "text": state.locked_text,
                "confidence": state.locked_conf,
                "frame": state.locked_frame,
            }
            for track_id, state in sorted(self.track_states.items())
            if state.locked_text
        ]

    def load(self) -> None:
        load_started = time.perf_counter()
        if self.args.torch_threads > 0:
            import torch

            torch.set_num_threads(self.args.torch_threads)
            try:
                torch.set_num_interop_threads(1)
            except RuntimeError:
                pass

        if self.args.pipeline == "vehicle":
            self.vehicle_model = YOLO(self.args.vehicle_model)
        if self.args.pipeline == "vehicle" and self.args.plate_stage != "off":
            self.plate_model = YOLO(self.args.plate_model)
        if self.args.ocr_engine != "none":
            self.ocr, self.recognize, self.is_plate_like, self.use_vehicle_first = build_ocr_engine(
                self.args.ocr_engine
            )
            if self.args.ocr_engine == "hyperlpr3-rec":
                warmup_image = np.zeros((96, 320, 3), dtype=np.uint8)
                for _index in range(self.args.ocr_warmup):
                    self.recognize(warmup_image)

        elapsed = time.perf_counter() - load_started
        self.stats.update(model_ready=True, load_seconds=elapsed)
        self.runtime.model_ready.set()

    def run(self) -> None:
        try:
            self.load()
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self.stats.update(error=message)
            self.runtime.model_failed.set()
            self.runtime.model_ready.set()
            self._put_result({"type": "fatal", "error": message})
            return

        version = 0
        while not self.runtime.stop_requested.is_set():
            if not self.runtime.recognition_enabled.wait(timeout=0.1):
                continue
            version, packet = self.frames.get(version, timeout=0.2)
            if packet is None:
                continue
            try:
                if not self.runtime.recognition_enabled.is_set():
                    continue
                started = time.perf_counter()
                plates, ocr_events, timings, vehicle_count = self.process(packet)
                total_seconds = time.perf_counter() - started
                timings["total_ms"] = total_seconds * 1000.0
                self.stats.add_processed(len(plates), total_seconds, timings, packet.frame_idx)
                self._put_result(
                    {
                        "type": "frame_result",
                        "frame": packet.frame_idx,
                        "captured_at": packet.captured_at,
                        "completed_at": time.perf_counter(),
                        "vehicles": vehicle_count,
                        "plates": plates,
                        "ocr_events": ocr_events,
                        "ocr_calls": int(timings.get("ocr_calls", 0.0)),
                        "timings_ms": {
                            key: round(value, 3)
                            for key, value in timings.items()
                            if key.endswith("_ms")
                        },
                    }
                )
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                self.stats.add_failure(message, packet.frame_idx)
                self._put_result(
                    {"type": "frame_error", "frame": packet.frame_idx, "error": message}
                )
            finally:
                self.frames.task_done()

    def process(
        self, packet: FramePacket
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, float], int]:
        if self.args.pipeline == "direct":
            return self._process_direct(packet)
        return self._process_vehicle_pipeline(packet)

    def _process_direct(
        self, packet: FramePacket
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, float], int]:
        timings = {"vehicle_ms": 0.0, "plate_ms": 0.0, "ocr_ms": 0.0, "ocr_calls": 0.0}
        if self.recognize is None:
            return [], [], timings, 0
        started = time.perf_counter()
        text, confidence = self.recognize(packet.frame)
        ocr_ms = (time.perf_counter() - started) * 1000.0
        timings["ocr_ms"] = ocr_ms
        timings["ocr_calls"] = 1.0
        result = self._make_plate_result(
            text=text,
            confidence=confidence,
            ocr_ms=ocr_ms,
            source="full_frame",
            vehicle_box=None,
            plate_corners=None,
            track_id=None,
            frame_idx=packet.frame_idx,
        )
        return ([result] if result is not None else []), [], timings, 0

    def _process_vehicle_pipeline(
        self, packet: FramePacket
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, float], int]:
        if self.vehicle_model is None:
            raise RuntimeError("vehicle model is not loaded")

        frame = packet.frame
        frame_h, frame_w = frame.shape[:2]
        timings = {"vehicle_ms": 0.0, "plate_ms": 0.0, "ocr_ms": 0.0, "ocr_calls": 0.0}

        vehicle_started = time.perf_counter()
        vehicle_results = self.vehicle_model(
            frame,
            imgsz=self.args.vehicle_imgsz,
            classes=VEHICLE_CLASSES,
            conf=self.args.vehicle_conf,
            verbose=False,
        )
        timings["vehicle_ms"] = (time.perf_counter() - vehicle_started) * 1000.0
        boxes_obj = vehicle_results[0].boxes
        if boxes_obj is None or len(boxes_obj) == 0:
            return [], [], timings, 0

        boxes = boxes_obj.xyxy.cpu().numpy().astype(int)
        confidences = (
            boxes_obj.conf.cpu().numpy().astype(float)
            if boxes_obj.conf is not None
            else np.ones(len(boxes), dtype=np.float32)
        )
        if self.tracker is not None:
            detections = self.tracker.update(boxes, confidences, packet.frame_idx)
        else:
            detections = [
                (None, box.astype(np.float32), float(confidence))
                for box, confidence in zip(boxes, confidences)
            ]

        detections.sort(
            key=lambda item: float(item[2]) * max(1.0, float((item[1][2] - item[1][0]) * (item[1][3] - item[1][1]))),
            reverse=True,
        )
        detections = detections[: self.args.max_vehicles_per_frame]

        emitted: list[dict[str, Any]] = []
        ocr_events: list[dict[str, Any]] = []
        for track_id, box_array, vehicle_confidence in detections:
            if track_id is not None:
                existing_state = self.track_states.get(int(track_id))
                if existing_state is not None and existing_state.locked_text:
                    continue
            x1, y1, x2, y2 = [int(value) for value in box_array.tolist()]
            vehicle_box = [x1, y1, x2, y2]
            ready, _reason = vehicle_ready_for_plate(
                vehicle_box, vehicle_confidence, frame.shape, self.args
            )
            if not ready:
                continue
            vehicle_crop = safe_crop(frame, vehicle_box)
            if vehicle_crop.size == 0:
                continue

            best_result: dict[str, Any] | None = None
            if self.recognize is not None and self.use_vehicle_first:
                ocr_started = time.perf_counter()
                text, confidence = self.recognize(vehicle_crop)
                ocr_ms = (time.perf_counter() - ocr_started) * 1000.0
                timings["ocr_ms"] += ocr_ms
                timings["ocr_calls"] += 1.0
                best_result = self._make_plate_result(
                    text=text,
                    confidence=confidence,
                    ocr_ms=ocr_ms,
                    source="vehicle_crop",
                    vehicle_box=vehicle_box,
                    plate_corners=None,
                    track_id=track_id,
                    frame_idx=packet.frame_idx,
                )

            should_run_plate = self.plate_model is not None and (
                self.args.plate_stage == "always"
                or (self.args.plate_stage == "fallback" and best_result is None)
            )
            if should_run_plate:
                cx1 = max(0, x1 - ROI_MARGIN)
                cy1 = max(0, y1 - ROI_MARGIN)
                cx2 = min(frame_w, x2 + ROI_MARGIN)
                cy2 = min(frame_h, y2 + ROI_MARGIN)
                roi = frame[cy1:cy2, cx1:cx2]
                if roi.size != 0:
                    plate_started = time.perf_counter()
                    plate_results = self.plate_model(
                        roi,
                        imgsz=self.args.plate_imgsz,
                        conf=self.args.plate_conf,
                        verbose=False,
                    )
                    timings["plate_ms"] += (time.perf_counter() - plate_started) * 1000.0
                    obb = plate_results[0].obb
                    if obb is not None and len(obb) > 0:
                        limit = min(len(obb), self.args.max_plates_per_vehicle)
                        for index in range(limit):
                            candidate = obb[index]
                            local_corners = candidate.xyxyxyxy[0].cpu().numpy().astype(np.float32)
                            corners = local_corners + np.array([[cx1, cy1]], dtype=np.float32)
                            plate_crop = warp_plate(frame, corners)
                            if plate_crop.size == 0:
                                continue
                            obb_confidence = get_obb_confidence(candidate)
                            area = polygon_area(corners)
                            geometry = plate_geometry(corners)
                            geometry["vehicle_overlap"] = plate_box_overlap_ratio(corners, vehicle_box)
                            keep, _reason = passes_plate_filter(
                                geometry,
                                area,
                                obb_confidence,
                                vehicle_box,
                                corners,
                                self.args,
                            )
                            if not keep or self.recognize is None:
                                continue
                            text, confidence, ocr_event = perform_ocr_call(
                                ocr=self.ocr,
                                recognize=self.recognize,
                                image=plate_crop,
                                frame_idx=packet.frame_idx,
                                track_id=int(track_id) if track_id is not None else -1,
                                engine=self.args.ocr_engine,
                                source="plate",
                                is_plate_like=self.is_plate_like,
                                min_ocr_conf=self.args.min_ocr_conf,
                            )
                            ocr_ms = float(ocr_event["ocr_ms"])
                            timings["ocr_ms"] += ocr_ms
                            timings["ocr_calls"] += 1.0
                            ocr_event["vehicle_box"] = vehicle_box
                            ocr_event["plate_corners"] = corners.tolist()
                            if track_id is None:
                                ocr_event["vote_reason"] = ocr_event["vote_reason"] or "tracking_disabled"
                            else:
                                state = self.track_states.setdefault(int(track_id), TrackState())
                                locked_now = apply_event_vote(
                                    ocr_event,
                                    state,
                                    self.args,
                                    vehicle_conf=vehicle_confidence,
                                    obb_conf=obb_confidence,
                                )
                                if locked_now:
                                    ocr_event["locked_text"] = state.locked_text
                            ocr_events.append(ocr_event)
                            plate_result = self._make_plate_result(
                                text=text,
                                confidence=confidence,
                                ocr_ms=ocr_ms,
                                source="plate_crop",
                                vehicle_box=vehicle_box,
                                plate_corners=corners.tolist(),
                                track_id=track_id,
                                frame_idx=packet.frame_idx,
                            )
                            if self._is_better_result(plate_result, best_result):
                                best_result = plate_result

            if best_result is not None:
                emitted.append(best_result)

        return emitted, ocr_events, timings, len(detections)

    def _make_plate_result(
        self,
        text: str | None,
        confidence: float | None,
        ocr_ms: float,
        source: str,
        vehicle_box: list[int] | None,
        plate_corners: list[list[float]] | None,
        track_id: int | None,
        frame_idx: int,
    ) -> dict[str, Any] | None:
        if not text:
            return None
        if self.is_plate_like is not None and not self.is_plate_like(text):
            return None
        numeric_confidence = float(confidence) if confidence is not None else 0.0
        if numeric_confidence < self.args.min_ocr_conf:
            return None

        return {
            "text": text,
            "confidence": round(numeric_confidence, 4),
            "ocr_engine": self.args.ocr_engine,
            "ocr_ms": round(float(ocr_ms), 3),
            "source": source,
            "frame": frame_idx,
            "track_id": int(track_id) if track_id is not None else None,
            "vehicle_box": vehicle_box,
            "plate_corners": plate_corners,
        }

    @staticmethod
    def _is_better_result(
        candidate: dict[str, Any] | None, current: dict[str, Any] | None
    ) -> bool:
        if candidate is None:
            return False
        if current is None:
            return True
        return float(candidate["confidence"]) > float(current["confidence"])

    def _put_result(self, item: dict[str, Any]) -> None:
        try:
            self.results.put_nowait(item)
        except queue.Full:
            try:
                self.results.get_nowait()
            except queue.Empty:
                pass
            try:
                self.results.put_nowait(item)
            except queue.Full:
                pass


def set_recognition_state(runtime: RuntimeState, enabled: bool, reason: str) -> None:
    old_state = runtime.recognition_enabled.is_set()
    if enabled:
        runtime.recognition_enabled.set()
    else:
        runtime.recognition_enabled.clear()
    if old_state != enabled:
        print(f"[CONTROL] recognition={'ON' if enabled else 'OFF'} reason={reason}", flush=True)


def parse_video_source(value: str) -> str | int:
    return int(value) if value.isdigit() else value


def drain_results(
    results: queue.Queue[dict[str, Any]],
    jsonl_file: Any,
) -> tuple[int, dict[str, Any] | None]:
    drained = 0
    latest_accepted: dict[str, Any] | None = None
    while True:
        try:
            item = results.get_nowait()
        except queue.Empty:
            break
        drained += 1
        if item.get("type") == "frame_result":
            timings = item.get("timings_ms", {})
            end_to_end_ms = max(
                0.0,
                (float(item.get("completed_at", 0.0)) - float(item.get("captured_at", 0.0)))
                * 1000.0,
            )
            for ocr_event in item.get("ocr_events", []):
                event = {
                    "timestamp": datetime.now().isoformat(timespec="milliseconds"),
                    **ocr_event,
                    "recognition_total_ms": round(float(timings.get("total_ms", 0.0)), 3),
                    "end_to_end_ms": round(end_to_end_ms, 3),
                    "timings_ms": timings,
                }
                line = json.dumps(event, ensure_ascii=False)
                print(
                    f"[OCR_SPEED] engine={event.get('ocr_engine')} text={event.get('text')} "
                    f"conf={float(event.get('confidence') or 0.0):.4f} "
                    f"ocr_ms={float(event.get('ocr_ms', 0.0)):.1f} "
                    f"accepted={bool(event.get('accepted_for_vote'))} "
                    f"reason={event.get('vote_reason')} "
                    f"frame={event.get('frame_idx')} track_id={event.get('track_id')}",
                    flush=True,
                )
                if jsonl_file is not None:
                    jsonl_file.write(line + "\n")
                    jsonl_file.flush()
                if event.get("accepted_for_vote"):
                    latest_accepted = event
        elif item.get("type") in {"frame_error", "fatal"}:
            print(f"[ERROR] {json.dumps(item, ensure_ascii=False)}", flush=True)
    return drained, latest_accepted


def update_from_control_file(
    path: Path | None,
    runtime: RuntimeState,
    last_mtime_ns: int | None,
) -> int | None:
    if path is None or not path.exists():
        return last_mtime_ns
    try:
        stat = path.stat()
        if stat.st_mtime_ns == last_mtime_ns:
            return last_mtime_ns
        command = path.read_text(encoding="utf-8").strip().lower()
    except OSError as exc:
        print(f"[CONTROL] cannot read {path}: {exc}", flush=True)
        return last_mtime_ns

    if command in {"on", "start", "1"}:
        set_recognition_state(runtime, True, f"file:{path}")
    elif command in {"off", "pause", "0"}:
        set_recognition_state(runtime, False, f"file:{path}")
    elif command in {"quit", "stop", "exit"}:
        print(f"[CONTROL] quit requested by {path}", flush=True)
        runtime.stop_requested.set()
    else:
        print(f"[CONTROL] ignored unsupported command {command!r} in {path}", flush=True)
    return stat.st_mtime_ns


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Keep raw video playback independent from ALPR inference. "
            "The recognition worker consumes only the newest frame and prints JSON results."
        )
    )
    parser.add_argument("--video", default=DEFAULT_VIDEO, help="Video path or numeric camera index.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Base directory for JSONL and summary output.")
    parser.add_argument("--vehicle-model", default=DEFAULT_VEHICLE_MODEL)
    parser.add_argument("--plate-model", default=DEFAULT_PLATE_MODEL)
    parser.add_argument("--pipeline", choices=["vehicle", "direct"], default="vehicle")
    parser.add_argument(
        "--plate-stage",
        choices=["off", "fallback", "always"],
        default="fallback",
        help="off skips plate OBB; fallback uses it only after vehicle-crop OCR fails; always runs it.",
    )
    parser.add_argument(
        "--ocr-engine",
        choices=["none", "plate-rec", "plate-rec-ort", "plate-rec-cv2", "hyperlpr3", "hyperlpr3-rec", "paddle"],
        default="hyperlpr3-rec",
    )
    parser.add_argument("--tracking", choices=["none", "iou"], default="iou")
    parser.add_argument("--track-iou", type=float, default=0.2)
    parser.add_argument("--track-max-age", type=int, default=120)
    parser.add_argument("--vehicle-conf", type=float, default=0.55)
    parser.add_argument("--plate-conf", type=float, default=0.25)
    parser.add_argument("--vehicle-imgsz", type=int, default=640)
    parser.add_argument("--plate-imgsz", type=int, default=320)
    parser.add_argument("--max-vehicles-per-frame", type=int, default=3)
    parser.add_argument("--max-plates-per-vehicle", type=int, default=1)
    parser.add_argument(
        "--min-ocr-conf",
        type=float,
        default=0.5,
        help="Minimum OCR confidence accepted as a result (default: 0.50).",
    )
    parser.add_argument("--torch-threads", type=int, default=4, help="Reserve CPU headroom for video playback.")
    parser.add_argument("--ocr-warmup", type=int, default=20, help="Unmeasured pure OCR warm-up calls.")
    parser.add_argument("--vote-window", type=int, default=10)
    parser.add_argument("--vote-threshold", type=int, default=3)
    parser.add_argument("--min-char-vote-ratio", type=float, default=0.65)
    parser.add_argument("--min-lock-text-len", type=int, default=7)
    parser.add_argument(
        "--recognition-initial-state",
        choices=["on", "off"],
        default="on",
        help="With a window, press R at any time to toggle recognition.",
    )
    parser.add_argument("--recognition-start-frame", type=int, default=0)
    parser.add_argument("--recognition-stop-frame", type=int, default=0)
    parser.add_argument(
        "--control-file",
        default="",
        help="Optional text file containing on/off/quit for external control.",
    )
    parser.add_argument(
        "--show-video",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Show source video with a lightweight FPS/status HUD. Q/Esc quits and R toggles recognition.",
    )
    parser.add_argument("--display-width", type=int, default=1280)
    parser.add_argument("--display-height", type=int, default=720)
    parser.add_argument(
        "--playback-fps",
        type=float,
        default=0.0,
        help="0 uses source FPS. For a file, forcing a different value changes playback speed.",
    )
    parser.add_argument(
        "--pace-playback",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Pace file playback in real time; disable for throughput benchmarks.",
    )
    parser.add_argument("--progress-interval-seconds", type=float, default=1.0)
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument(
        "--shutdown-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for the in-flight recognition call when exiting.",
    )
    parser.add_argument(
        "--save-results",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Save every OCR call, including rejected results, as JSONL; no images are saved.",
    )

    parser.add_argument("--min-process-vehicle-conf", type=float, default=0.65)
    parser.add_argument("--min-process-vehicle-width", type=int, default=90)
    parser.add_argument("--min-process-vehicle-height", type=int, default=70)
    parser.add_argument("--min-process-vehicle-area", type=int, default=8000)
    parser.add_argument("--min-process-vehicle-area-ratio", type=float, default=0.003)
    parser.add_argument("--min-plate-obb-conf", type=float, default=0.5)
    parser.add_argument("--min-plate-area", type=float, default=250.0)
    parser.add_argument("--max-plate-area", type=float, default=8000.0)
    parser.add_argument("--max-plate-vehicle-area-ratio", type=float, default=0.04)
    parser.add_argument("--min-plate-aspect", type=float, default=2.0)
    parser.add_argument("--max-plate-aspect", type=float, default=6.0)
    parser.add_argument(
        "--require-plate-in-vehicle", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--vehicle-box-pad-ratio", type=float, default=0.2)
    parser.add_argument("--vehicle-box-min-pad", type=float, default=20.0)
    parser.add_argument("--min-plate-vehicle-overlap", type=float, default=0.5)
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.ocr_engine != "hyperlpr3-rec":
        raise ValueError("This real-time mode is recognition-only and requires --ocr-engine hyperlpr3-rec")
    if args.pipeline != "vehicle":
        raise ValueError("HyperLPR3 recognition-only requires --pipeline vehicle for plate localization")
    if args.plate_stage == "off":
        raise ValueError("HyperLPR3 recognition-only requires plate OBB; --plate-stage off is invalid")
    if args.tracking != "iou":
        raise ValueError("Recognition-only voting requires --tracking iou")
    if args.pipeline == "direct" and args.ocr_engine == "none":
        raise ValueError("--pipeline direct requires a real OCR engine")
    if args.pipeline == "direct" and args.ocr_engine != "hyperlpr3":
        raise ValueError("--pipeline direct currently requires --ocr-engine hyperlpr3")
    if (
        args.pipeline == "vehicle"
        and args.plate_stage == "off"
        and args.ocr_engine not in {"none", "hyperlpr3"}
    ):
        raise ValueError(
            "--plate-stage off requires HyperLPR3 vehicle-crop OCR; "
            "other OCR engines need a plate crop"
        )
    if args.max_vehicles_per_frame <= 0:
        raise ValueError("--max-vehicles-per-frame must be positive")
    if args.max_plates_per_vehicle <= 0:
        raise ValueError("--max-plates-per-vehicle must be positive")
    if args.progress_interval_seconds <= 0:
        raise ValueError("--progress-interval-seconds must be positive")
    if args.ocr_warmup < 0:
        raise ValueError("--ocr-warmup must be >= 0")
    if args.shutdown_timeout <= 0:
        raise ValueError("--shutdown-timeout must be positive")
    if args.vote_window <= 0:
        raise ValueError("--vote-window must be positive")
    if args.vote_threshold <= 0 or args.vote_threshold > args.vote_window:
        raise ValueError("--vote-threshold must be between 1 and --vote-window")
    if not 0.0 <= args.min_char_vote_ratio <= 1.0:
        raise ValueError("--min-char-vote-ratio must be between 0 and 1")
    if args.min_lock_text_len <= 0:
        raise ValueError("--min-lock-text-len must be positive")


def main() -> None:
    args = build_parser().parse_args()
    validate_args(args)

    source = parse_video_source(args.video)
    is_camera = isinstance(source, int)
    if not is_camera and not Path(str(source)).exists():
        raise FileNotFoundError(f"Video not found: {source}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(args.output) / f"run_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    jsonl_path = run_dir / "recognition_results.jsonl"
    summary_path = run_dir / "summary.json"
    jsonl_file = jsonl_path.open("a", encoding="utf-8", buffering=1) if args.save_results else None

    runtime = RuntimeState()
    if args.recognition_initial_state == "on":
        runtime.recognition_enabled.set()
    frames = LatestFrameBuffer()
    results: queue.Queue[dict[str, Any]] = queue.Queue()
    worker_stats = SharedWorkerStats()
    recognizer = AsyncRecognizer(args, frames, results, runtime, worker_stats)
    worker = threading.Thread(target=recognizer.run, name="alpr-recognition", daemon=True)

    print("Loading recognition models in the background...", flush=True)
    worker.start()
    latest_accepted: dict[str, Any] | None = None
    while not runtime.model_ready.wait(timeout=0.2):
        _drained, accepted = drain_results(results, jsonl_file)
        latest_accepted = accepted or latest_accepted
    _drained, accepted = drain_results(results, jsonl_file)
    latest_accepted = accepted or latest_accepted
    if runtime.model_failed.is_set():
        if jsonl_file is not None:
            jsonl_file.close()
        raise RuntimeError(worker_stats.snapshot().get("error") or "recognition model load failed")
    print(
        f"Models ready in {worker_stats.snapshot()['load_seconds']:.2f}s | "
        f"recognition={'ON' if runtime.recognition_enabled.is_set() else 'OFF'}",
        flush=True,
    )

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        runtime.stop_requested.set()
        frames.close()
        raise RuntimeError(f"Could not open video source: {source}")

    source_fps = float(cap.get(cv2.CAP_PROP_FPS))
    if source_fps <= 0:
        source_fps = 30.0
    playback_fps = args.playback_fps if args.playback_fps > 0 else source_fps
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(
        f"Video: {width}x{height} source_fps={source_fps:.3f} frames={frame_count} | "
        f"playback_target={playback_fps:.3f} FPS",
        flush=True,
    )
    if not is_camera and abs(playback_fps - source_fps) > 0.01:
        print(
            "[WARNING] playback FPS differs from source FPS; file playback speed will change. "
            "This does not create new unique frames.",
            flush=True,
        )

    window_name = "ALPR Raw Video (R: recognition on/off, Q/Esc: quit)"
    if args.show_video:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(window_name, args.display_width, args.display_height)

    control_path = Path(args.control_file).resolve() if args.control_file else None
    control_mtime: int | None = None
    if control_path is not None:
        if not control_path.exists():
            control_path.parent.mkdir(parents=True, exist_ok=True)
            control_path.write_text(
                "on" if runtime.recognition_enabled.is_set() else "off", encoding="utf-8"
            )
        print(f"Control file: {control_path} (on/off/quit)", flush=True)

    frame_idx = 0
    playback_started = time.perf_counter()
    report_started = playback_started
    report_frame_idx = 0
    playback_rate = 0.0
    playback_timestamps: deque[float] = deque(maxlen=30)
    last_control_check = 0.0
    natural_eof = False
    playback_ended = playback_started

    try:
        while not runtime.stop_requested.is_set():
            ok, frame = cap.read()
            if not ok:
                natural_eof = True
                break
            frame_idx += 1
            captured_at = time.perf_counter()
            playback_timestamps.append(captured_at)
            if len(playback_timestamps) >= 2:
                window_elapsed = playback_timestamps[-1] - playback_timestamps[0]
                if window_elapsed > 0:
                    playback_rate = (len(playback_timestamps) - 1) / window_elapsed

            if args.recognition_start_frame > 0 and frame_idx == args.recognition_start_frame:
                set_recognition_state(runtime, True, f"start_frame:{frame_idx}")
            if args.recognition_stop_frame > 0 and frame_idx == args.recognition_stop_frame:
                set_recognition_state(runtime, False, f"stop_frame:{frame_idx}")

            if runtime.recognition_enabled.is_set():
                frames.publish(FramePacket(frame_idx=frame_idx, captured_at=captured_at, frame=frame))

            now = time.perf_counter()
            if control_path is not None and now - last_control_check >= 0.25:
                control_mtime = update_from_control_file(
                    control_path, runtime, control_mtime
                )
                last_control_check = now

            _drained, accepted = drain_results(results, jsonl_file)
            latest_accepted = accepted or latest_accepted

            if now - report_started >= args.progress_interval_seconds:
                elapsed = now - report_started
                playback_rate = (frame_idx - report_frame_idx) / elapsed
                snapshot = worker_stats.snapshot()
                print(
                    f"[PERF] video_fps={playback_rate:.2f} frame={frame_idx} "
                    f"recognition={'ON' if runtime.recognition_enabled.is_set() else 'OFF'} "
                    f"infer_fps={snapshot['processed_fps']:.2f} infer_ms={snapshot['last_total_ms']:.1f} "
                    f"ocr_frame_ms={snapshot['last_ocr_ms']:.1f} "
                    f"ocr_avg_ms={snapshot['average_ocr_ms']:.1f} "
                    f"submitted={frames.published} replaced={frames.overwritten}",
                    flush=True,
                )
                report_started = now
                report_frame_idx = frame_idx

            if args.show_video:
                display_frame = frame.copy()
                snapshot = worker_stats.snapshot()
                draw_realtime_hud(
                    display_frame,
                    playback_rate if playback_rate > 0 else None,
                    source_fps,
                    frame_idx,
                    int(snapshot["ocr_calls"]),
                    metric_label="ocr_calls",
                )
                cv2.putText(
                    display_frame,
                    (
                        f"REC {'ON' if runtime.recognition_enabled.is_set() else 'OFF'} "
                        f"INFER {float(snapshot['processed_fps']):.1f} FPS "
                        f"DROP {frames.overwritten}"
                    ),
                    (20, 116),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 255),
                    2,
                    cv2.LINE_AA,
                )
                if latest_accepted is not None:
                    cv2.putText(
                        display_frame,
                        (
                            f"TRACK {latest_accepted.get('track_id')} "
                            f"CONF {float(latest_accepted.get('confidence') or 0.0):.2f}"
                        ),
                        (20, 152),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.75,
                        (0, 255, 255),
                        2,
                        cv2.LINE_AA,
                    )
                shown = cv2.resize(
                    display_frame,
                    (args.display_width, args.display_height),
                    interpolation=cv2.INTER_AREA,
                )
                cv2.imshow(window_name, shown)

            if args.max_frames > 0 and frame_idx >= args.max_frames:
                break

            wait_ms = 1
            if args.pace_playback and not is_camera:
                deadline = playback_started + frame_idx / playback_fps
                remaining = deadline - time.perf_counter()
                wait_ms = max(1, int(round(remaining * 1000.0))) if remaining > 0 else 1

            if args.show_video:
                key = cv2.waitKey(wait_ms) & 0xFF
                if key in (ord("q"), 27):
                    runtime.stop_requested.set()
                elif key in (ord("r"), ord("R")):
                    set_recognition_state(
                        runtime,
                        not runtime.recognition_enabled.is_set(),
                        "keyboard:R",
                    )
            elif wait_ms > 1:
                time.sleep(wait_ms / 1000.0)
    except KeyboardInterrupt:
        print("Ctrl+C received; stopping...", flush=True)
    finally:
        playback_ended = time.perf_counter()
        cap.release()
        if args.show_video:
            cv2.destroyWindow(window_name)
        frames.wait_idle(args.shutdown_timeout)
        runtime.stop_requested.set()
        frames.close()
        worker.join(timeout=args.shutdown_timeout)
        if worker.is_alive():
            print(
                f"[WARNING] recognition worker did not stop within {args.shutdown_timeout:.1f}s",
                flush=True,
            )
        _drained, accepted = drain_results(results, jsonl_file)
        latest_accepted = accepted or latest_accepted
        if jsonl_file is not None:
            jsonl_file.close()

    elapsed = max(1e-9, playback_ended - playback_started)
    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "video": {
            "source": str(source),
            "width": width,
            "height": height,
            "source_fps": source_fps,
            "frame_count": frame_count,
            "frames_read": frame_idx,
            "natural_eof": natural_eof,
        },
        "runtime": {
            "elapsed_seconds": round(elapsed, 3),
            "video_loop_fps": round(frame_idx / elapsed, 3),
            "frames_submitted": frames.published,
            "frames_replaced_before_inference": frames.overwritten,
        },
        "recognition": worker_stats.snapshot(),
        "locks": recognizer.locked_tracks(),
        "config": vars(args),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved async run: {run_dir}", flush=True)
    print(json.dumps(summary["runtime"] | summary["recognition"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
