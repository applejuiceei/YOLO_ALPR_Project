# Stage 8：PlateRectifier

日期：2026-08-21

## 验收结论

已实现独立、可替换的 `IPlateRectifier` 和 OpenCV CPU 后端，并接入质量筛选之后。只有 `PlateQuality.acceptable=true` 的样本才进入矫正；本阶段不运行车牌颜色或 OCR。

## 1. 新增文件

- `include/plate/plate_rectifier.hpp`
- `include/plate/opencv_plate_rectifier.hpp`
- `src/plate/opencv_plate_rectifier.cpp`
- `tests/plate_rectifier_test.cpp`
- `STAGE8_REPORT.md`

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

- `PlateCrop`：非空 OpenCV BGR `CV_8UC3` ROI，以及 PlateCropper 转换后的 ROI 局部四角点。
- 正式主链路仅对质量通过的 PlateCrop 调用；Rectifier 本身仍独立校验图像和几何。

## 4. 模块输出

- `std::optional<RectifiedPlate>`。
- `RectifiedPlate.image`：默认 BGR `320×96`。
- `ordered_source_corners`：按左上、右上、右下、左下排序后的源点。
- `method`：`Resize`、`Perspective` 或 `ResizeFallback`。

## 5. 使用模型

无深度学习模型。使用 OpenCV convex hull、四角排序、`getPerspectiveTransform`、`warpPerspective` 和 `resize`。

## 6. 模型文件位置

不适用。本模块没有模型文件。

## 7. 模型输入尺寸

不适用。输入 ROI 尺寸可变；输出尺寸由 `plate_rectifier.output_width/output_height` 配置，当前为 `320×96`。

## 8. 模型输出格式

不适用。输出是 C++ `RectifiedPlate`，图像为 `CV_8UC3` BGR，并显式记录采用的矫正方式。

## 9. 是否使用 RK3588 NPU

否。当前是 OpenCV CPU 几何变换；正式板端可在保持接口不变的前提下新增 RGA 或 STN/RKNN 后端。

## 10. 实际 FPS

`144.mp4` 正式运行610个已处理帧，端到端 `17.326 FPS`。这是 Windows 异步最新帧链路的处理吞吐。

## 11. CPU 占用

进程 CPU 单核等效 `99.998%`。

## 12. NPU 占用

不适用；本轮 `npu_used=false`，不能外推 RK3588 NPU 占用。

## 13. 内存占用

正式运行结束工作集 `440.609 MiB`。

## 14. 正式结果与当前问题

- 610帧产生845个检测、120次轨迹观测和59个有效车牌 crop。
- 59次质量评价中28次通过；Rectifier调用28次，成功28次、失败0次。
- 28次全部使用Perspective，Resize和ResizeFallback均为0；真实视频未触发回退，但独立单测已覆盖。
- Rectifier耗时 mean/P50/P95 为 `0.530/0.494/0.718 ms/call`。
- 质量拒绝为29次尺寸不足、2次综合分不足。
- 目视对照两个真实蓝牌样本，字符方向正确，没有上下颠倒或镜像；近边缘字符留白较紧，后续需结合 OCR A/B 决定是否增加角点外扩。
- 本轮丢弃433个过期源帧，主要瓶颈仍是 PC CPU 模型推理，不是 Rectifier。
- 当前几何依赖 OBB detector 四角点；没有学习式角点网络、STN或双层车牌拆分。
- 固定 `320×96` 适合当前 HyperLPR3 纯识别计划，但其他 OCR 可通过配置或替换实现使用不同尺寸。

## 15. 下一步

只实现独立 `IPlateColorClassifier/HSVPlateColorClassifier`，输入使用矫正后的车牌图，输出 `blue/yellow/green/white/black/other` 与置信度。HSV 模块完成后再接 HyperLPR3 纯识别，不提前实现 PlateFusion 或四路调度。

## 测试

- CTest：7/7通过。
- 合成梯形恢复相对标准牌的平均像素绝对误差为 `4.246`。
- 独立基准中1000次透视拉正平均约 `0.286 ms/call`。
- 正式输出目录：`runs/pc_stage8_plate_rectifier/`。
