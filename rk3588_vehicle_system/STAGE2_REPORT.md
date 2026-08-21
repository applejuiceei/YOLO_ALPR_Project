# PC Stage 2 VehicleCropper 实测报告

测试时间：2026-08-20

## 结论

- `VehicleCropper` 已作为独立模块实现并接入单路 C++ 主程序。
- 支持 bbox 边界修正、四方向比例扩张、最小尺寸过滤和可选深拷贝；默认 `clone_output=0`，ROI 与输入帧共享底层数据。
- 单元测试、真实道路图片、180 帧独立视频测试和 610 帧主链路测试均通过。
- 610 帧主链路产生 172 个有效车辆 ROI，拒绝 0 个，按配置保存前 64 个；目视检查近车与远车 ROI 内容正确。

## 用户要求的 15 项信息

1. 新增文件：`include/cropper/vehicle_cropper.hpp`、`src/cropper/vehicle_cropper.cpp`、`tests/vehicle_cropper_test.cpp`、`tests/vehicle_cropper_pipeline_test.cpp`、`STAGE2_REPORT.md`。
2. 修改文件：`include/common/types.hpp`、`include/common/config.hpp`、`src/common/config.cpp`、`src/main.cpp`、`config/config.yaml`、`CMakeLists.txt`、`README.md`，并追加根目录项目记忆；未修改 `alpr_topk_capture.py`。
3. 模块输入：只读 `cv::Mat frame` 和 `Detection` 中的 `cv::Rect bbox`。
4. 模块输出：`std::optional<VehicleCrop>`；有效结果包含裁剪后在原图中的 `source_bbox` 和 `cv::Mat roi`，无效框返回 `std::nullopt`。
5. 使用模型：Cropper 本身不使用 AI 模型；集成测试的上游仍是 Rockchip 优化版 YOLO11n ONNX。
6. 模型位置：Cropper 不需要模型；上游模型为 `models/vehicle_detector/yolo11n.onnx`。
7. 模型输入尺寸：不适用；Cropper 接收原始分辨率 ROI。上游 detector 仍为 `1×3×640×640`。
8. 输出格式：OpenCV BGR `cv::Mat`，尺寸由裁剪后的 bbox 决定；默认浅引用，配置 `clone_output=1` 时深拷贝。
9. 是否使用 RK3588 NPU：否；Cropper 是 OpenCV/CPU 几何操作，本轮仍是 Windows PC。
10. 实际 FPS：610 帧主链路 `15.741 FPS`；Cropper 单元微基准平均 `0.042926 µs/次`，集成汇总每帧平均 `0.001 ms`、P95 `0.004 ms`。
11. CPU 占用：主链路约 `100.001%` 单逻辑核等效口径；主要来自 ONNX detector，不是 Cropper。
12. NPU 占用：不适用，本轮未调用 NPU。
13. 内存占用：主链路工作集 `391.449 MiB`。
14. 当前问题：远处车辆 ROI 像素很少，Cropper 只能正确裁剪，不能改善清晰度；当前尚无颜色分类模型；浅引用模式要求下游遵守 `cv::Mat` 生命周期，不得直接复用已释放的外部裸缓冲。
15. 下一步：按既定顺序评估并接入 PP-Vehicle/PPLCNet 车辆颜色预训练模型，先完成模型协议和 ONNX Runtime 独立分类测试，再接主链路。

## 测试记录

- CTest：2/2 通过，包括正常框、扩张、越界裁剪、最小尺寸、空帧、无效框、极端整数 bbox、浅引用和深拷贝。
- 图片集成：1 帧、1 个车辆检测、1 个 ROI、0 拒绝，平均裁剪 `1.3 µs`。
- 视频独立测试：180 帧、32 个车辆检测、32 个 ROI、0 拒绝、保存 16 张，平均裁剪 `1.975 µs`。
- 主链路：610 帧、172 个车辆检测、172 个 ROI、0 拒绝、保存 64 张；`npu_used=false`。
- 结果：`runs/pc_stage2_cropper/summary.json`、`annotated.mp4`、`vehicle_rois/`。
