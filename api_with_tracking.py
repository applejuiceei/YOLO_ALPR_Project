import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import time
import os
import re
from ultralytics import YOLO
from paddleocr import PaddleOCR


# ==========================================
# 1. 核心工业组件与工具函数
# ==========================================

class ALPRVoter:
    """车牌多帧投票器（3票共识机制）"""

    def __init__(self, max_history=10, consensus_threshold=3):
        self.history = {}
        self.max_history = max_history
        self.consensus_threshold = consensus_threshold

    def add_record(self, track_id):
        if track_id not in self.history:
            self.history[track_id] = []

    def vote(self, track_id, text, conf):
        if not text: return False, ""
        self.add_record(track_id)
        self.history[track_id].append(text)

        if len(self.history[track_id]) > self.max_history:
            self.history[track_id].pop(0)

        counts = {}
        for t in self.history[track_id]:
            counts[t] = counts.get(t, 0) + 1

        best_text = max(counts, key=counts.get)
        if counts[best_text] >= self.consensus_threshold:
            return True, best_text
        return False, ""


def clean_and_validate_plate(ocr_text):
    """
    工业级规则引擎：清洗并校验中国大陆车牌号
    """
    clean_text = re.sub(r'[^A-Z0-9\u4e00-\u9fa5]', '', ocr_text.upper())
    # 严格匹配中国车牌规范
    pattern = r"^[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领][A-Z][A-HJ-NP-Z0-9]{4,5}[A-HJ-NP-Z0-9挂学警港澳]$"

    if re.match(pattern, clean_text):
        return True, clean_text
    else:
        return False, clean_text


def cv2_add_chinese_text(img, text, position, textColor=(0, 255, 0), textSize=30):
    """OpenCV 绘制中文"""
    if isinstance(img, np.ndarray):
        img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img)
    try:
        # 请确保根目录有 simhei.ttf，或替换为你系统的绝对路径如 r"C:\Windows\Fonts\msyh.ttc"
        fontStyle = ImageFont.truetype("simhei.ttf", textSize, encoding="utf-8")
    except IOError:
        fontStyle = ImageFont.load_default()
    draw.text(position, text, textColor, font=fontStyle)
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


def order_points(pts):
    """四点排序：左上, 右上, 右下, 左下"""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def expand_rect(rect, pad_x=5, pad_y=5):
    """边缘外扩保护（深拷贝防止内存污染）"""
    new_rect = rect.copy()
    new_rect[0] = [new_rect[0][0] - pad_x, new_rect[0][1] - pad_y]
    new_rect[1] = [new_rect[1][0] + pad_x, new_rect[1][1] - pad_y]
    new_rect[2] = [new_rect[2][0] + pad_x, new_rect[2][1] + pad_y]
    new_rect[3] = [new_rect[3][0] - pad_x, new_rect[3][1] + pad_y]
    return new_rect


# ==========================================
# 2. 核心视频流与管线引擎
# ==========================================

def run_ultimate_alpr_engine(video_path):
    print("====== 🚀 启动终极工业级 ALPR 引擎 (SAHI + Regex + Snapshot) ======")

    # 1. 初始化抓拍目录
    snapshot_dir = r"D:\YOLO_ALPR_Project\captures"
    if not os.path.exists(snapshot_dir):
        os.makedirs(snapshot_dir)
        print(f"📁 抓拍证据链目录已就绪: {snapshot_dir}")

    # 2. 挂载 AI 模型
    vehicle_model = YOLO(r"D:\renlian\ultralytics-8.3.34\yolo11n.pt")
    plate_model = YOLO(r"D:\YOLO_ALPR_Project\best_obb.pt")
    ocr = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False)

    # 3. 初始化状态控制器
    voter = ALPRVoter(consensus_threshold=3)
    vehicle_states = {}

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("❌ 视频加载失败")
        return

    # UI 窗口设置
    WINDOW_NAME = "Ultimate ALPR Engine"
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 1280, 720)  # 强行撑开大屏显示

    ROI_MARGIN = 50

    try:
        while cap.isOpened():
            start_time = time.time()
            ret, frame = cap.read()
            if not ret: break

            # 防护：点红叉安全退出
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break

            orig_h, orig_w = frame.shape[:2]
            # 存底一张最干净的原始 4K 帧，用于后期生成抓拍证据图
            raw_clean_frame = frame.copy()

            # ====== 阶段一：全局低清寻车 (imgsz=640 榨干算力) ======
            v_results = vehicle_model.track(frame, imgsz=640, persist=True, classes=[2, 3, 5, 7], verbose=False)

            if v_results[0].boxes is not None and v_results[0].boxes.id is not None:
                boxes = v_results[0].boxes.xyxy.cpu().numpy().astype(int)
                track_ids = v_results[0].boxes.id.cpu().numpy().astype(int)

                for box, track_id in zip(boxes, track_ids):
                    vx1, vy1, vx2, vy2 = box

                    # 初始化追踪车辆的状态机
                    if track_id not in vehicle_states:
                        vehicle_states[track_id] = {"has_final_result": False, "final_text": "", "was_snapshot": False}
                    state = vehicle_states[track_id]

                    # 绘制检测框和 ID
                    cv2.rectangle(frame, (vx1, vy1), (vx2, vy2), (255, 0, 0), 2)
                    cv2.putText(frame, f"ID: {track_id}", (vx1, vy1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0),
                                2)

                    # 🛡️ 状态机拦截：出结果的直接挂字，跳过后面所有计算
                    if state["has_final_result"]:
                        frame = cv2_add_chinese_text(frame, state["final_text"], (vx1, vy1 - 45), textColor=(0, 255, 0),
                                                     textSize=35)
                        continue

                    # ====== 阶段二：原生 4K ROI 无损切片 (SAHI) ======
                    cx1 = max(0, vx1 - ROI_MARGIN)
                    cy1 = max(0, vy1 - ROI_MARGIN)
                    cx2 = min(orig_w, vx2 + ROI_MARGIN)
                    cy2 = min(orig_h, vy2 + ROI_MARGIN)

                    roi_crop = frame[cy1:cy2, cx1:cx2].copy()
                    if roi_crop.size == 0: continue

                    # ====== 阶段三：高清切片下的 OBB 与透视拉平 ======
                    p_results = plate_model(roi_crop, imgsz=320, verbose=False)

                    if len(p_results[0].obb) > 0:
                        best_obb = p_results[0].obb[0]
                        pts_local = best_obb.xyxyxyxy[0].cpu().numpy().astype(int)

                        # 还原坐标并透视变换
                        pts_global = pts_local + np.array([cx1, cy1])
                        rect_global = order_points(pts_global)
                        exp_rect = expand_rect(rect_global, pad_x=5, pad_y=5)

                        # 在当前帧上画出车牌绿框
                        cv2.polylines(frame, [exp_rect.astype(int)], True, (0, 255, 0), 2)

                        width, height = 320, 96
                        dst_pts = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
                                           dtype="float32")
                        M = cv2.getPerspectiveTransform(exp_rect.astype("float32"), dst_pts)
                        flattened_plate = cv2.warpPerspective(raw_clean_frame, M, (width, height))

                        # ====== 阶段四：OCR 识别 与 规则引擎过滤 ======
                        ocr_result = ocr.ocr(flattened_plate, cls=False)

                        if ocr_result and ocr_result[0]:
                            raw_text_str = ocr_result[0][0][1][0]
                            conf = ocr_result[0][0][1][1]

                            # 🚨 核心：送入中国车牌规则引擎安检
                            is_valid, clean_text_str = clean_and_validate_plate(raw_text_str)

                            if not is_valid:
                                # 乱码打回，绝不污染投票器
                                frame = cv2_add_chinese_text(frame, f"拒收乱码:{raw_text_str}", (vx1, vy1 - 35),
                                                             textColor=(128, 128, 128), textSize=20)
                                continue

                                # ====== 阶段五：三票共识与瞬间抓拍 ======
                            is_stable, final_result = voter.vote(track_id, clean_text_str, conf)

                            if is_stable:
                                state["has_final_result"] = True
                                state["final_text"] = final_result
                                print(f"✅ [ID {track_id}] 合法车牌锁定入库: {final_result}")

                                # 📸 触发交警级证据抓拍
                                if not state["was_snapshot"]:
                                    # 构建带框带字的 4K 证据全景图
                                    capture_img = raw_clean_frame.copy()
                                    cv2.rectangle(capture_img, (vx1, vy1), (vx2, vy2), (255, 0, 0), 4)
                                    cv2.polylines(capture_img, [exp_rect.astype(int)], True, (0, 255, 0), 3)
                                    capture_img = cv2_add_chinese_text(capture_img,
                                                                       f"违法车辆识别 | ID:{track_id} | {final_result}",
                                                                       (vx1, vy1 - 60), textColor=(0, 255, 0),
                                                                       textSize=50)

                                    # 保存两张证据图
                                    snap_full = os.path.join(snapshot_dir, f"{track_id}_{final_result}_full.jpg")
                                    snap_plate = os.path.join(snapshot_dir, f"{track_id}_{final_result}_plate.jpg")

                                    cv2.imwrite(snap_full, capture_img)
                                    cv2.imwrite(snap_plate, flattened_plate)
                                    state["was_snapshot"] = True
                                    print(f"📸 抓拍已落盘 -> {snap_full}")
                            else:
                                # 投票等待中
                                frame = cv2_add_chinese_text(frame, f"投票中:{clean_text_str}", (vx1, vy1 - 35),
                                                             textColor=(0, 255, 255), textSize=25)

            # ====== 性能监控与渲染 ======
            fps = 1 / (time.time() - start_time)
            cv2.putText(frame, f"FPS: {fps:.1f}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 3)

            cv2.imshow(WINDOW_NAME, frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("====== 引擎已安全关闭，资源完全释放 ======")


if __name__ == "__main__":
    test_video = r"D:\YOLO_ALPR_Project\测试图\10.mp4"
    run_ultimate_alpr_engine(test_video)