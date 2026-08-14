import cv2
import numpy as np
import sys
from PIL import Image, ImageDraw, ImageFont
import time
import os
import shutil
from ultralytics import YOLO
from paddleocr import PaddleOCR


# ==========================================
# 1. 核心工具函数与类 (重用投票和画字逻辑)
# ==========================================

def cv2_add_chinese_text(img, text, position, textColor=(0, 255, 0), textSize=30):
    """在 OpenCV 图像上安全绘制中文"""
    if isinstance(img, np.ndarray):
        img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img)
    try:
        # 请确保字体文件 exist，或替换为系统路径
        fontStyle = ImageFont.truetype("simhei.ttf", textSize, encoding="utf-8")
    except IOError:
        fontStyle = ImageFont.load_default()
    draw.text(position, text, textColor, font=fontStyle)
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


def order_points(pts):
    """对四个点进行排序：左上，右上，右下，左下"""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def expand_rect(rect, pad_x=5, pad_y=5):
    """边缘外扩保护（带深拷贝）"""
    new_rect = rect.copy()
    new_rect[0] = [new_rect[0][0] - pad_x, new_rect[0][1] - pad_y]
    new_rect[1] = [new_rect[1][0] + pad_x, new_rect[1][1] - pad_y]
    new_rect[2] = [new_rect[2][0] + pad_x, new_rect[2][1] + pad_y]
    new_rect[3] = [new_rect[3][0] - pad_x, new_rect[3][1] + pad_y]
    return new_rect


def resize_for_display(image, max_width=1280, max_height=720):
    """保持长宽比缩放显示，解决画面拉伸和看不清小窗口问题"""
    h, w = image.shape[:2]
    if w <= max_width and h <= max_height: return image
    scale = min(max_width / w, max_height / h)
    return cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def reset_capture_dir(snapshot_dir):
    """Keep captures limited to the current run."""
    os.makedirs(snapshot_dir, exist_ok=True)
    for entry in os.scandir(snapshot_dir):
        if entry.is_dir(follow_symlinks=False):
            shutil.rmtree(entry.path)
        else:
            os.remove(entry.path)


def is_window_closed(window_name):
    """Return True when the user closes an OpenCV window."""
    try:
        return cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        return True


class ALPRVoter:
    """车牌投票器 (带兜底机制)"""

    def __init__(self, max_history=10, consensus_threshold=2):
        # 方案一：阈值由 3 降为 2，加速锁定
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

    def get_best_guess(self, track_id):
        """方案二：获取历史记录中得票最高的车牌（无视阈值，用于兜底）"""
        if track_id not in self.history or not self.history[track_id]:
            return None, 0

        counts = {}
        for t in self.history[track_id]:
            counts[t] = counts.get(t, 0) + 1

        best_text = max(counts, key=counts.get)
        return best_text, counts[best_text]


# ==========================================
# 2. 主流控制与流水线 (SAHI + ROI + OCR + 兜底抓拍)
# ==========================================

def run_production_sahi_alpr(video_path):
    print("====== 初始化工业级 SAHI + 兜底抓拍视频流水线 ======")

    # 1. 创建保存抓拍图片的目录
    snapshot_dir = r"D:\YOLO_ALPR_Project\captures"
    if not os.path.exists(snapshot_dir):
        os.makedirs(snapshot_dir)
        print(f"✅ 已创建抓拍目录: {snapshot_dir}")

    # 2. 挂载模型 (使用绝对路径)
    reset_capture_dir(snapshot_dir)
    print(f"Captures reset for this run: {snapshot_dir}")

    vehicle_model = YOLO(r"D:\YOLO_ALPR_Project\yolo11n.pt")
    plate_model = YOLO(r"D:\YOLO_ALPR_Project\best_obb.pt")
    # Lazy init: PaddleOCR is the slowest startup component. Load it only after
    # a plate crop is found for the first time.
    ocr = None

    # 3. 初始化控制组件
    voter = ALPRVoter(consensus_threshold=2)
    vehicle_states = {}  # 状态机缓存

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("❌ 视频加载失败")
        return

    # 窗口设置
    main_window = "Full ALPR View (Downscaled)"
    cv2.namedWindow(main_window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(main_window, 1280, 720)

    ROI_MARGIN = 50
    VEHICLE_CLASSES = [2, 5, 7]  # COCO: car, bus, truck. Excludes motorcycle/e-bike.
    VEHICLE_CONF = 0.55

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break

        orig_h, orig_w = frame.shape[:2]

        # 保存一张原始的、没有任何框的 frame 用于抓拍原图
        raw_full_frame = frame.copy()

        # 记录当前帧画面中出现的所有车辆 ID，用于判定车辆是否驶离画面
        current_frame_track_ids = []

        # ==========================================
        # 阶段一：全局低清找车 (imgsz=640)
        # ==========================================
        v_results = vehicle_model.track(
            frame,
            imgsz=640,
            persist=True,
            classes=VEHICLE_CLASSES,
            conf=VEHICLE_CONF,
            verbose=False
        )

        if v_results[0].boxes is not None and v_results[0].boxes.id is not None:
            boxes = v_results[0].boxes.xyxy.cpu().numpy().astype(int)
            track_ids = v_results[0].boxes.id.cpu().numpy().astype(int)

            for box, track_id in zip(boxes, track_ids):
                current_frame_track_ids.append(track_id)
                vx1, vy1, vx2, vy2 = box

                # 初始化状态机
                if track_id not in vehicle_states:
                    vehicle_states[track_id] = {
                        "has_final_result": False,
                        "final_text": "",
                        "was_snapshot": False,
                        # 方案二新增：缓存最后的有效视觉信息，用于兜底抓拍
                        "last_frame": None,
                        "last_box": None,
                        "last_exp_rect": None,
                        "last_flattened_plate": None
                    }
                    voter.add_record(track_id)

                state = vehicle_states[track_id]

                # 画全景车身检测框 (蓝色)
                cv2.rectangle(frame, (vx1, vy1), (vx2, vy2), (255, 0, 0), 3)
                cv2.putText(frame, f"ID: {track_id}", (vx1, vy1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 0, 0), 2)

                # 策略拦截一：如果已经锁定了稳固结果，直接挂字，跳过全套计算！
                if state["has_final_result"]:
                    frame = cv2_add_chinese_text(frame, state["final_text"], (vx1, vy1 - 40), textColor=(0, 255, 0),
                                                 textSize=30)
                    continue

                # ==========================================
                # 阶段二：原生 4K ROI 切片提取 (SAHI 核心)
                # ==========================================
                cx1 = max(0, vx1 - ROI_MARGIN)
                cy1 = max(0, vy1 - ROI_MARGIN)
                cx2 = min(orig_w, vx2 + ROI_MARGIN)
                cy2 = min(orig_h, vy2 + ROI_MARGIN)

                roi_crop = frame[cy1:cy2, cx1:cx2].copy()
                if roi_crop.size == 0: continue

                # ==========================================
                # 阶段三：高清切片下的 OBB 找牌 (imgsz=320)
                # ==========================================
                p_results = plate_model(roi_crop, imgsz=320, verbose=False)

                if len(p_results[0].obb) > 0:
                    best_obb = p_results[0].obb[0]  # 取置信度最高的车牌
                    pts_local = best_obb.xyxyxyxy[0].cpu().numpy().astype(int)

                    # 在 ROI 切片上面画出倾斜框供调试预览
                    cv2.polylines(roi_crop, [pts_local], isClosed=True, color=(0, 255, 0), thickness=2)

                    # 坐标还原到全图，准备透视变换
                    pts_global = pts_local + np.array([[cx1, cy1]])
                    rect_global = order_points(pts_global)
                    exp_rect = expand_rect(rect_global, pad_x=5, pad_y=5)  # 加上 pad 保护字

                    # 透视变换拉平车牌
                    width, height = 320, 96
                    dst_pts = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
                                       dtype="float32")
                    M = cv2.getPerspectiveTransform(exp_rect.astype("float32"), dst_pts)
                    flattened_plate = cv2.warpPerspective(raw_full_frame, M, (width, height))

                    if flattened_plate.size == 0: continue

                    # 【核心更新】只要拿到一次有效的车牌切片，就将其缓存，以备兜底使用
                    state["last_frame"] = raw_full_frame.copy()
                    state["last_box"] = (vx1, vy1, vx2, vy2)
                    state["last_exp_rect"] = exp_rect
                    state["last_flattened_plate"] = flattened_plate.copy()

                    # ==========================================
                    # 阶段四：PaddleOCR 与投票机制
                    # ==========================================
                    if ocr is None:
                        print("--> First plate found, loading PaddleOCR...")
                        ocr = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False)
                    ocr_result = ocr.ocr(flattened_plate, cls=False)

                    if ocr_result and ocr_result[0]:
                        text_str = ocr_result[0][0][1][0]
                        conf = ocr_result[0][0][1][1]

                        # 送入投票器
                        is_stable, final_result = voter.vote(track_id, text_str, conf)

                        if is_stable:
                            # 如果 OCR 没认出省份汉字（小于 6 位），我们认为不完善，不锁定，继续投
                            if len(final_result) < 6: continue

                            # 达成共识，锁定状态机！以后这辆车再也不用跑 OCR 了
                            state["has_final_result"] = True
                            state["final_text"] = final_result
                            print(f"✅ [ID {track_id}] 锁定共识车牌: {final_result} - conf:{conf:.2f}")

                            # 策略拦截二：全流量证据抓拍 (成功瞬间触发一次)
                            if not state["was_snapshot"]:
                                try:
                                    # A. 证据一：原生全景环境图 (无检测框，确保干净)
                                    snapshot_full_path = os.path.join(snapshot_dir,
                                                                      f"{track_id}_{final_result}_full.jpg")
                                    capture_img = cv2_add_chinese_text(raw_full_frame,
                                                                       f"ID: {track_id} | {final_result}",
                                                                       (vx1, vy1 - 50), textSize=40)
                                    cv2.rectangle(capture_img, (vx1, vy1), (vx2, vy2), (255, 0, 0), 4)  # 车框
                                    cv2.polylines(capture_img, [exp_rect.astype(int)], isClosed=True, color=(0, 255, 0),
                                                  thickness=2)
                                    cv2.imwrite(snapshot_full_path, capture_img)

                                    # B. 证据二：特写拉平车牌图 (证明 OCR 输入)
                                    snapshot_plate_path = os.path.join(snapshot_dir,
                                                                       f"{track_id}_{final_result}_plate.jpg")
                                    cv2.imwrite(snapshot_plate_path, flattened_plate)

                                    state["was_snapshot"] = True  # 标记已抓拍
                                    print(f"📸 抓拍成功！证据已保存 -> {snapshot_full_path}")
                                except Exception as e:
                                    print(f"❌ 抓拍保存失败: {e}")
                        else:
                            # 投票进行中，在大图车头上显示即时的文字（用于提示用户它已经框住了）
                            frame = cv2_add_chinese_text(frame, f"识别中:{text_str}", (vx1, vy1 - 35),
                                                         textColor=(0, 255, 255), textSize=20)

                    # 为了让你能看到 OBB 模型看到的那点微小的切片
                    cv2.imshow("Native ROI Crop (What OBB sees)", roi_crop)

        # ==========================================
        # 阶段五：目标丢失兜底检测与内存清理逻辑
        # ==========================================
        active_state_ids = list(vehicle_states.keys())
        for t_id in active_state_ids:
            # 如果状态机里有这个车，但当前帧 YOLO 没检测到它（车开走了，或者被大型障碍物完全遮挡）
            if t_id not in current_frame_track_ids:
                state = vehicle_states[t_id]

                # 如果这辆车直到消失都没能触发常规抓拍，且系统成功提取过至少一次车牌特征
                if not state["was_snapshot"] and state["last_frame"] is not None:
                    # 从投票历史中强行取出得票最高的答案
                    best_text, vote_count = voter.get_best_guess(t_id)

                    if best_text and len(best_text) >= 6:
                        print(f"⚠️ [ID {t_id}] 目标离开画面，触发兜底抓拍! 最高得票: {best_text} ({vote_count}票)")

                        last_frame = state["last_frame"]
                        vx1, vy1, vx2, vy2 = state["last_box"]
                        last_rect = state["last_exp_rect"]
                        last_plate = state["last_flattened_plate"]

                        try:
                            # 兜底抓拍存图 (加上 _fallback 后缀方便日后筛选人工复核)
                            fallback_full_path = os.path.join(snapshot_dir, f"{t_id}_{best_text}_fallback_full.jpg")
                            # 兜底文字标橙色警告色
                            capture_img = cv2_add_chinese_text(last_frame, f"ID: {t_id} | {best_text}(兜底)",
                                                               (vx1, vy1 - 50), textSize=40, textColor=(0, 165, 255))
                            cv2.rectangle(capture_img, (vx1, vy1), (vx2, vy2), (255, 0, 0), 4)
                            cv2.polylines(capture_img, [last_rect.astype(int)], isClosed=True, color=(0, 255, 0),
                                          thickness=2)
                            cv2.imwrite(fallback_full_path, capture_img)

                            fallback_plate_path = os.path.join(snapshot_dir, f"{t_id}_{best_text}_fallback_plate.jpg")
                            cv2.imwrite(fallback_plate_path, last_plate)
                            print(f"📸 兜底抓拍成功！ -> {fallback_full_path}")
                        except Exception as e:
                            print(f"❌ 兜底抓拍保存失败: {e}")

                # 安全清理机制：释放彻底消失的车辆字典和投票历史，防止内存无限膨胀
                del vehicle_states[t_id]
                if t_id in voter.history:
                    del voter.history[t_id]

        # 全流量防变形缩小显示
        display_full = cv2.resize(frame, (1280, 720))
        cv2.imshow(main_window, display_full)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or is_window_closed(main_window):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("====== 引擎已安全关闭，资源完全释放 ======")


if __name__ == "__main__":
    # 替换成你的测试视频路径
    test_video = r"D:\YOLO_ALPR_Project\测试图\14.mp4"
    run_production_sahi_alpr(test_video)
    sys.exit(0)
