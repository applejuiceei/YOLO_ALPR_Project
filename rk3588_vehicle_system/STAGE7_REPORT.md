# Stage 7：PlateQualityEvaluator

日期：2026-08-21

## 验收结论

已实现独立、可替换的 `IPlateQualityEvaluator` 和 OpenCV CPU 后端，并接入单路 PC 主链路。质量模块只接收有效 `PlateCrop`，不运行模型，不调用 OCR；通过质量门槛只表示“允许进入下一阶段”，不代表车牌号码已经识别正确。

## 1. 新增文件

- `include/plate/plate_quality_evaluator.hpp`
- `include/plate/opencv_plate_quality_evaluator.hpp`
- `src/plate/opencv_plate_quality_evaluator.cpp`
- `tests/plate_quality_test.cpp`
- `STAGE7_REPORT.md`

## 2. 修改文件

- `CMakeLists.txt`
- `config/config.yaml`
- `include/common/config.hpp`
- `include/common/types.hpp`
- `src/common/config.cpp`
- `src/main.cpp`
- `README.md`
- 根目录项目记忆文档

## 3. 模块输入

- 非空 OpenCV BGR `CV_8UC3` 车牌 ROI。
- 输入来自 `PlateCropper`，不直接读取整帧或车辆 ROI。

## 4. 模块输出

`PlateQuality` 输出原始指标、归一化子分、综合分、是否可用和拒绝原因：

- `blur_score`：灰度图 Laplacian 方差，越大通常越清晰。
- `brightness`：灰度均值。
- `contrast`：灰度标准差。
- `size/sharpness/exposure/contrast_score`：范围 `[0,1]`。
- `quality_score`：配置权重归一化后的 `[0,1]` 综合分。
- `acceptable`、`rejection_reason`。

## 5. 使用模型

无深度学习模型。实现使用 OpenCV `cvtColor`、`Laplacian` 和 `meanStdDev`。

## 6. 模型文件位置

不适用。本模块没有模型文件。

## 7. 模型输入尺寸

不适用。ROI 可变尺寸；当前最小硬门槛为 `24×8`，综合尺寸目标为 `64×20`。

## 8. 模型输出格式

不适用。C++ 输出为 `PlateQuality` 结构体，不是张量。

## 9. 是否使用 RK3588 NPU

否。质量评价是 OpenCV CPU 算法；本轮整体测试仍是 Windows ONNX Runtime CPU，`npu_used=false`。

## 10. 实际 FPS

`144.mp4` 正式运行610个已处理帧，端到端 `18.236 FPS`。这是异步最新帧链路的处理吞吐，不是输入源完整逐帧吞吐。

## 11. CPU 占用

进程 CPU 单核等效 `100.002%`。该数字按进程 CPU 时间除以墙钟时间计算。

## 12. NPU 占用

不适用；PC 没有运行 RKNN，不能报告或外推 RK3588 NPU 占用。

## 13. 内存占用

正式运行结束工作集 `435.910 MiB`。

## 14. 正式结果与当前问题

- 610帧产生861个检测、142次已确认轨迹观测和73个有效车牌 crop。
- 73次质量评价中33次通过、40次拒绝；ID1通过24次，ID3通过9次。
- 40次拒绝全部因为 ROI 小于 `24×8`，没有出现模糊、亮度、对比度或综合分拒绝。
- 质量分 mean/P50/P95 为 `0.587/0.595/0.756`。
- 质量评价耗时 mean/P95 为 `0.056/0.107 ms/crop`，不是当前性能瓶颈。
- 本轮丢弃380个过期源帧；PC CPU 模型推理仍是主要负载。
- 当前阈值仅基于这一段白天道路视频的分布，尚无夜间、过曝、黄牌和新能源绿牌验收集。
- Laplacian 方差受分辨率、插值和像素锯齿影响；因此尺寸是优先硬门槛，不能只依据清晰度数值。
- 目前 crop 仍是轴对齐矩形，透视和旋转可能影响质量指标；通过质量门槛也不等于 OCR 一定正确。

## 15. 下一步

只实现独立 `IPlateRectifier`：第一版保留 resize 后端，同时利用现有 OBB 四角点实现可配置透视拉正接口和确定性测试。Rectifier 验收后再进入 HSV 车牌颜色和 HyperLPR3 纯识别接入，不提前实现 PlateFusion 或四路调度。

## 测试

- CTest：6/6通过。
- 单测覆盖空输入、错误图像类型、错误配置、微小高频 ROI、模糊、过曝、低对比度、综合分门槛和正常样本。
- 目视抽查：`q_920_pass` 样本能看到完整蓝牌字符；`q_452_reject` 样本极小且字符信息不足。

产物目录：`runs/pc_stage7_plate_quality/`。
