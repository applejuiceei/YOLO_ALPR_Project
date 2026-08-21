# PC Stage 6 PlateDetector + PlateCropper 实测报告

测试时间：2026-08-21

## 结论

- 已实现独立 C++ `IPlateDetector/YoloObbOnnxPlateDetector` 与 `IPlateCropper/PlateCropper`，主链路更新为 `Vehicle ROI → PlateDetector → PlateCropper`。
- Detector 只接收车辆 ROI，不对整张 1080P 图像检测车牌；输出同时保留轴对齐 `bbox`、四个 OBB 角点、置信度和弧度角度，为后续透视矫正保留完整几何信息。
- C++ 后处理按该 Ultralytics OBB 导出协议解析 `xywh + confidence + angle`，并使用 ProbIoU 做旋转框 NMS，不把普通水平框 NMS 冒充 OBB NMS。
- 独立原始车辆 ROI 测试检出 1 个真实车牌，置信度 `0.94`，推理 `12.600 ms`，裁剪位置目视正确。
- 610 帧正式运行共调用 PlateDetector 128 次，检出并成功裁剪 69 个车牌，0 个无效裁剪；PlateDetector 推理 mean/P50/P95 为 `19.876/19.094/25.072 ms`。

## 用户要求的 15 项信息

1. 新增文件：`include/plate/plate_detector.hpp`、`include/plate/yolo_obb_onnx_plate_detector.hpp`、`include/plate/plate_cropper.hpp`、`src/plate/yolo_obb_onnx_plate_detector.cpp`、`src/plate/plate_cropper.cpp`、`tests/plate_detector_test.cpp`、`tests/plate_cropper_test.cpp`、`STAGE6_REPORT.md`。
2. 修改文件：`include/common/types.hpp`、`include/common/config.hpp`、`src/common/config.cpp`、`src/main.cpp`、`config/config.yaml`、`CMakeLists.txt`、`README.md` 和根目录项目记忆；未修改 `alpr_topk_capture.py`。
3. 模块输入：PlateDetector 输入 `CV_8UC3` BGR 车辆 ROI；PlateCropper 输入同一车辆 ROI 和一个 `PlateDetection`。
4. 模块输出：Detector 输出 `std::vector<PlateDetection>`，包含车辆 ROI 坐标系中的 `bbox/corners/confidence/angle_radians`；Cropper 输出 `std::optional<PlateCrop>`，包含浅 ROI、源 bbox 和裁剪坐标系内的四角点。
5. 使用模型：现有 Ultralytics YOLO11 OBB 单类车牌模型 `best_obb.onnx`，类别为 `license_plate`。ONNX 元数据标明 Ultralytics 8.4.64、task=obb、未内置 NMS。
6. 模型位置：`models/plate_detector/best_obb.onnx`；SHA256 为 `4AD061EA0034182C534FDB6970E3053B84FEB8EE2D92B76C6967F85B94F14BB0`。
7. 模型输入尺寸：RGB float32 NCHW `1×3×320×320`，除以255，保持比例 letterbox，填充值114。
8. 模型输出格式：float32 `1×6×2100`；6个通道依次为输入尺度上的 `center_x/center_y/width/height/class_confidence/angle_radians`。模型只有一个类别，C++ 置信度过滤后使用 ProbIoU OBB NMS，再映射四角点回车辆 ROI。
9. 是否使用 RK3588 NPU：本轮为 Windows ONNX Runtime CPU，`npu_used=false`；已有同源 `best_obb.rknn` 尚未在本 C++ 接口中接入验证。
10. 实际 FPS：610 个已处理帧用时 33.962 秒，处理吞吐 `17.961 FPS`。
11. CPU 占用：约 `100.000%` 单逻辑核等效口径；包含车辆检测、颜色、车牌检测、解码和写盘。
12. NPU 占用：不适用，本轮未调用 NPU。
13. 内存占用：工作集 `439.469 MiB`。
14. 当前问题：丢弃398个过期源帧，Tracker发布4个ID；车牌命中按Track为`ID1=45、ID3=2、ID4=22、ID5=0`。PlateCropper目前只做轴对齐浅裁剪，尚未透视拉正；远距离小牌仍很模糊，尚无质量门控；蓝牌已实测命中，黄牌和新能源绿牌覆盖仍待确认；模型元数据声明AGPL-3.0，产品发布前需确认许可合规。输出目录保留先前300帧冒烟产物，正式计数只以最新`summary.json`为准。
15. 下一步：实现独立 `PlateQualityEvaluator`，用清晰度、尺寸、亮度和对比度过滤低质量车牌；完成后再实现 `IPlateRectifier`，利用本阶段保留的四角点进行透视拉正和统一 resize。

## 配置协议

- `confidence=0.25`：车牌候选最低置信度，与现有 Python OBB 主线默认值保持一致。
- `nms=0.45`：ProbIoU 旋转框 NMS 阈值。
- `max_detections=3`：单个车辆 ROI 最多保留3个车牌候选，避免异常模型输出无界增长。
- `input_width/input_height=320`：固定模型输入尺寸，构造时与 ONNX 张量形状严格核对。
- PlateCropper 四方向扩张默认为0，最小尺寸为`8×4`，`clone_output=0`。

## 验证记录

- CTest：5/5通过。
- PlateCropper单测覆盖：浅引用、可选深拷贝、四方向扩张、边界裁剪、角点坐标转换、最小尺寸过滤、空图/无效框/溢出框拒绝和10万次微基准。
- PlateDetector独立入口：原始车辆ROI输出`plate 0.94 bbox=[12×5 from (11,21)] angle=-0.0247`，推理`12.600 ms`。
- 610帧：874个车辆检测、128次已确认轨迹观测和PlateDetector调用、69个车牌框、69个有效plate crop、0个无效crop。
- PlateDetector total mean/P95为`20.781/25.953 ms`；PlateCropper每个检测mean/P95均约`0.002 ms`。
- 当前输出：`runs/pc_stage6_plate_detection/summary.json`、`annotated.mp4`、`vehicle_rois/`、`plate_rois/`。
