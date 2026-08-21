# Stage 9：HSVPlateColorClassifier

日期：2026-08-21

## 验收结论

已实现独立、可替换的 `IPlateColorClassifier/HsvPlateColorClassifier`，只对质量通过且成功矫正的车牌图分类。本阶段不运行 OCR，也不做 PlateFusion。

## 1. 新增文件

- `include/plate/plate_color_classifier.hpp`
- `include/plate/hsv_plate_color_classifier.hpp`
- `src/plate/hsv_plate_color_classifier.cpp`
- `tests/plate_color_classifier_test.cpp`
- `STAGE9_REPORT.md`

## 2. 修改文件

- `CMakeLists.txt`
- `config/config.yaml`
- `include/common/config.hpp`
- `src/common/config.cpp`
- `src/main.cpp`
- `README.md`
- 根目录项目记忆文档

## 3. 模块输入

- 非空 OpenCV BGR `CV_8UC3` 车牌图。
- 正式主链路输入为 `RectifiedPlate.image`，当前固定为 `320×96`；接口本身也支持其他尺寸。

## 4. 模块输出

- `ColorResult`：`color/confidence` 为规范结果，类别是 `blue/yellow/green/white/black/other`。
- `model_color` 保存阈值判定前的最佳候选；`secondary_color/secondary_confidence` 保存第二覆盖类别，便于诊断褪色或过曝样本。
- 当前 `confidence` 是颜色像素覆盖率；输出 `other` 时为 `1 - 最大候选覆盖率`，不是经过真值集校准的概率。

## 5. 使用模型

无深度学习模型。使用 OpenCV BGR→HSV、内区裁剪、色相/饱和度/亮度阈值和覆盖率/优势差判定。

## 6. 模型文件位置

不适用。本模块没有模型文件。

## 7. 模型输入尺寸

无固定模型尺寸。正式输入是 Rectifier 输出的 BGR `320×96`。

## 8. 模型输出格式

C++ `ColorResult`。主类别是字符串，置信度范围 `[0,1]`；详细分类计数和逐 Track 计数写入 `summary.json`。

## 9. 是否使用 RK3588 NPU

否。HSV 属于轻量 OpenCV CPU 算法，后续深度学习颜色分类器可以复用 `IPlateColorClassifier` 接口。

## 10. 实际 FPS

`144.mp4` 正式运行610个已处理帧，端到端 `17.880 FPS`。这是 Windows 异步最新帧链路吞吐，不是 RK3588 性能。

## 11. CPU 占用

进程 CPU 单核等效 `100.002%`。

## 12. NPU 占用

不适用；`npu_used=false`。

## 13. 内存占用

正式运行结束工作集 `449.234 MiB`。

## 14. 正式结果与当前问题

- 610帧产生866个检测、149次轨迹观测、80个车牌crop；42个质量通过并全部成功透视矫正。
- 颜色分类调用42次：`blue=37`、`white=3`、`other=2`，0次异常。
- 逐Track结果：ID1为28蓝/2白/1其他，ID2为1蓝，ID3为8蓝/1白/1其他。
- 分类自身 mean/P50/P95 为 `0.091/0.086/0.123 ms/call`；独立1000次合成蓝牌基准约 `0.104 ms/call`。
- CTest 8/8通过；合成测试覆盖蓝、黄、绿、白、黑、红色other、白字符干扰、边缘干扰、模糊类别和错误输入。
- Stage 8历史28张真实矫正牌独立复测为27蓝、1其他。正式运行的3白/2其他样本目视严重模糊或低饱和，缺少人工真值，不能据此声明识别正确或错误。
- 当前真实视频只确认蓝牌场景；黄牌、新能源绿牌、白牌、黑牌真实覆盖均待确认。
- 本轮丢弃396个过期源帧；主要瓶颈仍是PC CPU模型推理，HSV不是瓶颈。
- 单帧HSV会受过曝、低饱和、强反光影响；后续 PlateFusion 应按 Track ID 多帧融合，但本阶段没有提前实现。

## 15. 下一步

只实现独立 `IPlateRecognizer` 和 HyperLPR3 纯识别后端，输入使用矫正后的 `320×96` BGR 车牌图，输出真实中文车牌文本和置信度。先完成单图与历史crop A/B，再接主链路；不要提前实现 PlateFusion、四路调度或把格式合法当成识别正确。

## 输出

- `runs/pc_stage9_plate_color/annotated.mp4`
- `runs/pc_stage9_plate_color/summary.json`
- `runs/pc_stage9_plate_color/rectified_plates/`
