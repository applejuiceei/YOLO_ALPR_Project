# PC Stage 4 ByteTrack 实测报告

测试时间：2026-08-20

## 结论

- 已实现独立 C++ `IVehicleTracker/ByteTracker`，主链路顺序调整为 `Detector → ByteTrack → VehicleCropper → VehicleColorClassifier`。
- 实现包含 Kalman 运动预测、Hungarian 线性分配、高/低置信度两阶段关联、未确认轨迹二次确认、Lost 缓冲与恢复、类别兼容约束和超时移除。
- 每个 `ByteTracker` 实例独立维护 ID；当前 Camera 1 使用一个实例，未来四路将分别创建四个实例，不复制 AI 模型。
- 610 帧流程完成 154 次已确认轨迹观测，其中 14 次由低置信度检测维持；画面和 ROI 文件均已包含真实 `track_id`。
- 当前存在一次可复现断轨：后段同一车辆在画面底部盲区及跳帧后由 ID2 变为 ID3。该问题没有用过宽匹配阈值掩盖，留待调度和轨迹参数联合优化。

## 用户要求的 15 项信息

1. 新增文件：`include/tracker/vehicle_tracker.hpp`、`include/tracker/byte_tracker.hpp`、`src/tracker/byte_tracker.cpp`、`tests/vehicle_tracker_test.cpp`、`STAGE4_REPORT.md`。
2. 修改文件：`include/common/types.hpp`、`include/common/config.hpp`、`src/common/config.cpp`、`src/main.cpp`、`config/config.yaml`、`CMakeLists.txt`、`README.md` 和根目录项目记忆；未修改 `alpr_topk_capture.py`。
3. 模块输入：`std::vector<Detection>` 和严格递增的源 `frame_id`。Detector 阈值下调到 `0.10`，只为 ByteTrack 第二阶段保留低分框。
4. 模块输出：`std::vector<TrackedObject>`；包含 `track_id/bbox/class_id/type/confidence/age/hits`。只输出本帧有真实检测匹配的已确认轨迹，不输出纯预测框。
5. 使用模型：Tracker 不使用 AI 模型；上游仍是 Rockchip 优化 YOLO11n ONNX，颜色仍是 PP-Vehicle PP-LCNet ONNX。
6. 模型位置：Tracker 不需要模型；上游模型位于 `models/vehicle_detector/yolo11n.onnx` 和 `models/vehicle_color/vehicle_attribute_pp_lcnet.onnx`。
7. 模型输入尺寸：Tracker 不适用；它接收像素坐标框。上游 detector 为 `1×3×640×640`。
8. 输出格式：C++ `TrackedObject`；主视频标签格式例如 `ID:1 car 0.77 white 0.99`。性能 JSON 额外保存总轨迹观测、低分关联次数、唯一 ID 数和每个 ID 的观测次数。
9. 是否使用 RK3588 NPU：ByteTrack 本身按设计运行在 CPU；本轮上游模型也是 Windows ONNX Runtime CPU，整体 `npu_used=false`。
10. 实际 FPS：610 个已处理帧用时 37.741 秒，处理吞吐 `16.163 FPS`。
11. CPU 占用：约 `99.998%` 单逻辑核等效口径；包含检测、颜色、视频解码和写盘，ByteTrack 本身不是主要占用。
12. NPU 占用：不适用，本轮未调用 NPU。
13. 内存占用：工作集 `399.352 MiB`。
14. 当前问题：610 帧期间丢弃 512 个过期源帧；画面底部高速车辆在源帧大间隔下出现一次零重叠断轨，统计为 `ID1=80、ID2=2、ID3=72`；测试视频类别和车辆数量有限，不能据此给出通用 IDF1/MOTA；四路实例隔离已用单测验证但尚未搭建四路调度。
15. 下一步：实现独立 `VehicleFusion`，按 `track_id` 对颜色置信度加权投票，停止逐帧颜色直接作为最终结果；之后再进入车牌流水线。

## 配置协议

- `high_confidence=0.40`：第一次关联的高分框门槛。
- `low_confidence=0.10`：第二次关联可使用的最低分数。
- `new_track_confidence=0.50`：创建候选新轨迹门槛。
- `first_match_threshold=0.80`：高分关联最大代价，代价为 `1-IoU×score`。
- `second_match_threshold=0.50`：低分关联最大 IoU 代价。
- `unconfirmed_match_threshold=0.70`：候选轨迹确认代价。
- `track_buffer_frames=30`：Lost 轨迹按源帧号保留的范围。
- `class_aware=1`：机动车之间允许关联，person/non_motor 与机动车隔离。

## 验证记录

- CTest：3/3 通过。
- 独立测试覆盖：高分关联、低分二次关联、Lost 恢复、类别隔离、候选确认、超时移除、非递增帧拒绝、reset，以及两个 Camera Tracker 实例的独立 ID 空间。
- 610 帧检测输入：893 个 `>=0.10` 框，其中 148 个 `>=0.40`。
- 已确认轨迹观测：154；其中低分观测14；唯一已发布 ID 为3个。
- Tracker 耗时：每帧 mean/P95 为 `0.026/0.070 ms`。
- 车辆裁剪和颜色调用均为154次，0个无效 ROI。
- 结果：`runs/pc_stage4_bytetrack/summary.json`、`annotated.mp4`、`vehicle_rois/`。

