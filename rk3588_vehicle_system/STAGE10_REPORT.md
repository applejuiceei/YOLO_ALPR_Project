# PC Stage 10：HyperLPR3 纯车牌识别

日期：2026-08-21

## 结论

已完成独立 `IPlateRecognizer` 和 `HyperLpr3OnnxPlateRecognizer`，并接入单路 C++ 主链。模块只消费质量通过、透视矫正后的车牌图，输出真实 UTF-8 中文车牌候选、置信度、格式校验、接收状态和拒绝原因。当前没有 PlateFusion，不把任一单帧结果当作最终车牌。

## 1. 新增文件

- `include/plate/plate_recognizer.hpp`
- `include/plate/hyperlpr3_onnx_plate_recognizer.hpp`
- `src/plate/hyperlpr3_onnx_plate_recognizer.cpp`
- `tests/plate_recognizer_test.cpp`
- `models/plate_recognizer/rpv3_mdict_160_r3.onnx`（本地模型，不纳入源码发布）
- `STAGE10_REPORT.md`

## 2. 修改文件

- `CMakeLists.txt`
- `config/config.yaml`
- `include/common/types.hpp`
- `include/common/config.hpp`
- `src/common/config.cpp`
- `src/main.cpp`
- `README.md`
- 项目根目录的 `PROJECT.md`、`STATUS.md`、`DECISIONS.md`、`HANDOFF.md`

未修改 Windows Python 基准主线 `alpr_topk_capture.py`。

## 3. 模块输入

- `cv::Mat` BGR 车牌图。
- 主链实际输入为 `OpenCvPlateRectifier` 输出的 `320×96` BGR 图。
- 识别器内部按官方协议等比例缩放并补零到 `160×48`。

## 4. 模块输出

```cpp
struct PlateOCRResult {
    std::string text;
    float confidence;
    bool format_valid;
    bool accepted;
    std::string rejection_reason;
};
```

每次实际调用还输出预处理、ONNX 推理、CTC 解码耗时。主程序把完整 UTF-8 中文结果逐行写入 `recognition_results.jsonl`；拒绝结果也保留，不会伪装成成功。

## 5. 使用模型

- HyperLPR3 0.1.3 自带纯识别模型 `rpv3_mdict_160_r3.onnx`。
- SHA256：`8FB08B5DB2ADECCF43B05006BBBF409E4659D08D72E46A62631C00FF751EAEB3`。
- 文件大小：10,258,843 bytes。
- 本地包元数据许可：Apache-2.0。

## 6. 模型位置

`models/plate_recognizer/rpv3_mdict_160_r3.onnx`

## 7. 模型输入尺寸

- 名称：`data`
- 类型：float32
- 形状：`1×3×48×160`
- 颜色：BGR；与 HyperLPR3 0.1.3 `PPRCNNRecognitionORT` 源码保持一致。
- 归一化：`(value - 127.5) / 127.5`，CHW，右侧零填充。

## 8. 模型输出格式

- 名称：`output`
- 类型：float32
- 形状：`1×20×78`
- 解码：逐时间步 argmax，CTC blank 为索引 0，折叠连续重复，置信度为保留字符最大概率均值。
- 官方字符表包含 blank 在内共 77 项，而该模型输出 78 类。额外索引 77 不臆造字符；若命中则以 `unknown_token` 拒绝。项目现有 78 张历史 crop 检查中未命中索引 77。

## 9. 是否使用 RK3588 NPU

否。当前为 Windows ONNX Runtime CPU 验证，`npu_used=false`。不能把本轮性能外推为 RK3588 NPU 性能。

## 10. 实际 FPS

- `144.mp4`、610 个已处理帧：15.382 FPS。
- 输出视频：1920×1080、610 帧，可正常重新打开。
- Frame Queue 丢弃 567 个过期源帧；这是 PC CPU 单路未跟上输入的结果。

## 11. CPU 占用

进程 CPU 单核等效：100.000%。该口径不是整机总 CPU 百分比。

## 12. NPU 占用

不适用；PC 本轮未使用 NPU。

## 13. 内存占用

结束时工作集：455.980 MiB。

OCR 自身 20 次调用：

- 推理 mean/P50/P95：18.258/17.043/24.439 ms。
- 总耗时 mean/P95：18.370/24.536 ms。
- 预处理 mean：0.092 ms；解码 mean：0.021 ms。

## 14. 当前问题

- 20 次 OCR 全部产生非空文本，13 次通过格式和 0.50 置信度门槛，7 次因格式拒绝。
- Track 1 的合法单帧候选包括 `京JC5210`、`冀JC5218`、`冀JC521Q`、`粤JC521G`、`鲁CC5210`；Track 4 包括 `冀B6R9F9`、`黑B6R9F9`、`辽D6R9F9`、`鲁H6R5F3`。这证明格式合法或高置信度不等于识别正确。
- 当前没有逐 Track OCR/颜色多帧融合，不能输出最终号码。
- OpenCV 默认 Hershey 字体不能绘制中文省份字符，视频标签暂显示 `CN:` 加 ASCII 部分；JSONL 和终端保留完整中文。
- ONNX Runtime 会报告该旧模型把部分 initializer 暴露为 graph input 的优化警告；不影响本轮正确执行，但转换 RKNN 前应检查并清理。
- 新能源 8 位牌的格式接口已支持，实际准确率待有真值样本验证。

## 15. 下一步

只实现独立 `IPlateFusion`：按 `track_id` 保存质量分、OCR 置信度、文本和车牌颜色，以 Top-K 清晰度筛选和加权字符串投票形成稳定结果；同时保留全部原始候选与投票历史。PlateFusion 验收前不扩展四路，也不把单帧候选写成最终 `VehicleEvent`。

## 验证

- CMake 构建成功。
- CTest：9/9 通过。
- Python 官方参考样本 `grab10003.jpg`：`苏E803JV 0.999943`。
- C++ 同图：`苏E803JV 0.999943`，逐字和置信度一致。
- 正式输出：`runs/pc_stage10_plate_recognizer/`。

