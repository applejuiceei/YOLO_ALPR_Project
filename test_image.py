import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import re
from ultralytics import YOLO
from paddleocr import PaddleOCR

# ==========================================
# 🛠️ 架构师核心调试开关 🛠️
# ==========================================
USE_ESPCN = False  # False = 使用双三次插值 (防止摩尔纹被放大)；True = 开启超分网络
PADDING = 2  # OBB 边缘外扩像素，誓死保护第一个汉字不被切断


# ==========================================

def cv2_add_chinese_text(img, text, position, textColor=(0, 255, 0), textSize=30):
    """解决 OpenCV 无法直接渲染中文的问题"""
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
    """严格排序四个角点：左上, 右上, 右下, 左下"""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def expand_rect(rect, pad_x, pad_y):
    """【已修复】边缘外扩算法，保护汉字，彻底杜绝内存污染 Bug"""
    new_rect = rect.copy()  # 建立全新的内存副本！
    new_rect[0] = [new_rect[0][0] - pad_x, new_rect[0][1] - pad_y]  # 左上
    new_rect[1] = [new_rect[1][0] + pad_x, new_rect[1][1] - pad_y]  # 右上
    new_rect[2] = [new_rect[2][0] + pad_x, new_rect[2][1] + pad_y]  # 右下
    new_rect[3] = [new_rect[3][0] - pad_x, new_rect[3][1] + pad_y]  # 左下
    return new_rect


def test_single_image(image_path):
    print("====== 正在加载全链路静态调试引擎 (终极防弹版) ======")

    # 1. 加载所有模型
    vehicle_model = YOLO(r"D:\renlian\ultralytics-8.3.34\yolo11n.pt")
    plate_model = YOLO(r"D:\YOLO_ALPR_Project\best_obb.pt")

    if USE_ESPCN:
        sr = cv2.dnn_superres.DnnSuperResImpl_create()
        sr.readModel(r"D:\YOLO_ALPR_Project\ESPCN_x4.pb")
        sr.setModel("espcn", 4)

    ocr = PaddleOCR(use_angle_cls=False, lang="ch", det=False, show_log=False)

    # 2. 读取图片
    frame = cv2.imread(image_path)
    if frame is None:
        print(f"❌ 找不到图片，请检查路径: {image_path}")
        return

    # 3. 跑模型推理
    # 【已修复】加入 conf=0.5 和 iou=0.4，彻底杀掉重叠的幽灵车框！
    # 3. 一阶寻车 (扫描全图)
    v_results = vehicle_model(frame, classes=[2, 5, 7], conf=0.5, iou=0.4, verbose=False)
    vehicles = []
    if v_results[0].boxes is not None:
        for box in v_results[0].boxes:
            vehicles.append(list(map(int, box.xyxy[0])))

    print(f"📊 报告：官方模型找到 {len(vehicles)} 辆车")

    # ==========================================
    # 💡 核心升级：真正的两阶段级联 (抠图放大 -> 局部寻牌)
    # ==========================================
    plates_to_process = []

    if len(vehicles) > 0:
        print("🔍 启动【深度截取】模式：戴上八倍镜，在车身内部找车牌...")
        for v_box in vehicles:
            vx1, vy1, vx2, vy2 = v_box

            # 安全校验：防止车框越界导致裁剪报错
            h_img, w_img = frame.shape[:2]
            vx1, vy1 = max(0, vx1), max(0, vy1)
            vx2, vy2 = min(w_img, vx2), min(h_img, vy2)

            # 【绝招 1：物理抠图】把车辆单独切出来！
            car_crop = frame[vy1:vy2, vx1:vx2]
            if car_crop.size == 0: continue

            # 【绝招 2：局部推理】让 OBB 模型只看这辆车，彻底解决小目标丢失！
            p_results = plate_model(car_crop, verbose=False)

            if p_results[0].obb is not None:
                for obb in p_results[0].obb:
                    # 此时拿到的角点是相对于“车身小图”的
                    local_corners = obb.xyxyxyxy[0].cpu().numpy()

                    # 【绝招 3：坐标回填】加上车辆左上角的坐标，将其还原到大图的真实位置
                    global_corners = local_corners + np.array([vx1, vy1])

                    plates_to_process.append({
                        "corners": global_corners,
                        "v_box": v_box
                    })
    else:
        # 【降级模式】如果连车都没找到，启动全图盲搜（应对之前的局部特写）
        print("🛡️ 未找到车，启动【全图盲搜】降级模式...")
        p_results = plate_model(frame, verbose=False)
        if p_results[0].obb is not None:
            for obb in p_results[0].obb:
                global_corners = obb.xyxyxyxy[0].cpu().numpy()
                fake_v_box = [0, 0, frame.shape[1], frame.shape[0]]
                plates_to_process.append({
                    "corners": global_corners,
                    "v_box": fake_v_box
                })

    # ==========================================
    # 统一处理流水线 (后续代码基本不变)
    # ==========================================
    for p_data in plates_to_process:
        corners = p_data["corners"]
        vx1, vy1, vx2, vy2 = p_data["v_box"]

        # 只有在非降级模式（真实的框）才画蓝色车框
        if not (vx1 == 0 and vy1 == 0 and vx2 == frame.shape[1]):
            cv2.rectangle(frame, (vx1, vy1), (vx2, vy2), (255, 0, 0), 2)

        pts = corners.reshape((-1, 1, 2)).astype(np.int32)
        cv2.polylines(frame, [pts], isClosed=True, color=(0, 255, 0), thickness=2)

        # 4. 透视拍平 (加入防切边 Padding)
        rect = order_points(corners)
        rect = expand_rect(rect, PADDING, PADDING)

        width, height = 440, 140
        dst_pts = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32")
        M = cv2.getPerspectiveTransform(rect, dst_pts)
        flattened_plate = cv2.warpPerspective(frame, M, (width, height))

        # 5. 图像增强
        if USE_ESPCN:
            super_img = sr.upsample(flattened_plate)
        else:
            super_img = cv2.resize(flattened_plate, (width * 2, height * 2), interpolation=cv2.INTER_CUBIC)

        lab = cv2.cvtColor(super_img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)
        limg = cv2.merge((cl, a, b))
        balanced_img = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

        cv2.imshow("What OCR Sees (Balanced Image)", balanced_img)

        # 6. OCR 与工业校验
        ocr_result = ocr.ocr(balanced_img, cls=False, det=False)

        if ocr_result and ocr_result[0] and ocr_result[0][0]:
            raw_str = ocr_result[0][0][0]
            conf = ocr_result[0][0][1]
            print(f"✅ OCR 原始识别结果: '{raw_str}' (置信度: {conf:.4f})")

            clean_str = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', raw_str)
            if re.match(r'^[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领][A-Z][A-Z0-9D/F]{5,6}$',
                        clean_str):
                print(f"🟢 校验通过，完美车牌: {clean_str}")
                frame = cv2_add_chinese_text(frame, clean_str, (int(rect[0][0]), int(rect[0][1]) - 40),
                                             textColor=(0, 255, 0), textSize=40)
            else:
                print(f"🔴 校验失败 (清洗后: '{clean_str}')")
                frame = cv2_add_chinese_text(frame, f"Invalid: {clean_str}", (int(rect[0][0]), int(rect[0][1]) - 40),
                                             textColor=(0, 0, 255), textSize=30)
        else:
            print("🔴 OCR 未能读取到任何字符")

        break

        # 7. 渲染最终画面
    cv2.imshow("Static ALPR Test", frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    # ⚠️ 把你的图片名字放在这里跑！
    test_single_image(r"D:\YOLO_ALPR_Project\测试图\2.jpg")