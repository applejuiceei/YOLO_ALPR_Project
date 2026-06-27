from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from rk3588_topk_capture import (
    RKNNRunner,
    build_hyperlpr3,
    decode_obbs,
    decode_vehicle,
    recognize_hyperlpr3,
    warp_plate,
)


def box_to_ints(box: np.ndarray | list[float]) -> list[int]:
    return [int(round(float(value))) for value in box]


def padded_box(box: list[int], shape: tuple[int, int, int], ratio: float = 0.18, minimum: int = 24) -> list[int]:
    h, w = shape[:2]
    x1, y1, x2, y2 = box
    pad_x = max(minimum, int((x2 - x1) * ratio))
    pad_y = max(minimum, int((y2 - y1) * ratio))
    return [max(0, x1 - pad_x), max(0, y1 - pad_y), min(w, x2 + pad_x), min(h, y2 + pad_y)]


def crop(frame: np.ndarray, box: list[int]) -> np.ndarray:
    x1, y1, x2, y2 = box
    return frame[y1:y2, x1:x2].copy() if x2 > x1 and y2 > y1 else np.empty((0, 0, 3), dtype=np.uint8)


def infer_plate_rois(
    frame: np.ndarray,
    plate_model: RKNNRunner,
    catcher: object,
    output_dir: Path,
    rois: list[tuple[str, list[int]]],
    plate_imgsz: int,
    plate_conf: float,
    annotate: np.ndarray,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for roi_name, roi_box in rois:
        roi = crop(frame, roi_box)
        if not roi.size:
            continue
        rgb = cv2.cvtColor(cv2.resize(roi, (plate_imgsz, plate_imgsz)), cv2.COLOR_BGR2RGB)
        obbs = decode_obbs(plate_model.infer_rgb(rgb), roi, (roi_box[0], roi_box[1]), plate_imgsz, plate_conf)
        for index, (corners, score) in enumerate(obbs[:8], start=1):
            plate = warp_plate(frame, corners)
            text, ocr_conf = recognize_hyperlpr3(catcher, plate) if plate.size else ("", 0.0)
            plate_name = f"plate_{roi_name}_{index:02d}_score{score:.2f}_ocr{ocr_conf:.2f}.jpg"
            cv2.imwrite(str(output_dir / plate_name), plate)
            cv2.polylines(annotate, [corners.astype(np.int32)], True, (0, 255, 255), 2)
            cx, cy = corners.mean(axis=0)
            cv2.putText(
                annotate,
                f"{roi_name}:{score:.2f} {text or '-'}",
                (int(cx), max(22, int(cy) - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )
            results.append(
                {
                    "roi": roi_name,
                    "score": float(score),
                    "ocr_text": text,
                    "ocr_conf": float(ocr_conf),
                    "plate_image": plate_name,
                    "corners": corners.round(1).tolist(),
                }
            )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe current /tmp/frame.jpg from the MIPI preview stream.")
    parser.add_argument("--image", default="/tmp/frame.jpg")
    parser.add_argument("--output", default="/root/alpr_topk_rk3588/mipi_current_probe")
    parser.add_argument("--vehicle-model", default="/root/deploy/vehicle.rknn")
    parser.add_argument("--plate-model", default="/root/deploy/best_obb.rknn")
    parser.add_argument("--vehicle-conf", type=float, default=0.15)
    parser.add_argument("--plate-conf", type=float, default=0.20)
    parser.add_argument("--plate-imgsz", type=int, default=640)
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    frame = cv2.imread(args.image)
    if frame is None:
        raise RuntimeError(f"Could not read image: {args.image}")

    cv2.imwrite(str(output_dir / "current_frame.jpg"), frame)
    annotated = frame.copy()
    h, w = frame.shape[:2]
    summary: dict[str, object] = {
        "image": args.image,
        "shape": [h, w, int(frame.shape[2])],
        "vehicle_conf": args.vehicle_conf,
        "plate_conf": args.plate_conf,
    }

    vehicle_model = RKNNRunner(Path(args.vehicle_model), "vehicle")
    plate_model = RKNNRunner(Path(args.plate_model), "plate")
    catcher = build_hyperlpr3()

    try:
        vehicle_rgb = cv2.cvtColor(cv2.resize(frame, (640, 640)), cv2.COLOR_BGR2RGB)
        boxes, confidences = decode_vehicle(vehicle_model.infer_rgb(vehicle_rgb), frame.shape, args.vehicle_conf, 0.45)
        vehicle_results: list[dict[str, object]] = []
        vehicle_rois: list[tuple[str, list[int]]] = []
        for index, (box_array, conf) in enumerate(zip(boxes, confidences), start=1):
            box = box_to_ints(box_array)
            roi_box = padded_box(box, frame.shape)
            vehicle_rois.append((f"vehicle{index}", roi_box))
            vehicle_crop = crop(frame, box)
            vehicle_text, vehicle_ocr_conf = recognize_hyperlpr3(catcher, vehicle_crop) if vehicle_crop.size else ("", 0.0)
            cv2.rectangle(annotated, (box[0], box[1]), (box[2], box[3]), (255, 0, 0), 2)
            cv2.putText(
                annotated,
                f"veh{index}:{float(conf):.2f} {vehicle_text or '-'}",
                (box[0], max(22, box[1] - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 0, 0),
                2,
                cv2.LINE_AA,
            )
            vehicle_results.append(
                {
                    "index": index,
                    "box": box,
                    "confidence": float(conf),
                    "hyperlpr_on_vehicle": {"text": vehicle_text, "confidence": float(vehicle_ocr_conf)},
                }
            )

        summary["vehicles"] = vehicle_results

        scan_rois = [
            ("full", [0, 0, w, h]),
            ("center80", [int(w * 0.10), int(h * 0.08), int(w * 0.90), int(h * 0.95)]),
            ("center60", [int(w * 0.20), int(h * 0.12), int(w * 0.82), int(h * 0.92)]),
            ("lower_center", [int(w * 0.18), int(h * 0.35), int(w * 0.88), int(h * 0.98)]),
        ]
        scan_rois.extend(vehicle_rois)
        summary["plate_candidates"] = infer_plate_rois(
            frame,
            plate_model,
            catcher,
            output_dir,
            scan_rois,
            args.plate_imgsz,
            args.plate_conf,
            annotated,
        )

        cv2.imwrite(str(output_dir / "annotated_probe.jpg"), annotated)
        with (output_dir / "summary.json").open("w", encoding="utf-8") as file:
            json.dump(summary, file, ensure_ascii=False, indent=2)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    finally:
        vehicle_model.close()
        plate_model.close()


if __name__ == "__main__":
    main()
