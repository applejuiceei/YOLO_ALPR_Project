# RK3588 四路车辆结构化识别系统

当前完成 PC 单路车辆检测、ByteTrack、车辆裁剪、真实颜色分类、多帧颜色融合、车辆 ROI 内的 OBB 车牌检测/裁剪、OpenCV 车牌质量筛选、OBB 透视拉正、HSV 车牌颜色和 HyperLPR3 中文车牌纯识别。正式 RK3588 后端将实现相同接口的 RKNN/RGA 版本，不改变业务层调用方式。

## 当前模块

- `CameraManager`：只负责输入、`camera_id`、`lane_id`、`frame_id`、时间戳和有界 Frame Queue，不包含 AI 逻辑。
- `IVehicleDetector`：标准车辆检测接口。
- `Yolo11OnnxVehicleDetector`：Windows PC 的 ONNX Runtime CPU 实现。
- `IVehicleCropper` / `VehicleCropper`：边界修正、四方向可配置扩张、最小尺寸过滤；默认返回共享底层像素的 `cv::Mat` ROI。
- `IVehicleColorClassifier`：标准车辆颜色接口，预留主色和辅色字段。
- `PpVehicleOnnxColorClassifier`：Windows PC 的 PP-Vehicle/PP-LCNet ONNX Runtime CPU 实现。
- `IVehicleTracker` / `ByteTracker`：Kalman + Hungarian、高低分两阶段关联、候选确认、Lost 恢复；每路 Camera 独立实例。
- `IVehicleFusion` / `ConfidenceWeightedVehicleFusion`：按 Track ID 保存颜色历史并进行置信度加权投票，独立输出平均置信度、投票占比和稳定状态。
- `IPlateDetector` / `YoloObbOnnxPlateDetector`：只对车辆 ROI 做单类车牌 OBB 检测，保留 bbox、四角点、置信度和角度。
- `IPlateCropper` / `PlateCropper`：独立完成车牌边界修正、可配置扩张和浅 ROI 裁剪，并把四角点转换到 crop 坐标系。
- `IPlateQualityEvaluator` / `OpenCvPlateQualityEvaluator`：独立计算尺寸、Laplacian 方差、亮度、对比度和统一质量分，并给出可解释的拒绝原因。
- `IPlateRectifier` / `OpenCvPlateRectifier`：接收 PlateCrop 四角点，提供 resize 基线、旋转/透视拉正和无效几何回退，固定输出可配置的 `320×96` BGR 图像。
- `IPlateColorClassifier` / `HsvPlateColorClassifier`：只接收矫正后的 BGR 车牌图，按可配置 HSV 覆盖率输出 `blue/yellow/green/white/black/other` 和置信度。
- `IPlateRecognizer` / `HyperLpr3OnnxPlateRecognizer`：只接收矫正后的 BGR 车牌图，按 HyperLPR3 官方预处理和 CTC 协议输出 UTF-8 中文候选、置信度、格式状态和拒绝原因。
- `IPlateFusion` / `ConfidenceWeightedPlateFusion`：按 Camera 和 Track ID 隔离历史，对质量通过的号码与颜色分别做 Top-K 置信度加权投票；未稳定时保留最新有效单帧号码，稳定后切换为融合号码。
- `IUtf8TextRenderer` / `WindowsGdiUtf8TextRenderer`：使用 Windows GDI 和系统微软雅黑字体绘制 UTF-8 中文标签，仅转换小型标签区域，并为 RK3588 Linux FreeType 后端保留可替换接口。
- COCO 映射：`person`、`car`、`bus`、`truck`，并将 `bicycle`/`motorcycle` 映射为 `non_motor`。

## 模型

- 路径：`models/vehicle_detector/yolo11n.onnx`
- 来源：Rockchip RKNN Model Zoo 官方 YOLO11 示例提供的优化 ONNX。
- 输入：RGB float32，NCHW `1×3×640×640`。
- 输出：9 个 float32 张量；三个尺度分别输出 `64` 通道 DFL 框、`80` 类置信度和 `1` 通道置信度和。
- PC 后端：ONNX Runtime CPU；不使用 NPU。
- RK3588 后端：后续换成 `Yolo11RknnVehicleDetector` 和 `.rknn`，接口不变。

车辆颜色模型：

- 路径：`models/vehicle_color/vehicle_attribute_pp_lcnet.onnx`。
- 输入：RGB float32 NCHW `N×3×192×256`，ImageNet mean/std 归一化。
- 输出：`N×19` 概率；前 10 项为颜色，输出已包含 Sigmoid。
- 当前规范颜色为 `yellow/green/gray/red/blue/white/brown/black/other`；原模型 `orange/golden` 映射为 `other`，模型没有 `silver` 类。

车牌检测模型：

- 路径：`models/plate_detector/best_obb.onnx`。
- 输入：RGB float32 NCHW `1×3×320×320`，保持比例 letterbox。
- 输出：float32 `1×6×2100`，通道为`xywh/confidence/angle`；C++ 使用ProbIoU OBB NMS。
- 类别：单类`license_plate`；蓝牌已在当前视频中实测命中，黄牌和新能源绿牌覆盖待确认。

车牌识别模型：

- 路径：`models/plate_recognizer/rpv3_mdict_160_r3.onnx`。
- 来源：HyperLPR3 0.1.3 自带纯识别模型；SHA256 为 `8FB08B5DB2ADECCF43B05006BBBF409E4659D08D72E46A62631C00FF751EAEB3`。
- 输入：BGR float32 NCHW `1×3×48×160`，`(value-127.5)/127.5`，等比例缩放后右侧补零。
- 输出：float32 `1×20×78`；C++ 使用官方 CTC blank/去重和字符表协议解码。
- PC 后端：ONNX Runtime CPU；RKNN 转换和板端协议验证尚未进行。

## Windows 构建

```powershell
cd D:\YOLO_ALPR_Project\rk3588_vehicle_system
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

依赖固定放在 `third_party/prebuilt`，不会提交 Git：

```text
third_party/prebuilt/opencv
third_party/prebuilt/onnxruntime-win-x64-1.29.0
```

## 独立检测测试

```powershell
.\build\windows-x64\bin\vehicle_detector_test.exe `
  .\config\config.yaml `
  ..\测试图\grab214.jpg `
  .\runs\detector_test\grab214_result.jpg
```

## 单路视频测试

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_pc_demo.ps1 -MaxFrames 610 -NoDisplay
```

输出：

- `runs/pc_stage11_plate_fusion/annotated.mp4`
- `runs/pc_stage11_plate_fusion/summary.json`
- `runs/pc_stage11_plate_fusion/recognition_results.jsonl`
- `runs/pc_stage11_plate_fusion/plate_fusion_results.jsonl`
- `runs/pc_stage11_plate_fusion/vehicle_rois/*.jpg`
- `runs/pc_stage11_plate_fusion/plate_rois/*.jpg`
- `runs/pc_stage11_plate_fusion/rectified_plates/*.jpg`

## 独立 Cropper 测试

```powershell
.\build\windows-x64\bin\vehicle_cropper_test.exe

.\build\windows-x64\bin\vehicle_cropper_pipeline_test.exe `
  .\config\config.yaml --image ..\测试图\2.jpg `
  .\runs\cropper_image_test 1 8

.\build\windows-x64\bin\vehicle_cropper_pipeline_test.exe `
  .\config\config.yaml --video `
  ..\RK3588_dev\offline_bundle\rk3588_alpr_roadtest_bundle_20260701\deploy\144.mp4 `
  .\runs\cropper_video_test 180 16
```

当前 Windows 默认视频使用项目 RK 离线包中的 `deploy/144.mp4`；用户已确认它与
`测试图/14.mp4` 是同一段测试视频。这里使用 `144.mp4` 只是因为 OpenCV Windows 的
`VideoCapture(std::string)` 对中文文件路径支持不稳定；如需更换本地视频，请优先使用纯英文路径。

## 独立车辆颜色测试

```powershell
.\build\windows-x64\bin\vehicle_color_classifier_test.exe `
  .\config\config.yaml `
  .\runs\cropper_image_test\frame_000000_crop_0.jpg black

.\build\windows-x64\bin\vehicle_color_classifier_test.exe `
  .\config\config.yaml `
  .\runs\cropper_video_test\frame_000156_crop_0.jpg white
```

模型转换可用以下脚本复现，转换依赖来自项目隔离目录，不修改 Conda 环境：

```powershell
& D:\miniconda\envs\alpr_env\python.exe .\scripts\convert_vehicle_color_model.py
```

检测基线见 [STAGE1_REPORT.md](STAGE1_REPORT.md)，VehicleCropper 实测见 [STAGE2_REPORT.md](STAGE2_REPORT.md)，车辆颜色实测见 [STAGE3_REPORT.md](STAGE3_REPORT.md)。

## 独立 ByteTrack 测试

```powershell
.\build\windows-x64\bin\vehicle_tracker_test.exe
```

ByteTrack 实测和当前断轨边界见 [STAGE4_REPORT.md](STAGE4_REPORT.md)。Detector 配置阈值为
`0.10` 是为了保留第二阶段低分框；新轨迹仍需达到 Tracker 的 `0.50` 门槛。

## 独立 VehicleFusion 测试

```powershell
.\build\windows-x64\bin\vehicle_fusion_test.exe
```

VehicleFusion 实测、字段语义和稳定门槛见 [STAGE5_REPORT.md](STAGE5_REPORT.md)。画面标签中的
`F:30/1.00*` 表示当前有效历史为 30 个样本、获胜颜色权重占比 1.00，且结果已稳定。

## 独立车牌检测与裁剪测试

```powershell
.\build\windows-x64\bin\plate_cropper_test.exe

.\build\windows-x64\bin\plate_detector_test.exe `
  .\config\config.yaml `
  .\runs\pc_stage6_plate_detection\vehicle_rois\camera_1_frame_000163_track_1_crop_0.jpg `
  .\runs\plate_detector_test\raw_vehicle_output
```

OBB协议、独立结果和610帧性能见 [STAGE6_REPORT.md](STAGE6_REPORT.md)。

## 独立车牌质量测试

```powershell
.\build\windows-x64\bin\plate_quality_test.exe
```

默认先使用 `24×8` 尺寸硬门槛，再检查 Laplacian、亮度、对比度和综合分。文件名中的
`q_920_pass` 表示质量分约为0.920且可进入后续 OCR；`reject` 样本仍保存用于诊断。
接口、阈值语义和610帧结果见 [STAGE7_REPORT.md](STAGE7_REPORT.md)。

## 独立车牌矫正测试

```powershell
.\build\windows-x64\bin\plate_rectifier_test.exe
```

测试覆盖 resize、打乱顺序的四角点、梯形透视恢复、无效几何回退、禁用回退和非有限坐标。
正式结果与几何协议见 [STAGE8_REPORT.md](STAGE8_REPORT.md)。

## 独立车牌颜色测试

```powershell
.\build\windows-x64\bin\plate_color_classifier_test.exe

.\build\windows-x64\bin\plate_color_classifier_test.exe `
  .\config\config.yaml `
  .\runs\pc_stage9_plate_color\rectified_plates\camera_1_frame_000303_track_1_plate_0_q_921_perspective_color_blue_983.jpg `
  blue
```

无参数测试覆盖蓝、黄、绿、白、黑、其他、字符干扰、边缘干扰、模糊类别和错误输入。置信度是获胜颜色在有效内区的像素覆盖率，并非经过真值集校准的概率。接口与610帧结果见 [STAGE9_REPORT.md](STAGE9_REPORT.md)。

## 独立车牌识别测试

```powershell
.\build\windows-x64\bin\plate_recognizer_test.exe `
  .\config\config.yaml `
  ..\Dataset\dataset\test\sharp\grab10003.jpg `
  苏E803JV
```

该测试验证 C++ 输出与 HyperLPR3 Python 官方实现逐字、逐置信度一致，并检查空图拒绝。主链输出完整中文到 `recognition_results.jsonl`。接口、协议和610帧结果见 [STAGE10_REPORT.md](STAGE10_REPORT.md)。

## 独立 PlateFusion 与中文渲染测试

```powershell
.\build\windows-x64\bin\plate_fusion_test.exe
.\build\windows-x64\bin\utf8_text_renderer_test.exe
```

PlateFusion 测试覆盖权重投票、格式/置信度过滤、Top-K、同帧去重、历史滚动、过期清理、Track 隔离、颜色融合及单帧/稳定结果切换。UTF-8 测试覆盖 `京A12345`、`豫JC521G` 的严格 UTF-16 转换和 GDI 图像绘制。视频标签第一行显示车辆信息，第二行在车辆框上方显示 `车牌(单帧)` 或稳定后的 `车牌`。接口、正式结果和已知误识别见 [STAGE11_REPORT.md](STAGE11_REPORT.md)。

## 当前边界

- 本阶段不是 RK3588 性能结论，`npu_used=false`。
- 已实现按 Track ID 的 PlateFusion 和正确中文叠加；只有达到稳定门槛的融合结果才可作为当前 Track 的稳定候选，未稳定标签仍明确标为 `车牌(单帧)`。
- 尚未生成最终 `VehicleEvent`，也未实现多路统一调度。
- 真实视频只覆盖蓝牌场景，黄牌、绿牌、白牌和黑牌目前只有合成协议测试，真实准确率待确认。
- 摄像头硬件恢复后，先新增 RKNN detector 实现和 V4L2/RGA camera 实现，再开始板端 Camera 1 验收。
