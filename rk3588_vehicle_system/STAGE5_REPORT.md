# PC Stage 5 VehicleFusion 实测报告

测试时间：2026-08-21

## 结论

- 已实现独立 C++ `IVehicleFusion/ConfidenceWeightedVehicleFusion`，主链路更新为 `Detector → ByteTrack → VehicleCropper → VehicleColorClassifier → VehicleFusion`。
- 同一 `track_id` 的颜色按置信度加权投票；获胜颜色的平均置信度与其加权投票占比分开输出，避免混淆两个统计口径。
- 默认至少 3 个有效样本且投票占比不低于 0.60 才标记稳定；低于 0.50 的样本及 `other` 默认不参与投票。
- 610 帧完成 170 次融合更新，产生 164 次稳定观测，3 个 Track ID 均曾达到稳定门槛。融合平均/P95 耗时仅 `0.005/0.008 ms/次`。
- 目视抽查标注视频确认标签正常，例如 `white 1.00 F:30/1.00*`；`*` 代表稳定结果。

## 用户要求的 15 项信息

1. 新增文件：`include/fusion/vehicle_fusion.hpp`、`include/fusion/confidence_weighted_vehicle_fusion.hpp`、`src/fusion/confidence_weighted_vehicle_fusion.cpp`、`tests/vehicle_fusion_test.cpp`、`STAGE5_REPORT.md`。
2. 修改文件：`include/common/types.hpp`、`include/common/config.hpp`、`src/common/config.cpp`、`src/main.cpp`、`config/config.yaml`、`CMakeLists.txt`、`README.md` 和根目录项目记忆；未修改 `alpr_topk_capture.py`。
3. 模块输入：`track_id + ColorResult + frame_id`；每个 Track 的 `frame_id` 必须严格递增。
4. 模块输出：`std::optional<VehicleFusionResult>`，包含 `track_id`、融合 `ColorResult`、有效样本数、获胜颜色投票占比和稳定标志。
5. 使用模型：VehicleFusion 不使用 AI 模型；上游颜色结果来自 PP-Vehicle PP-LCNet ONNX。
6. 模型位置：Fusion 无模型；上游颜色模型位于 `models/vehicle_color/vehicle_attribute_pp_lcnet.onnx`。
7. 模型输入尺寸：Fusion 不适用；它接收结构化颜色结果。上游颜色模型输入为 RGB float32 NCHW `1×3×192×256`。
8. 输出格式：获胜颜色按置信度总和决定；`color.confidence` 是获胜颜色样本的平均置信度，`vote_ratio` 是获胜颜色权重占全部有效权重的比例，二者不混用。第一版不把第二名颜色伪装成车辆辅色。
9. 是否使用 RK3588 NPU：Fusion 本身是轻量 CPU 模块；本轮整体为 Windows ONNX Runtime CPU，`npu_used=false`。
10. 实际 FPS：610 个已处理帧用时 28.123 秒，处理吞吐 `21.691 FPS`。
11. CPU 占用：约 `100.001%` 单逻辑核等效口径；包含检测、颜色、视频解码和写盘。
12. NPU 占用：不适用，本轮未调用 NPU。
13. 内存占用：工作集 `409.176 MiB`。
14. 当前问题：本次丢弃 224 个过期源帧；170 次轨迹观测分布为 `ID1=112、ID3=3、ID4=55`，后段同一车辆仍可能因跟踪断裂分成多个 ID。Fusion 严格按 ID 隔离，不能也不应在没有重识别证据时跨 ID 合并；测试视频颜色单一，不能据此评价多颜色准确率。
15. 下一步：进入独立车牌流水线，先实现车辆 ROI 内的 `IPlateDetector` 与 `PlateCropper`，优先复用已有 `best_obb.onnx`；通过独立测试后再加入质量评价、矫正、HSV 车牌颜色和 HyperLPR3 纯识别。

## 配置协议

- `max_history_per_track=30`：每个 Track 最多保留 30 个有效颜色样本，超出后滚动淘汰最旧样本。
- `min_samples=3`：稳定结果所需的最少有效样本数。
- `min_sample_confidence=0.50`：进入投票的最低单帧颜色置信度。
- `min_vote_ratio=0.60`：获胜颜色达到稳定状态的最低加权占比。
- `stale_after_frames=60`：Track 超过该源帧间隔未更新时清除历史。
- `include_other=0`：默认不让模型的兜底类别参与主色投票。

## 验证记录

- CTest：4/4 通过。
- 独立测试覆盖：置信度加权、多样本稳定门槛、低置信度与 `other` 过滤、Track 隔离、重复帧拒绝、滚动窗口、过期清理和 reset。
- 610 帧检测输入：897 个 `>=0.10` 框，其中 174 个 `>=0.40`。
- 已确认轨迹观测/颜色调用/融合更新均为 170 次；无无效 ROI，无 `other` 颜色。
- 稳定融合观测 164 次；达到稳定状态的唯一 Track ID 数为 3。
- Fusion 更新耗时 mean/P95：`0.005/0.008 ms`；Tracker 每帧 mean/P95：`0.023/0.066 ms`。
- 结果：`runs/pc_stage5_vehicle_fusion/summary.json`、`annotated.mp4`、`vehicle_rois/`；目视抽查图为 `frame_220.jpg`。
