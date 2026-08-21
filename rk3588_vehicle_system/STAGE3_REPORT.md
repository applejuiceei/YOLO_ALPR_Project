# PC Stage 3 车辆颜色分类实测报告

测试时间：2026-08-20

## 结论

- 已将官方 PP-Vehicle 车辆属性 PP-LCNet 模型转换为 ONNX，并实现独立、可替换的 `IVehicleColorClassifier`。
- Paddle 2.6.2 与 ONNX Runtime 对同一车辆 ROI 的最大绝对输出误差为 `8.34e-7`；转换脚本复现出的 ONNX 与当前模型 SHA256 完全一致。
- 黑车和白车独立样本分别得到 `black 0.621165`、`white 0.863887`；610 帧主链路完成 173 次真实颜色分类，画面已显示车辆类型和颜色标签。
- 本阶段是 Windows ONNX Runtime CPU 验证，`npu_used=false`；尚未做 ONNX 到 RKNN 转换和板端性能测试。

## 用户要求的 15 项信息

1. 新增文件：`include/classifier/vehicle_color_classifier.hpp`、`include/classifier/pp_vehicle_onnx_color_classifier.hpp`、`src/classifier/pp_vehicle_onnx_color_classifier.cpp`、`tests/vehicle_color_classifier_test.cpp`、`scripts/convert_vehicle_color_model.py`、`STAGE3_REPORT.md`。
2. 修改文件：`.gitignore`、`CMakeLists.txt`、`include/common/types.hpp`、`include/common/config.hpp`、`src/common/config.cpp`、`src/main.cpp`、`config/config.yaml`、`README.md` 和根目录项目记忆；未修改 `alpr_topk_capture.py`。
3. 模块输入：OpenCV BGR `cv::Mat vehicle_roi`，来自独立 `VehicleCropper`。
4. 模块输出：`ColorResult`，包含规范化后的 `color/confidence`，并预留 `primary_color/secondary_color`；当前只输出主颜色。
5. 使用模型：PaddleDetection PP-Vehicle 发布的 PP-LCNet 车辆属性模型；当前只读取其前 10 个车辆颜色概率，不使用后 9 个车型属性。
6. 模型位置：原始 Paddle 文件在 `models/vehicle_color/vehicle_attribute_model/`；正式 PC ONNX 为 `models/vehicle_color/vehicle_attribute_pp_lcnet.onnx`，SHA256 为 `47770502245FE0971E9E0D77FDDD5FB952C288FF26133FD5F199F11A001D25B8`。
7. 模型输入尺寸：动态 batch、`N×3×192×256`，RGB float32 NCHW；像素除以 255 后按 ImageNet mean/std 归一化。
8. 模型输出格式：`N×19` float32 概率。前 10 项依次为 `yellow/orange/green/gray/red/blue/white/golden/brown/black`，后 9 项为车型属性。输出节点已经带 Sigmoid，C++ 后处理不重复 Sigmoid。系统规范映射将 `orange/golden` 归入 `other`；模型没有 `silver` 类，不伪造该结果。
9. 是否使用 RK3588 NPU：否；本轮为 PC ONNX Runtime CPU。模型的 RKNN 转换兼容性仍待板端工具链验证。
10. 实际 FPS：610 个已处理帧用时 33.834 秒，处理吞吐 `18.029 FPS`。由于 CameraManager 按源速读取且最新帧队列会丢弃过期帧，本次采样与 Stage 2 不完全一致，不能把 FPS 差异归因于颜色模块。
11. CPU 占用：约 `99.999%` 单逻辑核等效口径；包含检测、颜色、视频解码和写盘。
12. NPU 占用：不适用，本轮未调用 NPU。
13. 内存占用：工作集 `404.301 MiB`。
14. 当前问题：没有带人工颜色真值的数据集，黑/白样本和目视结果只能证明模型协议与链路正确，不能给出整体准确率；远处小车辆仍可能因像素不足误判；610 帧中 1 次低于阈值映射为 `other`；本轮队列丢弃 395 个过期帧。
15. 下一步：实现独立 C++ ByteTrack，每个 Camera 单独维护跟踪器，让颜色结果与稳定 `track_id` 关联；之后再实现 `VehicleFusion`，不直接逐帧发布颜色。

## 性能与验证记录

- 颜色独立测试：黑车推理 `3.595 ms`，白车推理 `3.587 ms`，两者期望类别均通过。
- 610 帧主链路：173 个检测、173 个有效 ROI、173 次颜色调用、0 个无效裁剪、1 个 `other`。
- 颜色分类实际调用耗时：推理 mean/P50/P95 为 `5.461/5.385/7.108 ms`；完整分类 mean/P95 为 `6.030/7.777 ms`。这些统计的分母是实际颜色调用次数，不是输入帧数。
- CTest：2/2 通过；颜色模块另有带真实模型和图片的独立可执行测试。
- 可视核验：`runs/pc_stage3_color/annotated.mp4` 中已显示例如 `car 0.74 white 1.00`。
- 转换依赖安装在项目忽略目录 `third_party/python_conversion/`，未修改现有 Conda 环境。

## 结果位置

- `runs/pc_stage3_color/summary.json`
- `runs/pc_stage3_color/annotated.mp4`
- `runs/pc_stage3_color/vehicle_rois/`

