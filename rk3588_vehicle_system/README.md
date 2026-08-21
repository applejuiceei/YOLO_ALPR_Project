# RK3588 四路车辆结构化识别系统

当前完成 PC 单路车辆检测、ByteTrack、裁剪、真实颜色分类和多帧颜色融合：视频采集、Rockchip 优化版 YOLO11n ONNX 推理、两阶段目标跟踪、`VehicleCropper`、PP-Vehicle/PP-LCNet 颜色分类、按 Track ID 的置信度加权投票、ROI 保存、画框和性能统计。正式 RK3588 后端将实现相同接口的 RKNN 版本，不改变 Tracker、Cropper、Fusion 或业务层调用方式。

## 当前模块

- `CameraManager`：只负责输入、`camera_id`、`lane_id`、`frame_id`、时间戳和有界 Frame Queue，不包含 AI 逻辑。
- `IVehicleDetector`：标准车辆检测接口。
- `Yolo11OnnxVehicleDetector`：Windows PC 的 ONNX Runtime CPU 实现。
- `IVehicleCropper` / `VehicleCropper`：边界修正、四方向可配置扩张、最小尺寸过滤；默认返回共享底层像素的 `cv::Mat` ROI。
- `IVehicleColorClassifier`：标准车辆颜色接口，预留主色和辅色字段。
- `PpVehicleOnnxColorClassifier`：Windows PC 的 PP-Vehicle/PP-LCNet ONNX Runtime CPU 实现。
- `IVehicleTracker` / `ByteTracker`：Kalman + Hungarian、高低分两阶段关联、候选确认、Lost 恢复；每路 Camera 独立实例。
- `IVehicleFusion` / `ConfidenceWeightedVehicleFusion`：按 Track ID 保存颜色历史并进行置信度加权投票，独立输出平均置信度、投票占比和稳定状态。
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

- `runs/pc_stage5_vehicle_fusion/annotated.mp4`
- `runs/pc_stage5_vehicle_fusion/summary.json`
- `runs/pc_stage5_vehicle_fusion/vehicle_rois/*.jpg`

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

## 当前边界

- 本阶段不是 RK3588 性能结论，`npu_used=false`。
- 尚未实现车牌模块和多路统一调度。
- 摄像头硬件恢复后，先新增 RKNN detector 实现和 V4L2/RGA camera 实现，再开始板端 Camera 1 验收。
