import sys
import os
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import re
import torch
from torchvision import transforms
from ultralytics import YOLO
from paddleocr import PaddleOCR

# ==========================================
# 1. 动态引入自定义去模糊架构路径
# ==========================================
CUSTOM_DEBLUR_PATH = r"D:\YOLO_ALPR_Project\models_run"
if CUSTOM_DEBLUR_PATH not in sys.path:
    sys.path.insert(0, CUSTOM_DEBLUR_PATH)

try:
    from model import TinyUNet
except ImportError:
    raise ImportError(f"❌ 无法从 {CUSTOM_DEBLUR_PATH} 导入 TinyUNet，请检查本地路径。")

# ==========================================
# 2. 绘制与几何处理工具层
# ==========================================
def cv2_add_chinese_text(img, text, position, textColor=(0, 255, 0), textSize=30):
    """OpenCV 安全绘制中文文本"""
    if isinstance(img, np.ndarray):
        img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img)
    try:
        fontStyle = ImageFont.truetype("simhei.ttf", textSize, encoding="utf-8")
    except IOError:
        fontStyle = ImageFont.load_default()
    draw.text(position, text, textColor, font=fontStyle)
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)

def order_points(pts):
    """对四个角点进行顺时针排序: 左上, 右上, 右下, 左下"""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect

def expand_rect(rect, pad_x=2, pad_y=2):
    """适度缓冲层保护（降低过大外扩对轻量级去模糊网络的边缘特征污染）"""
    new_rect = rect.copy()
    new_rect[0] = [new_rect[0][0] - pad_x, new_rect[0][1] - pad_y]
    new_rect[1] = [new_rect[1][0] + pad_x, new_rect[1][1] - pad_y]
    new_rect[2] = [new_rect[2][0] + pad_x, new_rect[2][1] + pad_y]
    new_rect[3] = [new_rect[3][0] - pad_x, new_rect[3][1] + pad_y]
    return new_rect

# ==========================================
# 3. 稳定化神经网络去拖影引擎层
# ==========================================
def run_tiny_unet_deblur(flattened_bgr, model, device):
    """
    纯 FP32 稳定桥接层：剥离混合精度干扰，彻底消除高频波纹失真
    """
    if flattened_bgr is None or flattened_bgr.size == 0:
        return flattened_bgr

    orig_h, orig_w = flattened_bgr.shape[:2]

    # 强制等比对齐到训练基准规格 (宽 224 x 高 112)
    resized_bgr = cv2.resize(flattened_bgr, (224, 112), interpolation=cv2.INTER_CUBIC)

    # BGR -> RGB -> 转为纯 FP32 标准张量 [1, 3, H, W]
    rgb_img = cv2.cvtColor(resized_bgr, cv2.COLOR_BGR2RGB)
    input_tensor = transforms.ToTensor()(rgb_img).unsqueeze(0).to(device, dtype=torch.float32)

    # 绝对稳定无梯度推理（移除 autocast 杜绝 BatchNorm 统计量下溢崩坏）
    with torch.no_grad():
        output_tensor = model(input_tensor)

    # 张量转回视觉矩阵
    output_tensor = output_tensor.squeeze(0).cpu()
    output_arr = (output_tensor * 255).clamp(0, 255).numpy().astype(np.uint8)
    output_arr = np.transpose(output_arr, (1, 2, 0)) # CHW -> HWC
    restored_bgr = cv2.cvtColor(output_arr, cv2.COLOR_RGB2BGR)

    return cv2.resize(restored_bgr, (orig_w, orig_h), interpolation=cv2.INTER_LANCZOS4)

# ==========================================
# 4. 全链路兼容测试流水线
# ==========================================
def test_single_image(image_path):
    print("====== 🚀 正在启动端侧全链路 ALPR 分析引擎 (高兼容稳定版) ======")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    torch.cuda.empty_cache()

    # ------------------------------------------
    # A. 挂载 AI 模型引擎
    # ------------------------------------------
    vehicle_model = YOLO(r"D:\YOLO_ALPR_Project\yolo11n.pt")
    plate_model = YOLO(r"D:\YOLO_ALPR_Project\best_obb.pt")

    weights_path = r"D:\YOLO_ALPR_Project\My_models\tiny_unet_best.pth"
    if not os.path.exists(weights_path):
        raise FileNotFoundError(f"❌ 找不到去拖影权重，请核对路径: {weights_path}")

    deblur_model = TinyUNet().to(device)
    deblur_model.load_state_dict(torch.load(weights_path, map_location=device))
    deblur_model.eval() # 锁定推理计算图
    print("✅ TinyUNet 纯净去拖影内核就绪！")

    ocr = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False)

    # ------------------------------------------
    # B. 寻车与"无车保底直通逻辑" (安全修复版)
    # ------------------------------------------
    frame = cv2.imread(image_path)
    if frame is None:
        print(f"❌ 无法读取目标图片: {image_path}")
        return

    h_orig, w_orig = frame.shape[:2]
    vehicles = []

    # 第一阶段检测
    v_results = vehicle_model(frame, classes=[2, 3, 5, 7], verbose=False)
    if v_results[0].boxes is not None:
        for box in v_results[0].boxes.xyxy.cpu().numpy().astype(int):
            # 统一转化为纯 Python 标准列表，彻底根除 numpy 比较的二义性报错
            vehicles.append(box.tolist())

    print(f"🚓 寻车阶段结束 | 捕获标准车身数: {len(vehicles)} 辆")

    plates_to_process = []

    # 定义全局直通模式的专属特征框
    global_fallback_box = [0, 0, w_orig, h_orig]

    # 如果找不到完整车身，强行注入全图直通框
    if len(vehicles) == 0:
        print("⚠️ 未发现完整车辆，自动激活 [全局ROI直通模式] 搜寻疑似车牌...")
        vehicles.append(global_fallback_box)

    # 遍历有效区域寻找目标车牌
    for v_box in vehicles:
        vx1, vy1, vx2, vy2 = v_box
        car_crop = frame[vy1:vy2, vx1:vx2]
        if car_crop.size == 0: continue

        p_results = plate_model(car_crop, verbose=False)

        # 判断当前框是否为保底直通框
        is_fallback = (v_box == global_fallback_box)

        if p_results[0].obb is not None and len(p_results[0].obb) > 0:
            for obb in p_results[0].obb:
                local_corners = obb.xyxyxyxy[0].cpu().numpy()
                global_corners = local_corners + np.array([vx1, vy1])
                plates_to_process.append({
                    "corners": global_corners,
                    # 只有真实车辆才保留车身回框数据，直通模式设为 None
                    "v_box": None if is_fallback else v_box
                })
        else:
            # 保底分支：如果在直通模式下连 OBB 都没命中，直接对全图执行无损拉平
            if is_fallback:
                print("💡 检测到极小牌照微切片，直接跳过定位自动透视矫正...")
                fake_corners = np.array([[0, 0], [w_orig, 0], [w_orig, h_orig], [0, h_orig]])
                plates_to_process.append({"corners": fake_corners, "v_box": None})

    # ------------------------------------------
    # C. 去模糊与字符提取引擎
    # ------------------------------------------
    for p_data in plates_to_process:
        corners = p_data["corners"]
        v_box = p_data["v_box"]

        # 仅在非全局直通模式下绘制车身框
        if v_box is not None:
            cv2.rectangle(frame, (v_box[0], v_box[1]), (v_box[2], v_box[3]), (255, 0, 0), 2)

        # 绘制车牌边界多边形
        pts = corners.reshape((-1, 1, 2)).astype(np.int32)
        cv2.polylines(frame, [pts], isClosed=True, color=(0, 255, 255), thickness=2)

        # 透视矫正
        rect = order_points(corners)
        rect = expand_rect(rect, pad_x=2, pad_y=2) # 适度外扩保护边界

        width, height = 224, 112
        dst_pts = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32")

        M = cv2.getPerspectiveTransform(rect.astype("float32"), dst_pts)
        flattened_plate = cv2.warpPerspective(frame, M, (width, height))
        if flattened_plate.size == 0: continue

        # 🚀 启用高纯净物理去拖影内核
        restored_plate = run_tiny_unet_deblur(flattened_plate, deblur_model, device)

        # 渲染对比面板
        cv2.imshow("Input Blurred Plate", flattened_plate)
        cv2.imshow("TinyUNet Restored Plate", restored_plate)
        cv2.waitKey(1)

        # 读入 OCR 识字
        ocr_result = ocr.ocr(restored_plate, cls=False)

        # 计算车牌文字坐标位置
        txt_x = int(rect[0][0]) if v_box is None else v_box[0]
        txt_y = int(rect[0][1]) if v_box is None else v_box[1]

        if ocr_result and ocr_result[0]:
            raw_text = ocr_result[0][0][1][0]
            conf = ocr_result[0][0][1][1]

            clean_text = re.sub(r'[^A-Z0-9\u4e00-\u9fa5]', '', raw_text.upper())
            pattern = r"^[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领][A-Z][A-HJ-NP-Z0-9]{4,5}[A-HJ-NP-Z0-9挂学警港澳]$"

            if re.match(pattern, clean_text):
                print(f"✔️ 捕获真实车牌 -> [{clean_text}] | 置信度: {conf:.4f}")
                frame = cv2_add_chinese_text(frame, f"{clean_text} ({conf:.2f})", (max(0, txt_x), max(0, txt_y - 40)),
                                             textColor=(0, 255, 0), textSize=30)
            else:
                print(f"⚠️ 拦截异常输出: [{raw_text}]")
                frame = cv2_add_chinese_text(frame, f"疑似畸形: {raw_text}", (max(0, txt_x), max(0, txt_y - 30)),
                                             textColor=(0, 165, 255), textSize=20)
        else:
            print("❌ OCR 未识别有效字符。")

    # 等比展示渲染
    h_f, w_f = frame.shape[:2]
    max_w, max_h = 1280, 720
    if w_f > max_w or h_f > max_h:
        scale = min(max_w / w_f, max_h / h_f)
        display_frame = cv2.resize(frame, (int(w_f * scale), int(h_f * scale)), interpolation=cv2.INTER_AREA)
    else:
        display_frame = frame

    cv2.imshow("Final Recognition Result", display_frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    # 替换测试即可验证直通效果
    TARGET_TEST_IMAGE = r"D:\YOLO_ALPR_Project\测试图\grab4.jpg"
    test_single_image(TARGET_TEST_IMAGE)