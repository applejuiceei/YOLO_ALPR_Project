# Stage 11：PlateFusion 与中文车牌叠加

日期：2026-08-21

## 结论

Stage 11 已完成。主链路现在按 `track_id` 保存车牌号码和颜色观察，未稳定时显示最新一次有效单帧结果，达到门槛后自动切换为融合结果。Windows 视频标签已通过 GDI 使用系统微软雅黑绘制完整中文，不再使用 `CN:`、问号或 OpenCV 不支持中文的默认字体。

正式验收仍是 Windows ONNX Runtime CPU 模拟，不是 RK3588 NPU 结果。`144.mp4` 共处理 610 帧，CTest 11/11 通过。

## 1. 新增文件

- `include/fusion/plate_fusion.hpp`
- `include/fusion/confidence_weighted_plate_fusion.hpp`
- `src/fusion/confidence_weighted_plate_fusion.cpp`
- `include/common/utf8_text_renderer.hpp`
- `src/common/utf8_text_renderer.cpp`
- `tests/plate_fusion_test.cpp`
- `tests/utf8_text_renderer_test.cpp`
- `STAGE11_REPORT.md`

## 2. 修改文件

- `CMakeLists.txt`
- `config/config.yaml`
- `include/common/config.hpp`
- `include/common/types.hpp`
- `src/common/config.cpp`
- `src/main.cpp`
- `README.md`
- 项目根目录的 `PROJECT.md`、`STATUS.md`、`DECISIONS.md`、`HANDOFF.md`

Windows Python 基准主线 `alpr_topk_capture.py` 未修改。

## 3. 模块输入

`ConfidenceWeightedPlateFusion` 的输入为 Camera 本地的 `track_id` 和 `PlateFusionObservation`：

- `frame_id`
- 质量评价结果和 `quality_score`
- 原始 `PlateOCRResult`
- 可选的单帧车牌颜色 `ColorResult`

只有质量通过的车牌进入该模块。OCR 格式或置信度不合格时不进入号码投票，但原始观察仍写入 `recognition_results.jsonl`；颜色按独立门槛继续融合。

## 4. 模块输出

`PlateFusionResult` 输出：

- 最新一次有效单帧号码 `latest_ocr`
- 当前加权获胜号码 `fused_ocr`
- 融合车牌颜色
- 号码/颜色样本数
- 获胜次数和投票权重占比
- `stable` 状态

业务显示规则固定为：未稳定显示 `车牌(单帧)` 和 `latest_ocr`；稳定后显示 `车牌` 和 `fused_ocr`。PlateFusion 只从真实出现过的完整字符串中选择，不按字符拼造未出现过的号码。

## 5. 使用模型

本阶段没有新增 AI 模型。OCR 继续使用 HyperLPR3 纯识别模型：

- 文件：`models/plate_recognizer/rpv3_mdict_160_r3.onnx`
- 输入：BGR float32 NCHW `1×3×48×160`
- 输出：float32 `1×20×78`
- 解码：HyperLPR3 官方 CTC blank/去重和字符表协议

车牌颜色继续使用 OpenCV HSV，不使用深度学习模型。PlateFusion 和文字渲染均为 CPU 模块。

## 6. 融合策略

- 每路 Camera 使用独立实例，并在实例内部按 `track_id` 隔离。
- 每个 Track 最多保存 30 个历史样本，只从质量最高的 10 个样本投票。
- 号码权重：`quality_score × OCR confidence`。
- 默认稳定门槛：至少 3 个有效号码样本、获胜号码至少出现 2 次、获胜权重占比至少 0.50。
- 颜色权重：`quality_score × color confidence`，默认排除 `other`。
- 同一 Track 同一帧的多个候选分别只保留号码和颜色权重最高者。
- 默认超过 60 个源帧未更新的 Track 会被清理；支持 `reset()`。

## 7. 中文渲染

- 业务层只依赖 `IUtf8TextRenderer`。
- Windows 后端使用严格 UTF-8→UTF-16 转换、Windows GDI 和系统 `Microsoft YaHei`。
- 仅生成并转换标签大小的 BGRA/BGR 小图，不对整张 1080P 图像做额外颜色转换。
- 启动时把 Windows 控制台输入、输出代码页设置为 UTF-8。
- JSONL 原样保存 UTF-8。
- Linux/RK3588 后续实现 FreeType 后端，不需要修改业务层。

全分辨率验收帧 `runs/pc_stage11_plate_fusion/stage11_frame_88.jpg` 中，车辆框上方第二行正确显示 `车牌(单帧): 京JC5210 0.84 blue`；“车牌”“单帧”和省份字符均无乱码。原车牌小框不再重复绘制 OCR，只保留质量和颜色诊断。

## 8. 独立测试

`plate_fusion_test` 覆盖：

- 正确号码压过一次字符误识别
- 质量分和 OCR 置信度共同影响权重
- 非法/低置信度 OCR 不参与号码投票
- Top-K、同帧去重、历史滚动、过期清理和 Track 隔离
- 车牌颜色独立融合并排除 `other`
- 未稳定使用最新单帧、稳定后切换融合结果

`utf8_text_renderer_test` 覆盖 `京A12345`、`豫JC521G` 的 UTF-16 码点检查、非法 UTF-8 拒绝和 Windows GDI 图像绘制。完整清理构建后 CTest 为 11/11 通过。

## 9. 610 帧正式结果

输出目录：`runs/pc_stage11_plate_fusion/`

- `annotated.mp4`：610 帧标注视频
- `summary.json`：汇总与性能
- `recognition_results.jsonl`：22 条原始 OCR 观察，全部可按 UTF-8 JSON 解析
- `plate_fusion_results.jsonl`：22 条融合更新历史，全部可按 UTF-8 JSON 解析
- 车辆、车牌和矫正 ROI 诊断目录

主要数据：

- 处理速度：12.623 FPS
- CPU：单核等效 100.001%
- 工作集内存：459.789 MiB
- NPU：未使用，NPU 占用不适用
- 车牌检测：47 个
- 质量通过：22/47
- OCR：22 次，11 次通过格式和 0.50 置信度门槛
- PlateFusion 更新：22 次
- PlateFusion 更新耗时：mean 0.009 ms，P95 0.013 ms
- 本轮稳定 Track：0 个

本轮没有稳定 Track 是预期门槛行为，不是融合未运行：Track 1 的 7 个有效号码各不相同；Track 3 的 `冀B6R9F9` 只出现 2 次，尚未达到至少 3 个有效样本；同车进入 Track 4 后不会违规跨 Track 合并。最新有效单帧号码已经分别保存在 Track 1、3、4 中并显示于视频。

## 10. 当前问题

- HyperLPR3 仍会输出格式合法但内容错误的号码，例如 Track 1 出现多个省份/字符组合；融合只能降低偶发抖动，不能把多数一致的错误自动纠正为真值。
- 当前 ByteTrack 在高速接近、CPU 丢帧时会断 Track，同一车辆的观察因此不能跨 ID 融合。
- 610 帧运行丢弃 823 个过期队列帧；这是 PC CPU 实时追帧策略的结果，不代表 RK3588 NPU 性能。
- 本轮自然视频没有达到稳定门槛，因此视频中只出现 `车牌(单帧)` 标签；稳定切换已由确定性单元测试验证。
- 当前真实视频只覆盖蓝牌，其他牌色真实准确率仍待确认。

## 11. 下一步

下一阶段建议生成统一 `VehicleEvent` JSON，把 Camera、Lane、Track、车辆类型/融合颜色、车牌稳定状态/号码/颜色和时间戳汇入标准输出；保持原始 OCR 与融合历史作为诊断旁路。完成单路事件验收后，再开始 RKNN 后端和板端视频文件验证。
