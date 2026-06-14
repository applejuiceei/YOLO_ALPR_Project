import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import re
from ultralytics import YOLO
from paddleocr import PaddleOCR


# --- 辅助函数 ---
# (由于篇幅原因，此文件的 cv2_add_chinese_text、order_points、warp_rect 与上面的代码完全一致，直接沿用)

def order_points(pts):
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def warp_rect(img, pts, width, height):
    pts = order_points(pts)
    dst_pts = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(pts, dst_pts)
    warped = cv2.warpPerspective(img, M, (width, height))
    return warped


# ==========================================
if __name__ == "__main__":
    vehicle_model = YOLO("yolov8n.pt")
    plate_model = YOLO("runs/obb/train4_plate/weights/best.pt")
    ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)

    cap = cv2.VideoCapture("test_video.mp4")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break

        v_results = vehicle_model(frame, classes=[2, 3, 5, 7], verbose=False)

        if v_results[0].boxes is not None:
            for v_box in v_results[0].boxes:
                x1, y1, x2, y2 = map(int, v_box.xyxy[0].cpu().numpy())
                vehicle_roi = frame[max(0, y1):y2, max(0, x1):x2]

                p_results = plate_model(vehicle_roi, verbose=False)

                if hasattr(p_results[0], 'obb') and p_results[0].obb is not None:
                    for obb in p_results[0].obb:
                        local_corners = obb.xyxyxyxy[0].cpu().numpy()
                        global_corners = local_corners + np.array([x1, y1])

                        plate_crop = warp_rect(frame, global_corners, 240, 80)

                        gray = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2GRAY)
                        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                        enhanced = clahe.apply(gray)

                        ocr_res = ocr.ocr(enhanced, cls=False)
                        if ocr_res and ocr_res[0]:
                            raw_text = ocr_res[0][0][1][0]
                            frame = cv2_add_chinese_text(frame, raw_text,
                                                         (int(global_corners[0][0]), int(global_corners[0][1]) - 30))
                            cv2.polylines(frame, [np.int32(global_corners)], True, (0, 0, 255), 2)

        cv2.imshow("Cascade OBB Pipeline", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break