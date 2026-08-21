# PC Stage 1 实测报告

测试时间：2026-08-19

本报告只覆盖当前第一步 PC 模拟链路：单路视频采集 → YOLO11n ONNX → 车辆/行人检测 → 画框与统计。用户已确认默认读取的 `deploy/144.mp4` 与 `测试图/14.mp4` 是同一段测试视频；使用前者是为了避开 Windows OpenCV 对中文视频路径支持不稳定的问题。

## 结论

- C++ 工程已能独立配置、编译和运行。
- `CameraManager` 与 `IVehicleDetector` 已解耦，后续 RKNN 实现可在不改变业务调用的前提下替换 ONNX Runtime 实现。
- 610 个已处理帧中输出 154 个目标框；目视抽查确认远处小车和驶近车辆的 `car` 框位置合理。
- 当前性能是 Windows ONNX Runtime CPU 结果，不是 RK3588 NPU 结果，也不能代表最终四路性能。
- 当前视频约 30 FPS，而处理速度约 15.42 FPS；有界最新帧队列丢弃了 560 个过期帧，避免延迟无限积累。诊断输出视频只包含已处理帧，因此不是原始时间轴的完整复刻。

## 用户要求的 15 项信息

1. 新增文件：完整清单见 `README.md` 的模块说明；核心包括接口头文件、CameraManager、YOLO11 ONNX detector、主程序、独立 detector 测试、构建/运行脚本和本报告。
2. 修改文件：本轮只在新目录 `rk3588_vehicle_system` 内新增或修改 C++ 工程；同时追加更新根目录项目记忆文档。未修改 `alpr_topk_capture.py`。
3. 模块输入：单路 `1920×1080` 视频帧，封装为包含 `camera_id`、`lane_id`、`frame_id`、时间戳和 `cv::Mat` 的 `FramePacket`。
4. 模块输出：`std::vector<Detection>`，每项包含 COCO `class_id`、映射后的目标类型、置信度和 `cv::Rect bbox`；主程序另输出画框 MP4 与 JSON 性能汇总。
5. 使用模型：Rockchip RKNN Model Zoo YOLO11 示例提供的优化版 YOLO11n ONNX。
6. 模型位置：`models/vehicle_detector/yolo11n.onnx`。
7. 模型输入尺寸：RGB float32 NCHW `1×3×640×640`，保持比例 letterbox。
8. 模型输出格式：9 个 float32 张量；80/40/20 三个尺度各有 `64` 通道 DFL 框、`80` 通道类别分数和 `1` 通道分数和。后处理采用 DFL 解码、目标类别过滤和按类 NMS。
9. 是否使用 RK3588 NPU：否。当前 `onnxruntime-cpu`，汇总中 `npu_used=false`。
10. 实际 FPS：610 帧总用时 39.550 秒，处理速度 `15.423 FPS`。
11. CPU 占用：进程 CPU 时间约等于墙钟时间，即 `99.999%` 单逻辑核等效口径；不是整机所有核心总占用百分比。
12. NPU 占用：不适用；PC 本轮未调用 NPU。
13. 内存占用：进程工作集 `390.801 MiB`。
14. 当前问题：尚未实现 RKNN/NPU 后端；未连接摄像头；未实现 VehicleCropper、颜色、ByteTrack、车牌和融合；单路约 30 FPS 输入快于 CPU detector，过期帧会被丢弃；当前样本片段的类别多样性不足，不能据此给出各类别准确率。
15. 下一步：严格按既定顺序实现 Step 3 `VehicleCropper`，先做独立单元/图片测试和 ROI 输出；随后再评估并接入可替换的车辆颜色模型。摄像头恢复且转回板端时，再新增 `Yolo11RknnVehicleDetector` 与 V4L2/RGA 输入实现。

## 性能明细

来自 `runs/pc_stage1/summary.json`：

| 指标 | 结果 |
|---|---:|
| 已处理帧 | 610 |
| 目标框总数 | 154 |
| 过期队列帧 | 560 |
| 推理平均 | 53.446 ms |
| 推理 P50 | 51.128 ms |
| 推理 P95 | 73.548 ms |
| detector 总耗时平均 | 58.076 ms |
| detector 总耗时 P95 | 78.914 ms |

## 验证记录

- Release 构建成功：`build/windows-x64/bin/vehicle_demo.exe`、`vehicle_detector_test.exe`。
- CTest：1/1 通过。
- 独立图片测试：道路图片检测到 `car 0.81`，框位置经目视检查合理。
- 视频测试：610 帧无崩溃退出；生成 `runs/pc_stage1/annotated.mp4`、`summary.json` 和目视抽查图 `contact_sheet.jpg`。
