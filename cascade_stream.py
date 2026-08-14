import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import re
from ultralytics import YOLO
from paddleocr import PaddleOCR
from collections import defaultdict

# ==========================================
# 🛠️ 核心配置参数
# ==========================================
USE_ESPCN = False  # 视频流建议关闭超分，使用插值即可，保证 FPS
PADDING = 2  # 防切边保护
VOTE_THRESHOLD = 3  # 投票器门槛：同一辆车必须得到3次相同结果才确认输出


# ==========================================
# 🛠️ 工业级投票器 (ALPR Voter)
# ==========================================
class ALPRVoter:
    def __init__(self):
        self.plate_memory = defaultdict(list)
        self.confirmed_plates = {}

    def add_result(self, track_id, ocr_result):
        if track_id in self.confirmed_plates:
            return self.confirmed_plates[track_id]

        self.plate_memory[track_id].append(ocr_result)

        # 统计哪个结果出现的次数最多
        counts = {}
        for plate in self.plate_memory[track_id]:
            counts[plate] = counts.get(plate, 0) + 1

            if counts[plate] >= VOTE_THRESHOLD:
                self.confirmed_plates[track_id] = plate
                return plate
        return None


def cv2_add_chinese_text(img, text, position, textColor=(0, 255, 0), textSize=30):
    if (isinstance(img, np.ndarray)):
        img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img)
    try:
        fontStyle = ImageFont.truetype("simhei.ttf", textSize, encoding="utf-8")
    except IOError:
        fontStyle = ImageFont.load_default()
    draw.text(position, text, textColor, font=fontStyle)
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


def order_points(pts):
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def expand_rect(rect, pad_x, pad_y):
    new_rect = rect.copy()
    new_rect[0] = [new_rect[0][0] - pad_x, new_rect[0][1] - pad_y]
    new_rect[1] = [new_rect[1][0] + pad_x, new_rect[1][1] - pad_y]
    new_rect[2] = [new_rect[2][0] + pad_x, new_rect[2][1] + pad_y]
    new_rect[3] = [new_rect[3][0] - pad_x, new_rect[3][1] + pad_y]
    return new_rect


def process_video_stream(video_path):
    print("====== 正在启动工业级 ALPR 视频流水线 (满血性能优化版) ======")

    # ⚠️ 这里的模型路径确保是正确的
    vehicle_model = YOLO(r"D:\renlian\ultralytics-8.3.34\yolo11n.pt")
    plate_model = YOLO(r"D:\YOLO_ALPR_Project\best_obb.pt")
    ocr = PaddleOCR(use_angle_cls=False, lang="ch", det=False, show_log=False)
    voter = ALPRVoter()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"❌ 无法打开视频流: {video_path}")
        return

    # 开启窗口自适应大小，防止高分辨率视频溢出屏幕
    cv2.namedWindow("Dynamic ALPR Stream", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Dynamic ALPR Stream", 1280, 720)

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            print("🏁 视频播放结束！")
            break

        # 1. 启动视频级追踪引擎 (Tracker)
        v_results = vehicle_model.track(frame, classes=[2, 5, 7], conf=0.5, iou=0.4, persist=True, verbose=False)

        if v_results[0].boxes is not None and v_results[0].boxes.id is not None:
            boxes = v_results[0].boxes.xyxy.cpu().numpy().astype(int)
            track_ids = v_results[0].boxes.id.cpu().numpy().astype(int)

            for box, track_id in zip(boxes, track_ids):
                vx1, vy1, vx2, vy2 = box
                h_img, w_img = frame.shape[:2]

                # 安全越界保护
                vx1, vy1 = max(0, vx1), max(0, vy1)
                vx2, vy2 = min(w_img, vx2), min(h_img, vy2)

                # 画出车辆追踪框和 ID
                cv2.rectangle(frame, (vx1, vy1), (vx2, vy2), (255, 0, 0), 2)
                cv2.putText(frame, f"ID: {track_id}", (vx1, max(20, vy1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                            (255, 0, 0), 2)

                # ==========================================
                # 🚀 性能优化：过滤远景小车，拯救 FPS！
                # ==========================================
                car_width = vx2 - vx1
                car_height = vy2 - vy1
                if car_width < 100 or car_height < 80:
                    continue

                    # ==========================================
                # 💡 核心：Crop-and-Detect (抠图寻牌)
                # ==========================================
                car_crop = frame[vy1:vy2, vx1:vx2]
                if car_crop.size == 0: continue

                p_results = plate_model(car_crop, verbose=False)

                # ✅ 防空集校验：确保真的找到了车牌
                if p_results[0].obb is not None and len(p_results[0].obb) > 0:
                    best_obb = p_results[0].obb[0]

                    # 提取局部坐标并回填到原图
                    local_corners = best_obb.xyxyxyxy[0].cpu().numpy()
                    global_corners = local_corners + np.array([vx1, vy1])

                    # 画出绿色的车牌多边形框
                    pts = global_corners.reshape((-1, 1, 2)).astype(np.int32)
                    cv2.polylines(frame, [pts], isClosed=True, color=(0, 255, 0), thickness=2)

                    # 透视拍平
                    rect = order_points(global_corners)
                    rect = expand_rect(rect, PADDING, PADDING)

                    width, height = 440, 140
                    dst_pts = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
                                       dtype="float32")
                    M = cv2.getPerspectiveTransform(rect, dst_pts)
                    flattened_plate = cv2.warpPerspective(frame, M, (width, height))

                    # 图像增强与光照均衡
                    super_img = cv2.resize(flattened_plate, (width * 2, height * 2), interpolation=cv2.INTER_CUBIC)
                    lab = cv2.cvtColor(super_img, cv2.COLOR_BGR2LAB)
                    l, a, b = cv2.split(lab)
                    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                    cl = clahe.apply(l)
                    limg = cv2.merge((cl, a, b))
                    balanced_img = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

                    # ==========================================
                    # 🧠 OCR 识别与透视调试展示
                    # ==========================================
                    ocr_result = ocr.ocr(balanced_img, cls=False, det=False)
                    if ocr_result and ocr_result[0] and ocr_result[0][0]:
                        raw_str = ocr_result[0][0][0]
                        clean_str = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', raw_str)

                        # 统一文字显示坐标（在车牌正上方）
                        text_x = int(rect[0][0])
                        text_y = int(rect[0][1]) - 35

                        # 正则校验：是否是完美的中国车牌格式？
                        if re.match(
                                r'^[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领][A-Z][A-Z0-9D/F]{5,6}$',
                                clean_str):
                            final_plate = voter.add_result(track_id, clean_str)

                            if final_plate:
                                # 投票成功！稳稳锁死输出绿色
                                frame = cv2_add_chinese_text(frame, f"✅ {final_plate}", (text_x, text_y),
                                                             textColor=(0, 255, 0), textSize=35)
                            else:
                                # 还在投票积累中，显示黄色 Loading
                                frame = cv2_add_chinese_text(frame, f"⏳ {clean_str}", (text_x, text_y),
                                                             textColor=(0, 255, 255), textSize=25)
                        else:
                            # 如果没过正则，但长度大于 2，说明识别到了半拉子乱码，用红色打出来！
                            if len(clean_str) > 2:
                                frame = cv2_add_chinese_text(frame, f"❌ {clean_str}", (text_x, text_y),
                                                             textColor=(0, 0, 255), textSize=25)

        cv2.imshow("Dynamic ALPR Stream", frame)

        # ==========================================
        # 🛡️ 优雅退出机制
        # ==========================================
        # 1. 监听键盘 'q' 键退出
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        # 2. 监听鼠标点击右上角的 'X' 按钮退出
        if cv2.getWindowProperty("Dynamic ALPR Stream", cv2.WND_PROP_VISIBLE) < 1:
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    # ⚠️ 把这段换成你想测试的 MP4 路径，或者填 0 调用电脑摄像头
    process_video_stream(r"D:\YOLO_ALPR_Project\测试图\10.mp4")