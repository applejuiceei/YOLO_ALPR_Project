import cv2
import numpy as np
import sys
from PIL import Image, ImageDraw, ImageFont
import time
import os
from ultralytics import YOLO
from paddleocr import PaddleOCR

# ==========================================
# 1. 核心工具函数与类 (重用投票和画字逻辑)
# ==========================================

class ALPRVoter:
    """车牌投票器 (3票共识机制)"""

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
    """边缘外扩保护 (带深拷贝)"""
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


# ==========================================
# 2. 主流控制与流水线 (SAHI + ROI + OCR + Snapshot)
# ==========================================

def run_production_sahi_alpr(video_path):
    print("====== 初始化工业级 SAHI + 抓拍视频流水线 ======")

    # 1. 创建保存抓拍图片的目录
    snapshot_dir = "D:/YOLO_ALPR_Project/captures"
    if not os.path.exists(snapshot_dir):
        os.makedirs(snapshot_dir)
        print(f"✅ 已创建抓拍目录: {snapshot_dir}")

    # 2. 挂载模型 (使用你的绝对路径)
    vehicle_model = YOLO(r"D:\YOLO_ALPR_Project\yolo11n.pt")  # 找车低清推理
    plate_model = YOLO(r"D:\YOLO_ALPR_Project\best_obb.pt")  # 找牌高清ROI推理
    ocr = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False)

    # 3. 初始化控制组件
    voter = ALPRVoter(consensus_threshold=3)
    vehicle_states = {}  # 状态机缓存: { track_id: {"has_final_result": False, "final_text": "", "box": None, "was_snapshot": False} }

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("❌ 视频加载失败")
        return

    # 窗口设置 (WINDOW_NORMAL 允许拖拽放大)
    cv2.namedWindow("Full ALPR View (Downscaled)", cv2.WINDOW_NORMAL)
    # 强行把这个窗口撑大，解决"啥也看不清"
    cv2.resizeWindow("Full ALPR View (Downscaled)", 1280, 720)

    ROI_MARGIN = 50

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break

        orig_h, orig_w = frame.shape[:2]

        # 保存一张原始的、没有任何框的 frame 用于抓拍原图
        raw_full_frame = frame.copy()

        # ==========================================
        # 阶段一：全局低清找车 (imgsz=640)
        # ==========================================

        # 使用 Ultralytics 内置追踪器，必须classes过滤
        v_results = vehicle_model.track(frame, imgsz=640, persist=True, classes=[2, 3, 5, 7], verbose=False)

        if v_results[0].boxes is not None and v_results[0].boxes.id is not None:
            boxes = v_results[0].boxes.xyxy.cpu().numpy().astype(int)
            track_ids = v_results[0].boxes.id.cpu().numpy().astype(int)

            for box, track_id in zip(boxes, track_ids):
                vx1, vy1, vx2, vy2 = box

                # 初始化状态机
                if track_id not in vehicle_states:
                    vehicle_states[track_id] = {"has_final_result": False, "final_text": "", "was_snapshot": False}
                    voter.add_record(track_id)

                state = vehicle_states[track_id]

                # 画全景车身检测框 (蓝色)
                cv2.rectangle(frame, (vx1, vy1), (vx2, vy2), (255, 0, 0), 3)
                cv2.putText(frame, f"ID: {track_id}", (vx1, vy1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)

                # ==========================================
                # 策略拦截一：状态机缓存
                # ==========================================

                # 如果已经锁定了稳固结果，直接挂字，跳过全套计算！
                if state["has_final_result"]:
                    frame = cv2_add_chinese_text(frame, state["final_text"], (vx1, vy1 - 40), textColor=(0, 255, 0), textSize=30)
                    continue

                # ==========================================
                # 阶段二：原生 4K ROI 切片提取 (SAHI核心)
                # ==========================================

                cx1 = max(0, vx1 - ROI_MARGIN)
                cy1 = max(0, vy1 - ROI_MARGIN)
                cx2 = min(orig_w, vx2 + ROI_MARGIN)
                cy2 = min(orig_h, vy2 + ROI_MARGIN)

                # 这就是显微镜下的高清世界
                roi_crop = frame[cy1:cy2, cx1:cx2].copy()
                if roi_crop.size == 0: continue

                # ==========================================
                # 阶段三：高清切片下的 OBB 找牌 (imgsz=320)
                # ==========================================

                p_results = plate_model(roi_crop, imgsz=320, verbose=False)

                if len(p_results[0].obb) > 0:
                    best_obb = p_results[0].obb[0]  # 取置信度最高的车牌
                    pts_local = best_obb.xyxyxyxy[0].cpu().numpy().astype(int)

                    # 在 ROI 切片上画出倾斜框供调试预览
                    cv2.polylines(roi_crop, [pts_local], isClosed=True, color=(0, 255, 0), thickness=2)

                    # 坐标还原到全图，准备透视变换
                    pts_global = pts_local + np.array([[cx1, cy1]])

                    # ====== 透视变换拉平车牌 ======
                    rect_global = order_points(pts_global)
                    exp_rect = expand_rect(rect_global, pad_x=5, pad_y=5)  # 加上 pad 保护字

                    width, height = 320, 96
                    dst_pts = np.array([
                        [0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]
                    ], dtype="float32")

                    M = cv2.getPerspectiveTransform(exp_rect.astype("float32"), dst_pts)
                    flattened_plate = cv2.warpPerspective(raw_full_frame, M, (width, height))

                    if flattened_plate.size == 0: continue

                    # ==========================================
                    # 阶段四：PaddleOCR 与 投票机制
                    # ==========================================
                    # (可或增加 blur_score 清晰度过滤，这里砍掉追求代码干净)

                    ocr_result = ocr.ocr(flattened_plate, cls=False)

                    if ocr_result and ocr_result[0]:
                        text_str = ocr_result[0][0][1][0]
                        conf = ocr_result[0][0][1][1]

                        # 送入投票器
                        is_stable, final_result = voter.vote(track_id, text_str, conf)

                        if is_stable:
                            # ❌ 如果 OCR 没认出省份汉字（小于 6 位），我们认为不完善，不锁定，继续投
                            if len(final_result) < 6: continue

                            # 达成共识，锁定状态机！以后这辆车再也不用跑 OCR 了
                            state["has_final_result"] = True
                            state["final_text"] = final_result
                            print(f"✅ [ID {track_id}] 锁定共识车牌: {final_result} - conf:{conf:.2f}")

                            # ==========================================
                            # 策略拦截二：全流量证据抓拍 (成功瞬间触发一次)
                            # ==========================================
                            if not state["was_snapshot"]:
                                try:
                                    # 海康级证据链要求：全景+ROI抠图，图片中需要有车和车牌

                                    # A. 证据一：原生全景环境图 (无检测框，确保干净)
                                    snapshot_full_path = os.path.join(snapshot_dir, f"{track_id}_{final_result}_full.jpg")

                                    # 将结果留在抓拍原图上 (使用 Chinese Font, textColor=(0,255,0))
                                    capture_img = cv2_add_chinese_text(raw_full_frame, f"ID:{track_id} | {final_result}", (vx1, vy1 - 50), textColor=(0, 255, 0), textSize=40)

                                    # 画车身框和车牌框到原图
                                    cv2.rectangle(capture_img, (vx1, vy1), (vx2, vy2), (255, 0, 0), 4) # 车框
                                    cv2.polylines(capture_img, [exp_rect.astype(int)], isClosed=True, color=(0, 255, 0), thickness=2)
                                    cv2.imwrite(snapshot_full_path, capture_img)

                                    # B. 证据二：特写拉平车牌图 (证明 OCR 输入)
                                    snapshot_plate_path = os.path.join(snapshot_dir, f"{track_id}_{final_result}_plate.jpg")
                                    cv2.imwrite(snapshot_plate_path, flattened_plate)

                                    state["was_snapshot"] = True  # 标记已抓拍
                                    print(f"📸 抓拍成功！证据已保存 -> {snapshot_full_path}")
                                except Exception as e:
                                    print(f"❌ 抓拍保存失败: {e}")

                        else:
                            # 投票进行中，在大图车头上显示即时的文字 (用于提示用户它已经框住了)
                            frame = cv2_add_chinese_text(frame, f"识别中:{text_str}", (vx1, vy1 - 35), textColor=(0, 255, 255), textSize=20)


                # 为了让你能看到 OBB 模型看到的那个动得很小的切片
                cv2.imshow("Native ROI Crop (What OBB sees)", roi_crop)


        # 全流量防变形缩小显示
        display_full = cv2.resize(frame, (1280, 720))
        cv2.imshow("Full ALPR View (Downscaled)", display_full)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("====== 引擎已安全关闭，资源完全释放 ======")


if __name__ == "__main__":
    # 替换成你的测试视频路径
    test_video = r"D:\YOLO_ALPR_Project\测试图\14.mp4"
    run_production_sahi_alpr(test_video)
    sys.exit(0)