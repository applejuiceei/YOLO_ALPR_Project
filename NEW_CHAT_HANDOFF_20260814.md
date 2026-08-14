# 新对话完整交接文档：YOLO + 车牌 OBB + HyperLPR3 / PP-OCRv4 + RK3588

更新时间：2026-08-14（Asia/Shanghai）  
项目根目录：`D:\YOLO_ALPR_Project`  
当前 Git 分支：`main`  
本文用途：新开对话时的一站式项目接手入口

> 本文综合了当前工作区源码、项目记忆文件、已有运行结果和本轮对话。它同时覆盖 Windows 原速纯识别、HyperLPR3 性能分析、PP-OCRv4 训练准备，以及 RK3588 + SC850SL 真实道路部署。
>
> 本文不包含任何仓库密码、登录密码或其他凭据。新对话中也不得把凭据写入代码、文档、日志或 Git 历史。

---

## 0. 新对话如何使用本文

### 0.1 必读顺序

新对话开始后，建议按以下顺序阅读：

1. `AGENTS.md`：协作规则、红线和长期约束。
2. `NEW_CHAT_HANDOFF_20260814.md`：本文，当前全局接手入口。
3. 与当前任务直接相关的源码：
   - Windows 原速纯识别：`alpr_realtime_async.py`、`alpr_topk_capture_demo.py`、`hyperlpr3_ocr.py`。
   - HyperLPR3 性能：三个 `benchmark_hyperlpr3_*.py` 和 `hyperlpr3_recognize_once.py`。
   - PP-OCR：`ppocr_plate/README.md` 及该目录源码。
   - RK/SC850SL：`NEW_CHAT_HANDOFF_20260717.md`、`rk3588_topk_capture_mipi_debug_sc850.py`、`rk3588_topk_capture_mipi_debug_sc850_postfocus.py` 和 `RK3588_dev/run_sc850_*.sh`。
4. `PROJECT.md`、`STATUS.md`、`DECISIONS.md`、`HANDOFF.md`：了解长期目标和决策演进。
5. `PROJECT_HANDOFF.md`、`NEW_CHAT_HANDOFF_20260708.md`、`NEW_CHAT_HANDOFF_20260710.md`：仅在追溯早期历史时阅读。

### 0.2 状态冲突时的优先级

遇到文档之间结论冲突时，按以下优先级判断：

1. 用户在新对话中的最新明确指令。
2. 当前源码和实际运行产物。
3. 本文。
4. `NEW_CHAT_HANDOFF_20260717.md` 中的 RK/SC850SL 专项结论。
5. `PROJECT.md`、`STATUS.md`、`DECISIONS.md`、`HANDOFF.md`。
6. 更早历史交接文档。

### 0.3 事实标记约定

- **已验证**：有源码、JSON、日志、图片或运行目录作为证据。
- **当前实现**：当前工作区代码已经具备，但不代表完成全部场景验收。
- **历史结果**：当时有效，当前机器负载、摄像头状态或代码版本可能不同。
- **待确认**：没有足够证据，不得自行补全。
- **建议**：下一步方案，不代表已经执行。

---

## 1. 最短接手结论

项目有两个层级不同、但互相关联的目标：

1. **当前 Windows 直接任务**：让 `测试图\14.mp4` 按源视频 24 FPS 原速播放，后台只对车辆 YOLO + 车牌 OBB 得到的透视车牌调用 HyperLPR3 纯识别模型；不运行 HyperLPR3 自带检测器和颜色分类器，不识别车辆截图，每次 OCR 都保存到 JSONL。
2. **长期产品目标**：在 RK3588 + SC850SL `/dev/video71` 4K NV12 真实道路画面上完成车辆检测、车牌 OBB、OCR、多帧确认和证据保存，并提高高速车辆的识别覆盖率。

截至本文创建时：

- Windows 异步纯识别已经达到源视频原速：610 帧实测 `24.029 FPS`，用户后续 2502 帧 GUI 实跑为 `24.001 FPS`。
- 原速不是“每一帧都完成识别”，而是播放线程按时间轴运行、后台只保留最新帧，过期推理帧会主动覆盖。
- HyperLPR3 纯识别在 1041 张预裁车牌上的稳定性能为 `P50=26.034 ms`、`P95=43.254 ms`；瓶颈是 ONNX 推理，不是预处理或 CTC 解码。
- 单张预热后曾测到 `17.735 ms`，但单次值不能替代 P50/P95。
- `alpr_topk_capture_demo.py` 已接入 `hyperlpr3-rec`，逐次 OCR 记录、同车投票、JSONL 和 FPS HUD 均已实现。
- 车牌专用 PP-OCRv4 Mobile **尚未正式训练**；只完成 100 步 CPU 结构冒烟和 Paddle 固定形状导出验证。
- SC850SL `/dev/video71` 已经证明能独占输出 3840×2160 NV12 约 30 FPS；旧文档中“当前 sensor 未上线、video71 不能出帧”已经过时。
- RK 真实道路流已经产生过多批锁定证据；历史 balanced 处理约 `4.17 FPS`，7 月 30 日长跑最高有 `19387` 帧、约 `4.208 FPS` 的证据。
- Gitea `PLR-Test` 远端是 2026-08-06 的轻量快照，早于 8 月 12 日纯识别改造；不能把远端当作本地最新版本。

---

## 2. 项目目标与验收边界

### 2.1 长期产品目标：RK3588 真实道路 ALPR

目标流程：

```text
SC850SL /dev/video71 4K NV12
  -> 道路/车辆 ROI
  -> RKNN 车辆检测
  -> 车辆区域内 RKNN 车牌 OBB
  -> 透视裁正车牌
  -> HyperLPR3 OCR
  -> 格式校验 + 置信度 + 多帧一致性
  -> Top-K / rejected / vote history / lock evidence
  -> /tmp/frame.jpg 或其他浏览器预览
```

当前板端优先级是：

1. 有效识别率和错误控制。
2. 连续稳定运行。
3. 处理速度和预览响应。
4. 长期跟踪、预测和复杂重关联。

复杂追踪已经被弱化。板端只需保留足够完成短期同车多帧确认的状态，不再把长时间预测跟随作为当前第一验收指标。

### 2.2 当前 Windows 阶段目标：原速播放 + 纯识别

固定链路：

```text
源视频按自身 FPS 播放
  -> 后台最新帧
  -> 车辆 YOLO（只定位）
  -> 车牌 OBB（只定位和四点）
  -> 320×96 透视车牌
  -> HyperLPR3 PPRCNNRecognitionORT
  -> 格式/0.5置信度过滤
  -> track_id 多帧投票
  -> 终端 + recognition_results.jsonl
```

明确不做：

- 不调用 HyperLPR3 自带车牌检测器。
- 不调用 HyperLPR3 颜色分类器。
- 不把车辆 crop 或整帧送入纯识别器。
- 不把“源视频 24 FPS”伪装成 30 FPS。
- 不要求后台逐帧处理完所有源帧后才显示下一帧。
- 不把格式合法率、高置信度或输出率称为准确率。

### 2.3 OCR 模型研究目标

当前正式 OCR 仍是 HyperLPR3。PP-OCRv4 Mobile 是独立研究线，只有同时通过以下门槛才允许接入实时程序：

- 人工核验实拍整牌准确率 `>=98%`。
- 字符准确率 `>=99.5%`。
- INT8 相对 FP32 整牌准确率下降 `<=0.5` 个百分点。
- Windows CPU 和 RK3588 均在预热后 1000 次、batch=1、单并发、端到端 OCR `P95<20 ms`。

---

## 3. 当前已实现的功能

### 3.1 Windows 基准主线 `alpr_topk_capture.py`

已实现：

- YOLO 车辆检测。
- 车辆 track 管理。
- 车辆区域内车牌 OBB。
- 四点透视裁正，生成约 `320×96` 车牌图。
- 每辆车 Top-K 候选排序和保存。
- HyperLPR3 完整接口 OCR。
- 格式校验、OCR 置信度、多帧投票和锁定。
- 锁定后跳过该 track 的部分 OBB/OCR 工作。
- `run_summary.json`、`track_*/summary.json`、accepted/rejected 图片和 vote history。

这是 Windows 行为基准，长期规则是不要随意修改。

### 3.2 Windows 实验线 `alpr_topk_capture_demo.py`

当前已经实现：

- 保留原完整 `hyperlpr3` 引擎。
- 新增 `hyperlpr3-rec` 纯识别引擎。
- `hyperlpr3-rec` 固定 `use_vehicle_first=False`，只识别 OBB 拉正后的 plate crop。
- 新增 `--show-ocr-timing`，终端逐次输出帧号、track、来源、文字、置信度、OCR 毫秒、格式/置信度和投票状态。
- 每一次 OCR 调用都先进入 run 级内存事件列表；空文本、非法格式、低置信度和异常也不会被静默丢弃。
- 退出时总是创建 `recognition_results.jsonl`，并在 `run_summary.json` 中写入调用数、完成数、错误数、mean/P50/P95/min/max。
- `track_id` 用于判断是否属于同一辆车。
- 格式非法或低于阈值的结果仍写 JSONL，但不会进入投票。
- 支持同车投票与锁定。
- 支持原始和 deblur 分支分别记录 OCR 事件；当前纯识别基线不建议启用 deblur。
- 左上角显示滑动窗口实际处理 FPS 和源 FPS。

### 3.3 原速异步线 `alpr_realtime_async.py`

当前代码已收紧为纯识别专用模式：

- 参数校验要求 `--ocr-engine hyperlpr3-rec`。
- 要求 `--pipeline vehicle`、车牌 OBB 开启、IoU tracking 开启。
- CLI 中 `--plate-stage` 的默认值仍是 `fallback`；由于 pure-rec 不执行 vehicle-crop OCR，该模式下 `fallback` 的实际执行效果等价于 `always`。推荐命令显式写 `--plate-stage always`，便于表达意图。
- 主线程按源视频 FPS 显示。
- `LatestFrameBuffer` 是单槽最新帧缓冲；后台忙时，新帧覆盖尚未开始的旧帧。
- 后台车辆 YOLO 和车牌 OBB 只负责产生透视 plate crop。
- HyperLPR3 只加载一次纯识别模型，默认预热 20 次。
- OCR 输入实际为 `(96, 320, 3)` OpenCV BGR 透视图，官方内部再处理为 `[1,3,48,160]`。
- 每次 OCR 都生成事件并通过结果队列写入 JSONL。
- 结果队列不主动丢 OCR 事件。
- Worker 按 track 维护投票状态；锁定 track 可跳过后续重工作。
- `R` 开启/暂停后台识别，视频继续原速播放。
- `Q/Esc` 等待正在执行的工作结束、drain 结果后保存退出。
- 左上角显示 `FPS/SRC`、frame、OCR 调用数、`INFER` 和 `DROP`。
- 不在视频中显示车牌文字；结果看终端和 JSONL。

### 3.4 OCR 适配层 `hyperlpr3_ocr.py`

包含两个明确分开的类：

1. `HyperLPR3OCR`
   - 包装完整 `hyperlpr3.LicensePlateCatcher`。
   - 内部包含 HyperLPR3 检测、裁正、识别和条件颜色分类。

2. `HyperLPR3RecognitionOCR`
   - 从 HyperLPR3 配置动态解析 `rpv3_mdict_160_r3.onnx` 路径，不硬编码用户目录。
   - 直接创建官方内部 `PPRCNNRecognitionORT(input_size=(48,160))`。
   - 复用官方预处理、ONNX 推理和 CTC 解码，不自行改写协议。
   - 严格检查输入必须是非空 HWC 三通道 NumPy 图像。
   - `last_ocr_ms` 只包围官方识别器调用，不含 YOLO、OBB、透视、打印、投票或磁盘。
   - 返回清洗后的文字和有限置信度。

### 3.5 HyperLPR3 性能工具

已完成四个入口：

- `benchmark_hyperlpr3_recognition.py`：18 组 Top-K 车辆/车牌三路 A/B。
- `benchmark_hyperlpr3_image_dir.py`：普通预裁车牌目录的完整接口与纯识别批量基准。
- `benchmark_hyperlpr3_full_stages.py`：完整接口检测、透视、OCR、分类和杂项的无侵入分阶段插桩。
- `hyperlpr3_recognize_once.py`：用户手动运行单张纯识别并查看各阶段耗时。

### 3.6 PP-OCRv4 Mobile 独立工作区

`ppocr_plate` 已经具备：

- 固定 76 字符字典和 CTC blank 契约。
- 合成车牌生成和增强。
- manifest、SHA256、字符覆盖、许可证、同车/同视频 group 泄漏审计。
- `real_verified` 数据硬门槛。
- PP-OCRv4 Mobile 训练、smoke、checkpoint 和 Paddle 导出入口。
- Paddle -> ONNX 转换与真实 crop parity 验证设计。
- ONNX Runtime benchmark。
- OpenVINO FP32 转换、INT8 校准和 benchmark。
- RKNN FP16/INT8 转换与板端 benchmark。
- 跨后端文本一致性与量化精度下降比较。

但当前只有结构冒烟，不是正式训练完成。

### 3.7 RK3588 + SC850SL

板端代码已经覆盖：

- RKNN 车辆模型和车牌 OBB 模型。
- 视频文件与 MIPI 输入。
- NV12、UYVY、RAW10 灰度解码。
- `/dev/video71` 4K NV12。
- detect ROI、process ROI、ROI tiles。
- 车辆尺寸/面积/置信度门控。
- HyperLPR3 或旧 RKNN OCR。
- 严格中国车牌格式、投票、锁定、Top-K、rejected 和 lock evidence。
- `/tmp/frame.jpg` 浏览器预览。
- balanced/quality、后聚焦、4K accuracy、traffic corridor、异步预览和保守 re-association 等实验启动配置。

---

## 4. 本轮对话完整工作历程

以下按技术演进顺序总结本轮对话做过的工作：

1. 运行和观察 `alpr_topk_capture_demo` 实时画面，并确认用户可按 `Q` 退出。
2. 将目标从“强行 30 FPS”修正为“以源文件自身 FPS 为基准原速播放”；`14.mp4` 实际是 24 FPS。
3. 讨论识别阶段对帧率的影响，保留后台结果，不要求把识别文字画进视频。
4. 修复/扩展 summary 和 `recognition_results.jsonl`：不再只剩最终一个结果，而是按调用/有效事件保存，并用 `track_id` 表示同一辆车。
5. 明确“一辆车只有一个最终锁定结果”与“需要保留每一次 OCR 诊断事件”是两个不同层级。
6. 将轻量 Windows 核心代码发布到 Gitea `gcvision_admin/PLR-Test`，不上传模型、视频、结果、RK 包或凭据。
7. 给 HyperLPR3 增加 `ocr_ms`、整帧耗时和端到端耗时统计，并将接受阈值调整为 `0.50`。
8. 分析如何把 OCR 降到 20 ms 内，确认主要瓶颈是模型 ONNX 推理，不是 Python 字符处理。
9. 核对 `plate_rec_sim.onnx`，确认它不是 HyperLPR3 模型，协议和字典也不同。
10. 实现 HyperLPR3 `rpv3_mdict_160_r3.onnx` 纯识别离线 A/B，不改 Windows 基准主线。
11. 讨论是否训练车牌专用 PP-OCRv4 Mobile，并实现完整的独立训练/导出/部署工具包。
12. 定位 PP-OCR 冒烟“卡死”原因：NRTR 辅助编码的 BOS/EOS 需要更长内部序列槽；修正后完成 100 步 CPU 冒烟。
13. 修正合成蓝牌/黄牌 RGB 颜色顺序、字典 76/77 类契约、训练数据硬门槛、OpenVINO/RKNN RGB 契约和量化校准限制。
14. 对 `Dataset/dataset/test/sharp` 的 1041 张纯车牌进行完整 HyperLPR3 与纯识别批量基准。
15. 对完整 HyperLPR3 做分阶段插桩，明确检测、透视、OCR、分类的真实耗时和条件调用关系。
16. 新增单张纯识别脚本，让用户能手动看到模型加载、读图、预处理、ONNX 推理、CTC 解码和总耗时。
17. 在 `alpr_topk_capture_demo.py` 接入 `hyperlpr3-rec`，保证不识别车辆 crop，保留每次 OCR、过滤原因和同车投票。
18. 解释为什么离线图片约 20 多 ms，而视频中曾出现 100 多 ms：测试条件不一致、没有预热、YOLO/ORT/OpenCV 多线程争用、后台 Python 进程和 Windows 调度等待共同造成。
19. 发现历史长时间 Python 进程曾持续占用约一个逻辑核；当时没有足够权限确认命令行，因此没有盲目终止。后续快照已无 Python 进程。
20. 在 demo 左上角增加实时处理 FPS 和源 FPS。
21. 确认同步 demo 即使 OCR 恢复到约 26 ms，整体仍只有约 10 FPS；主要持续开销是每帧车辆 YOLO，其次是触发帧上的 plate OBB。
22. 将原速播放方案转到 `alpr_realtime_async.py`：播放与识别解耦，只处理最新帧，严格限定为 HyperLPR3 纯识别。
23. 补齐异步链路的逐次 JSONL、同车投票、HUD、开关、退出 drain 和识别开关竞态处理。
24. 完成无窗口 610 帧、GUI 48 帧和用户 GUI 2502 帧原速验证。

---

## 5. 关键测试结果

### 5.1 HyperLPR3 清晰车牌目录基准

输入：`Dataset\dataset\test\sharp`  
输出：`runs_hyperlpr3_image_dir\run_20260811_112914`  
条件：1041 张、全部预载、batch=1、单并发、warmup=50、磁盘读取不计时、ORT CPU。

| 指标 | 完整 HyperLPR3 | 纯识别模块 |
|---|---:|---:|
| 成功调用 | 1041/1041 | 1041/1041 |
| 非空输出 | 779（74.83%） | 1041（100%） |
| 格式合法 | 未作为主指标 | 1012（97.21%） |
| 总耗时 P50 | 78.266 ms | 26.034 ms |
| 总耗时 P95 | 210.520 ms | 43.254 ms |
| 总耗时平均 | 94.841 ms | 28.206 ms |
| 总耗时最小 | 8.586 ms | 13.345 ms |
| 总耗时最大 | 469.451 ms | 169.135 ms |

纯识别拆分：

| 阶段 | P50 | P95 |
|---|---:|---:|
| 预处理 | 0.207 ms | 0.299 ms |
| ONNX 推理 | 25.572 ms | 42.778 ms |
| CTC 解码 | 0.222 ms | 0.301 ms |

结论：纯识别比完整接口明显快，但 P50/P95 都没有稳定低于 20 ms；瓶颈几乎完全在 ONNX 推理。

限制：该目录无人工真值。“有输出、格式合法、高置信度、两路一致”都不能称为准确率。完整接口有输出的 779 张中，两路文本一致 722 张；完整接口空的 262 张中，纯识别产生 240 个格式合法串，这只能说明行为差异。

### 5.2 完整 HyperLPR3 分阶段基准

输出：`runs_hyperlpr3_full_stages\run_20260811_114704`

| 阶段 | 调用条件/次数 | P50 | P95 | 平均 |
|---|---|---:|---:|---:|
| 公共完整调用 | 1041 张 | 79.474 | 205.369 | 96.817 ms |
| 检测合计 | 每图必跑 1041 次 | 13.053 | 83.683 | 31.641 ms |
| 透视裁正 | 825 次 | 1.229 | 1.638 | 条件统计 |
| OCR 合计 | 825 次 | 61.531 | 182.872 | 74.336 ms |
| 颜色分类 | 717 次 | 1.715 | 34.982 | 5.556 ms |

平均每张输入的贡献：OCR `60.85%`、检测 `32.68%`、分类 `3.95%`、透视 `1.67%`。

注意：OCR、透视和分类是条件阶段，不能把它们各自的 P50/P95 直接相加。1041 张中 216 张没有检测候选；另有 46 张已经产生候选并执行 OCR，但最终仍没有公开结果。

### 5.3 早期 18 组三路 A/B

输出：`runs_hyperlpr3_recognition_ab\run_20260807_170904`

- 18 组、三路 warmup=20、每样本重复10次、调用错误0。
- 纯识别 `P50=81.616 ms`、`P95=186.169 ms`。
- ONNX 推理 `P50=81.184 ms`，仍是瓶颈。
- `冀B6R9F9` 确认样本可正确输出。
- 合法率 0.6111、与旧 summary 参考一致率 0.1333，但旧 summary 不是人工真值。

该批明显慢于 8 月 11 日清晰目录基准，说明 CPU 负载、线程池、调度和运行环境能造成巨大波动。

### 5.4 单张纯识别

脚本：`hyperlpr3_recognize_once.py`

- 冷调用样例：总 OCR `22.174 ms`，其中推理 `21.643 ms`。
- 预热20次后的单次样例：总 OCR `17.735 ms`，其中推理 `17.410 ms`。
- 文字：`苏E803JV`，置信度 `0.999943`。

这只是单次调度结果；正式性能结论仍以多样本 P50/P95 为准。

### 5.5 同步 demo 纯识别

代表 clean run：`captures_demo_hyperlpr3_rec\run_20260812_154752`

- 19 次 OCR，JSONL 19 行，错误 0。
- 全部 `engine=hyperlpr3-rec`、`source=plate`。
- OCR mean `27.745 ms`、P50 `26.339 ms`、P95 `34.877 ms`、min `25.137 ms`、max `40.341 ms`。
- track 4 在 593/594/595 帧分别出现 `粤B6R9F9`、`冀B6R9F9`、`冀B6R9F9`；三次合法事件并非三次完全相同文本，最终由逐字符加权共识在第595帧锁定 `冀B6R9F9`。

受并发负载污染的历史 run：`captures_demo_hyperlpr3_rec_smoke_final\run_20260812_151825`

- 同样19次，但 P50 `106.428 ms`、P95 `167.481 ms`。
- 当时存在长期后台 Python 进程，故该数字只能作为“资源争用会把 20 多 ms 放大到 100 多 ms”的证据，不能当独占 CPU 基准。

### 5.6 异步原速纯识别

#### 610 帧量化验收

输出：`runs_realtime_async_hyperlpr3_rec_smoke\run_20260812_162454`

| 指标 | 结果 |
|---|---:|
| 源 FPS | 24.000 |
| 理论时间 | 25.417 s |
| 实际时间 | 25.386 s |
| 播放循环 FPS | 24.029 |
| 提交帧 | 610 |
| 后台处理帧 | 340 |
| 覆盖过期帧 | 270 |
| 失败帧 | 0 |
| OCR 调用/JSONL | 4 / 4 |
| 平均 OCR | 32.436 ms |

frame 595 输出 `冀B6R9F9`，置信度 `0.995744`，OCR `42.171 ms`。该异步样本只有一个有效票，因此没有达到三票锁定。

#### GUI 48 帧冒烟

输出：`runs_realtime_async_hyperlpr3_rec_gui_smoke\run_20260812_162947`

- 48 帧耗时 `1.982 s`。
- 播放 `24.223 FPS`。
- 前48帧没有触发 OCR；该测试只验证 GUI 原速和退出逻辑。

#### 用户后续 GUI 2502 帧实跑

输出：`runs_realtime_async_hyperlpr3_rec\run_20260812_163427`

- 2502 帧、`104.247 s`、播放 `24.001 FPS`。
- 后台处理 1754 帧，覆盖 747 个过期帧，失败 0。
- 提交数与“已处理 + 已覆盖”相差1帧，是退出时单槽中最多可能留有一个尚未开始的末帧；不能强制假设 `submitted == processed + replaced`。
- OCR 10 次，平均 `23.971 ms`。
- 4 个格式合法/进入投票的事件：`冀B6R9F9` 两次、`鲁V0JU10` 两次。
- 每车只有两票，当前 `vote_threshold=3`，因此没有锁定。

核心结论：原速播放已实现，但识别覆盖率和投票锁定率必须单独优化，不能把 `DROP` 当成算法已经逐帧处理。

### 5.7 `plate_rec_sim.onnx`

输出：`runs_plate_rec_sim_corrected\run_20260808_094939`

- 它不属于 HyperLPR3。
- 真实输入 `[1,3,48,320]`，输出 `[1,40,6625]`，使用大通用字符表。
- 4线程、warmup50、1000次：总耗时 P50 `47.299 ms`、P95 `79.755 ms`。
- 推理 P50 `45.932 ms`、P95 `75.380 ms`。
- 18 张中仅 1 张通过车牌格式。
- `冀B6R9F9` 被识别为 `WB6R9F9`。

结论：速度和质量都未过门槛，不进入正式链路。

### 5.8 PP-OCRv4 Mobile CPU 冒烟

输出：`runs_ppocr_plate_train\smoke_20260808_092616`

- 100 步，约 17 分08秒。
- `global_step=100`。
- loss 约从 `151.829` 降至 `101.462`。
- 保存 `latest.pdparams` 等 checkpoint。
- Paddle predictor 输入 `(1,3,48,160)`、输出 `(1,20,77)`，数值有限。

限制：从随机初始化开始，只证明数据、前后向、checkpoint 和导出结构可运行；输出 `CHN` 没有识别质量意义。正式数据门槛、官方预训练权重和 GPU 都尚未具备。

### 5.9 RK3588 / SC850SL 历史证据

已验证事实：

- 本地 IMX585 板和远程 SC850SL 板都能跑内置 `/root/deploy/144.mp4`。
- `/dev/video71` 是 SC850SL 对应的 `rkisp1-vir1 mainpath`。
- 独占时能连续抓取 3840×2160 NV12 约 30 FPS，每帧 12,441,600 bytes。
- 真实道路流已经走通过车辆、OBB、HyperLPR3、锁定和证据保存。

历史真实道路运行：

| 运行 | processed frames | FPS | 关键结果 |
|---|---:|---:|---|
| 第一批反馈 | 1098 | 2.45 | 锁定过 `苏E51PK6` |
| 批量反馈 | 2155 | 2.35 | 保存20组锁定证据 |
| 去重长跑 | 3392 | 2.46 | 21个已发出锁定事件，抑制2次重复 |
| balanced短测 | 约208 | 正常段约4.17 | 相比2.46 FPS提升约70% |

7月30日 `RK3588_dev\board_inspection_20260729`：

- 同一 lane ROI 对焦前平均清晰度 `371.277`，对焦后 `774.515`，约提升 `2.09×`。
- `run_summary_19387.json`：19387 帧 / 4607.246 s = `4.208 FPS`；plate attempts 6662、OBB 2230、OCR/accepted 915，但最终无锁定，说明“有很多 OCR 调用”不等于投票闭环成功。
- `run_summary_4k_accuracy_5563.json`：5563 帧、`3.643 FPS`、无锁定。
- postfocus 1452 帧：`3.608 FPS`、无锁定。
- traffic corridor 1200 帧：`2.889 FPS`、无锁定。
- `postfocus_reassoc_async_short300`：300 帧、`4.338 FPS`、2 次 lock event，文字为 `苏UL8971` 和 `苏E17L3Q`。

上述两个锁定没有人工真值，且投票包含 `source=vehicle` 的 HyperLPR pre-OCR，不能把它当作 8 月12日严格 plate-only 纯识别准确率。

---

## 6. 为什么离线 20 多 ms，视频里曾变成 100 多 ms

已经确认的事实：

1. `ocr_ms` 没有把车辆 YOLO、plate OBB、透视和磁盘读取算进去。
2. HyperLPR3 识别器无论输入原图是 350×150 还是 320×96，内部都会归一化到固定 `[1,3,48,160]`，图像内容不会改变模型计算图规模。
3. 离线基准预热50次、连续单并发、图片预载、CPU相对空闲。
4. 同步视频没有 OCR 预热时，OCR 紧跟在 PyTorch YOLO 和 OpenCV 工作之后运行。
5. 当时 PyTorch 默认12线程、OpenCV 16线程、ORT线程为自动配置，多个线程池会争抢16个逻辑处理器、缓存和内存带宽。
6. 历史 PID 36352 的 `alpr_env` Python 进程曾持续吃满约一个逻辑核，进一步污染了毫秒基准。
7. clean video run 已恢复到 P50约26ms，证明“视频 crop 本身让模型固定变慢”不是主因。

因此正确结论是：

- 20多 ms 是预热、相对空闲、稳定条件下的典型中位数。
- 100多 ms 是 CPU竞争、线程过量、调度等待和未预热造成的现场尾延迟。
- 稳定结论应报告 P50/P95，而不是只报告一次最快或最慢值。

---

## 7. 当前文件结构

项目包含第三方源码、虚拟环境、数据集、模型和大量生成运行目录，无法也没有必要逐列 `.venv`、Ultralytics、PaddleOCR 或每个 `run_*` 中的每张图片。下面覆盖全部关键业务文件、当前主线文件和独立训练包；依赖与批量生成物按类别说明。

```text
D:\YOLO_ALPR_Project
├─ 项目记忆与交接
│  ├─ AGENTS.md
│  ├─ PROJECT.md
│  ├─ STATUS.md
│  ├─ DECISIONS.md
│  ├─ HANDOFF.md
│  ├─ PROJECT_HANDOFF.md
│  ├─ NEW_CHAT_HANDOFF_20260708.md
│  ├─ NEW_CHAT_HANDOFF_20260710.md
│  ├─ NEW_CHAT_HANDOFF_20260717.md
│  └─ NEW_CHAT_HANDOFF_20260814.md
├─ Windows 核心
│  ├─ alpr_topk_capture.py
│  ├─ alpr_topk_capture_demo.py
│  ├─ alpr_realtime_async.py
│  ├─ hyperlpr3_ocr.py
│  └─ plate_rec_ocr.py
├─ HyperLPR3 性能工具
│  ├─ benchmark_hyperlpr3_recognition.py
│  ├─ benchmark_hyperlpr3_image_dir.py
│  ├─ benchmark_hyperlpr3_full_stages.py
│  └─ hyperlpr3_recognize_once.py
├─ PP-OCRv4 Mobile
│  └─ ppocr_plate\...
├─ RK3588 主线与实验
│  ├─ rk3588_topk_capture.py
│  ├─ rk3588_topk_capture_mipi_debug.py
│  ├─ rk3588_topk_capture_mipi_debug_sc850.py
│  ├─ rk3588_topk_capture_mipi_debug_sc850_postfocus.py
│  ├─ mipi_current_frame_probe.py
│  ├─ rk3588_mipi_isp_probe.py
│  ├─ RK3588\...
│  └─ RK3588_dev\...
├─ 模型、数据和训练
│  ├─ yolo11n.pt / yolov8n.pt
│  ├─ best_obb*.pt
│  ├─ Dataset\...
│  ├─ blur models\...
│  └─ 去模糊与OBB训练脚本
├─ 结果
│  ├─ captures*
│  ├─ runs_hyperlpr3*
│  ├─ runs_realtime_async*
│  ├─ runs_plate_rec_sim_corrected
│  └─ runs_ppocr_plate_train
├─ 轻量发布副本
│  └─ _publish\PLR-Test
├─ 第三方/环境
│  ├─ third_party\PaddleOCR
│  ├─ python_deps / python_deps_ocr
│  ├─ Ultralytics / PaddleCache / .venv
│  └─ LPDGAN
└─ 报告、论文与生成缓存
   ├─ 汇报 / 论文 / tools
   ├─ report_render* / _docx_render*
   └─ __pycache__ / .idea
```

---

## 8. 根目录关键文件逐项作用

### 8.1 项目规则、状态与交接

| 文件 | 作用 |
|---|---|
| `AGENTS.md` | 长期协作规则、阅读顺序和红线。规则有效，但其中“MIPI当前不出帧”是旧状态。 |
| `PROJECT.md` | 长期目标、验收标准和各阶段新增目标。内部保留历史状态，需按日期读。 |
| `STATUS.md` | 已完成、卡点和最近测试结果；包含7月和8月追加内容。 |
| `DECISIONS.md` | 技术决定及原因。旧决定可能已被后续决定取代。 |
| `HANDOFF.md` | 操作命令和阶段接手说明；前部摄像头状态较旧，后部8月纯识别命令较新。 |
| `PROJECT_HANDOFF.md` | 2026-07-03 早期总交接，只用于历史背景。 |
| `PROJECT_HANDOFF_20260626_legacy.md` | 更早历史留档。 |
| `NEW_CHAT_HANDOFF_20260708.md` | 7月8日完整交接。 |
| `NEW_CHAT_HANDOFF_20260710.md` | SC850SL sensor/推流恢复阶段详细历史。 |
| `NEW_CHAT_HANDOFF_20260717.md` | 目前最完整的 RK 真实道路专项交接，含 balanced、真实锁定和 multisense。 |
| `NEW_CHAT_HANDOFF_20260814.md` | 本文，当前全局最新入口。 |
| `REMOTE_CODEX_HANDOFF.md` | 远程 Windows/Codex 文件传输和操作历史。 |
| `AGENTS_0708.md`、`PR0JECT_0708.md`、`STATUS_0708.md`、`DECISIONS_0708.md`、`HANDOFF_0708.md` | 7月8日快照，禁止当当前状态。 |

### 8.2 Windows 当前主线与 OCR

| 文件 | 作用 |
|---|---|
| `alpr_topk_capture.py` | Windows Top-K 行为基准；受保护，不随意修改。 |
| `alpr_topk_capture_demo.py` | Windows 可修改实验线；现含 pure-rec、逐次事件、投票、deblur兼容和FPS HUD。 |
| `alpr_realtime_async.py` | 当前原速播放 + 后台 pure-rec 主入口。 |
| `hyperlpr3_ocr.py` | 完整 HyperLPR3 与纯识别适配器。 |
| `plate_rec_ocr.py` | `plate_rec_sim.onnx` 包装和文字清洗/格式/CTC工具；当前模型不晋级。 |

主要依赖关系：

```text
alpr_realtime_async.py
  -> 复用 alpr_topk_capture_demo.py 的几何、过滤、投票和事件函数
  -> hyperlpr3_ocr.py
  -> plate_rec_ocr.py 的文字清洗和格式工具
```

### 8.3 HyperLPR3 性能和手动入口

| 文件 | 作用 |
|---|---|
| `benchmark_hyperlpr3_recognition.py` | 18组 vehicle/plate 三路离线 A/B。 |
| `benchmark_hyperlpr3_image_dir.py` | 任意预裁车牌目录的完整接口/纯识别批量基准。 |
| `benchmark_hyperlpr3_full_stages.py` | 完整接口分阶段插桩。 |
| `hyperlpr3_recognize_once.py` | 单张车牌纯识别和阶段耗时显示。 |

本机 HyperLPR3 模型实际目录：

```text
D:\Users\Lenovo\.hyperlpr3\20230229\onnx
├─ y5fu_320x_sim.onnx
├─ y5fu_640x_sim.onnx
├─ rpv3_mdict_160_r3.onnx
└─ litemodel_cls_96x_r1.onnx
```

纯识别模型 I/O 已记录为 `[1,3,48,160] -> [1,20,78]`。实时适配器动态解析模型路径，不依赖这个硬编码路径。

### 8.4 早期 ALPR、SAHI、推流和报告脚本

| 文件 | 作用/当前定位 |
|---|---|
| `alpr_sahi_snapshot.py` / `alpr_sahi_snapshot2.py` | 早期 SAHI 切片车辆/车牌快照实验，已被 Top-K 主线取代。 |
| `main.py` | 早期 ALPR/流处理入口，非当前主线。 |
| `api_with_tracking.py` | 早期带追踪 API 实验。 |
| `cascade_stream.py` / `cascade_stream2.py` | 早期级联推流实验。 |
| `test_image.py` / `test_image2.py` | 早期单图检测、透视、增强实验。 |
| `ocr_compare_topk.py` | 对已有 Top-K 候选比较 OCR 引擎。 |
| `topk_report.py` | 将 Top-K run 生成 CSV/HTML/最佳文本汇总。 |
| `alpr_topk_capture_vs_sahi_flowchart.svg` | Top-K 与 SAHI 流程对比图。 |
| `build_alpr_demo_report.py` | 早期 ALPR 演示报告生成。 |
| `build_sc850_progress_report.py` | SC850SL 阶段报告生成。 |
| `tools/build_alpr_stage_report.py` | 项目阶段报告辅助工具。 |

### 8.5 去模糊与 OBB 训练脚本

| 文件 | 作用 |
|---|---|
| `prepare_obb_finetune_dataset.py` | 构建 OBB 微调数据集。 |
| `export_obb_review_pack.py` | 导出 OBB 人工复核包。 |
| `annotate_obb_review.py` | OpenCV 人工检查/修订 OBB 标注。 |
| `train_obb_colab.py` | Colab OBB 训练入口。 |
| `prepare_deblur_dataset.py` | 第一版配对去模糊数据构建。 |
| `prepare_deblur_dataset_v2.py` | 第二版大规模配对、manifest和划分。 |
| `train_deblur_colab.py` | 轻量车牌复原模型训练和导出。 |
| `test_deblur_image.py` | 单图/目录去模糊视觉测试。 |
| `test_deblur_hyperlpr3.py` | 去模糊前后 HyperLPR3 A/B。 |
| `COLAB_DEBLUR_V2_E20_STEPS.md` | deblur Colab 操作说明。 |
| `OBB_FINETUNE_COLAB.md` | OBB 微调说明。 |
| `COLAB_TRAINING_GUIDE.md` | 通用 Colab 训练说明。 |

### 8.6 RK 主脚本

| 文件 | 作用 |
|---|---|
| `rk3588_topk_capture.py` | 通用 RK3588 Python 主线，主要用于内置视频和通用板端策略。 |
| `rk3588_topk_capture_mipi_debug.py` | IMX585/MIPI 调试参考，不直接污染。 |
| `rk3588_topk_capture_mipi_debug_sc850.py` | SC850SL `/dev/video71` 适配实验主副本。 |
| `rk3588_topk_capture_mipi_debug_sc850_postfocus.py` | 较新后聚焦版，加入异步最新帧预览和未锁定证据重关联。 |
| `mipi_current_frame_probe.py` | 对当前 `/tmp/frame.jpg` 或 MIPI 帧做 vehicle/plate/OCR 探测。旧帧风险必须注意。 |
| `rk3588_mipi_isp_probe.py` | MIPI/ISP 节点、格式和单帧诊断。 |

### 8.7 根目录模型和大文件

| 文件 | 作用/状态 |
|---|---|
| `yolo11n.pt` | Windows 默认车辆检测。 |
| `yolov8n.pt` | 旧 YOLO 基线。 |
| `best_obb.pt` | Windows 默认车牌 OBB。 |
| `best_obb_finetuned_e8.pt` / `best_obb_finetuned_e20.pt` | OBB 微调候选；e20 转 RKNN A/B 仍待执行。 |
| `ESPCN_x4.pb` | 早期轻量超分实验。 |
| `RealESRGAN_x4plus.pth` | Real-ESRGAN 超分资产，未进入实时主链。 |
| `LPDGAN.zip` / `LPDGAN` | 外部车牌复原研究代码，未进入当前主线。 |
| `rknn-toolkit2-master.zip` / `rknpu2-master.zip` | RKNN 转换/runtime 源码包，大型离线资产。 |
| `deblur_pair_preview.jpg` | 去模糊配对预览。 |
| `demo_live_*.log`、`obb_dataset_build*.log` | 历史运行日志；空文件不代表当前任务。 |
| 根目录 `.docx` 文件 | 历史代码截图、对话和说明文档，不是运行依赖。 |

---

## 9. `ppocr_plate` 每个文件的作用

| 文件 | 作用 |
|---|---|
| `ppocr_plate/__init__.py` | 包初始化。 |
| `ppocr_plate/README.md` | PP-OCR 专项当前权威入口，含数据、训练、导出和门槛。 |
| `ppocr_plate/plate_chars.txt` | 76 个唯一非 blank 字符；SHA256 已绑定到数据审计。 |
| `ppocr_plate/configs/plate_PP-OCRv4_mobile_rec.yml` | SVTR_LCNet/CTC训练配置，输入48×160。 |
| `ppocr_plate/dataset.py` | manifest、解码、字符、SHA256、许可证、group泄漏审计与数据划分。 |
| `ppocr_plate/synthetic.py` | 单层7/8位蓝牌、黄牌、新能源牌及透视/模糊/低照等合成增强。 |
| `ppocr_plate/train.py` | `smoke/train/export` 统一入口；formal train 强制读取 audit gate。 |
| `ppocr_plate/runtime.py` | BGR crop -> RGB `[1,3,48,160]`、CTC解码和统一 recognize 接口。 |
| `ppocr_plate/export_onnx.py` | Paddle -> ONNX、固定shape、ORT实跑和真实crop Paddle/ONNX parity。 |
| `ppocr_plate/benchmark.py` | ONNX Runtime端到端延迟、质量和门槛统计。 |
| `ppocr_plate/openvino_tools.py` | OpenVINO FP32转换、严格 `real_verified` INT8校准和 benchmark。 |
| `ppocr_plate/rknn_tools.py` | RKNN FP16/INT8转换、1000-2000真实样本校准和板端benchmark。 |
| `ppocr_plate/compare_backends.py` | Paddle/ONNX/OpenVINO/RKNN文本一致性与量化损失比较。 |
| `ppocr_plate/data/synthetic_smoke*` | 结构冒烟合成图片；不是正式数据。 |
| `ppocr_plate/data/splits_smoke*` | 冒烟划分、canonical manifest 和 audit；正式数据门槛均未通过。 |

当前不存在或尚未完成：

- `splits_formal`。
- 3000 张人工核验 `real_verified`。
- 官方 PP-OCRv4 预训练 checkpoint 本地副本。
- 正式训练 run。
- PP-OCR 专用 ONNX、OpenVINO IR 和 RKNN 产物。
- Windows/RK3588 双端1000次正式 P95。

---

## 10. `RK3588_dev` 关键文件和目录

### 10.1 模型与转换

| 文件 | 作用 |
|---|---|
| `vehicle.rknn` | 板端车辆检测模型。 |
| `plate_obb.rknn` | 板端车牌 OBB 模型。 |
| `plate_rec.rknn` | 旧板端独立 OCR 实验。 |
| `yolo11n.onnx` | 车辆模型 ONNX 中间产物。 |
| `best_obb.onnx` | OBB ONNX 中间产物。 |
| `plate_rec.onnx` / `plate_rec_sim.onnx` | 独立 OCR ONNX，非 HyperLPR3。 |
| `dict.txt` / `dataset.txt` | 旧 OCR 字典和 RKNN 转换数据列表。 |
| `onnx_to_rknn.py` | ONNX -> RKNN 转换脚本。 |
| `convert_obb_640.py` / `convert_obb_640_fp16.py` | OBB RKNN 转换。 |
| `main.cpp` / `rknn_model_info.cpp` / `CMakeLists.txt` | C++/RKNN实验和模型信息工具，不是当前生产主线。 |

### 10.2 SC850SL 启动、预览和探针

| 文件 | 作用 |
|---|---|
| `run_sc850_video71_alpr_live.sh` | 7月 balanced/quality 实时配置。 |
| `run_sc850_video71_alpr_live_roi_rightroad_20260730.sh` | 右侧道路 ROI 实验。 |
| `run_sc850_video71_alpr_live_roi_rightroad_4k_accuracy_20260730.sh` | 右道路4K精度实验。 |
| `run_sc850_video71_alpr_live_roi_trafficcorridor_4k_accuracy_postfocus_20260730.sh` | 对焦后交通走廊4K实验。 |
| `run_sc850_video71_alpr_live_postfocus_reassoc_async_20260730.sh` | 对焦后、保守重关联、异步4K预览实验。 |
| `sc850_video71_focus_preview.py` | 对焦预览和清晰度指标采集。 |
| `stream_threaded_mjpeg.py` / `stream_threaded_preview_page.py` | 多线程 MJPEG/预览页面实验。 |
| `stream_4k_polling_preview_page.py` | 4K轮询预览页面。 |
| `stream_focus_preview_page.py` | 对焦辅助页面。 |
| `sc850_video71_vehicle_probe_collect.sh` | 有界采集、ALPR probe 和证据打包；默认 OCR none 时不能当正式识别。 |
| `sc850_isp_probe.sh` | ISP/media graph/V4L2专项探针。 |

### 10.3 证据包与分析目录

- `sc850_*probe*.tar.gz`：sensor、I2C、device tree、media graph、rkaiq、video71和识别探针。
- `sc850_recognition_feedback_*.tar.gz`：第一批真实道路识别反馈。
- `sc850_recognition_batch_*.tar.gz`：较长批量道路识别。
- `sc850_recognition_dedupe_*.tar.gz`：文字去重长跑。
- `sc850_alpr_performance_profile_20260714.tar.gz`：balanced性能证据。
- `_analysis_sc850_*`：回传包解压、锁定事件统计和 contact sheet。
- `board_inspection_20260729`：7月30日对焦、ROI、4K精度、长跑和短测结果。
- `rk_*`：板端 tracker、reassociation、Windows等价、predicted plate、pre-OCR、adaptive等历史A/B。
- `offline_bundle`：可复制到板端的离线部署包、操作指南、依赖和模型。

### 10.4 `RK3588` 目录

`RK3588` 包含早期 C++ 应用、ByteTrack、Eigen 和 RKNN 模型。`main.cpp`/`alpr_app` 是实验资产，不是当前 Python 板端主线。不要因为看到 C++ 文件就判断项目已迁移到 C++。

---

## 11. 数据、模型和结果目录

### 11.1 数据集

`Dataset` 主要包含：

- `dataset/train/sharp` 与 `train/blur`：各9367张。
- `dataset/test/sharp` 与 `test/blur`：各1041张。
- `CCPD2020`。
- `CRPD_single`、`CRPD_double`、`CRPD_multi`。
- `MDLP_Mini`。
- `plate_dataset_obb_finetune`。
- `obb_hardcase_review`。
- `plate_deblur_dataset_v1/v2/v2_smoke`。
- 对应 zip 压缩包。

注意：这些目录不是自动等于人工真值。特别是 `Dataset/dataset/test/sharp` 没有本轮可用的人工车牌标签，只能做性能和输出行为测试。

### 11.2 去模糊

`blur models/deblur_v2_e20` 包含：

- `plate_restore_lite_v2_e20_320x96.onnx`。
- best/last PyTorch checkpoint。
- metrics、config、静态测试和完整 Top-K 评估结果。

当前结论：部分图像视觉变清晰，但 OCR 收益不稳定，且会增加实时开销；只保留在 Windows demo/离线 A/B，不进入 RK 实时主链。

### 11.3 结果目录命名

- `captures_topk*`：Windows Top-K/回归。
- `captures_demo*`：Windows demo，包括 pure-rec JSONL。
- `captures_deblur*`：去模糊视频/静态 A/B。
- `runs_hyperlpr3_recognition_ab*`：18组三路 A/B。
- `runs_hyperlpr3_image_dir*`：1041张车牌目录基准。
- `runs_hyperlpr3_full_stages*`：完整接口分阶段基准。
- `runs_plate_rec_sim_corrected`：独立 OCR纠正基准。
- `runs_ppocr_plate_train`：PP-OCR冒烟/训练输出。
- `runs_realtime_async*`：原速异步运行。
- `RK3588_dev/rk_*` 和 `sc850_*`：板端实验、探针和回传证据。

重要正式/代表性路径：

```text
captures_topk_codex_win_20260708\run_20260708_131529
runs_hyperlpr3_recognition_ab\run_20260807_170904
runs_plate_rec_sim_corrected\run_20260808_094939
runs_ppocr_plate_train\smoke_20260808_092616
runs_hyperlpr3_image_dir\run_20260811_112914
runs_hyperlpr3_full_stages\run_20260811_114704
captures_demo_hyperlpr3_rec\run_20260812_154752
runs_realtime_async_hyperlpr3_rec_smoke\run_20260812_162454
runs_realtime_async_hyperlpr3_rec_gui_smoke\run_20260812_162947
runs_realtime_async_hyperlpr3_rec\run_20260812_163427
RK3588_dev\board_inspection_20260729
```

---

## 12. 输出文件怎么读

### 12.1 Top-K run

常见结构：

```text
run_时间戳
├─ run_summary.json
├─ recognition_results.jsonl（纯识别/异步时）
└─ track_<id>
   ├─ summary.json
   ├─ full_rank*.jpg
   ├─ vehicle_rank*.jpg
   ├─ plate_rank*.jpg
   └─ rejected
      ├─ full_reject*.jpg
      ├─ vehicle_reject*.jpg
      └─ plate_reject*.jpg
```

字段含义：

- `track_id`：短期车辆身份，相同值表示程序认为属于同一辆车。
- `seen_frames`：track出现帧数。
- `plate_hits`：OBB候选命中数。
- `vote_history` / `vote_counts`：OCR投票。
- `locked_text` / `locked_frame` / `locked_confidence`：最终锁定。
- `candidates`：Top-K accepted候选。
- `rejected_candidates`：几何、置信度、面积、重叠等未通过的样本。

### 12.2 `recognition_results.jsonl`

当前 pure-rec 每一行代表一次实际 OCR 调用，而不是一辆车的最终汇总。常见字段：

- `frame_idx`、`track_id`。
- `ocr_engine=hyperlpr3-rec`。
- `source=plate`。
- `text`、`confidence`。
- `ocr_ms`。
- `timing_scope=recognition_preprocess_inference_ctc_decode`。
- `format_valid`、`confidence_pass`、`length_pass`。
- `vote_attempted`、`entered_vote`、`locked_now`。
- `vote_reason`。
- `error`。
- `vehicle_box`、`plate_corners`。
- 异步链路还包含 `vehicle_ms`、`plate_ms`、`recognition_total_ms`、`end_to_end_ms`。

非法、低置信或短字符串仍会出现，`entered_vote=false` 表示它只保留作诊断。

### 12.3 异步 `summary.json`

- `video.source_fps`：源文件声明 FPS。
- `runtime.video_loop_fps`：实际播放/读取时间轴速度。
- `frames_submitted`：提交到最新帧缓冲的帧数。
- `frames_replaced_before_inference`：后台未开始前被新帧覆盖的数量。
- `recognition.processed_frames` / `processed_fps`：后台真正处理量。
- 退出时单槽可能仍有最多1个尚未开始的末帧，因此提交数不保证严格等于“后台处理数 + 覆盖数”。
- `ocr_calls` / `average_ocr_ms`：纯 OCR 调用。
- `frames_with_plate_stage` / `frames_with_ocr`：触发覆盖率。
- `locks`：达到投票门槛的锁定。

---

## 13. 环境与运行约束

### 13.1 Windows

- 推荐解释器：`D:\miniconda\envs\alpr_env\python.exe`。
- 系统默认 Python 3.13 与项目内 ONNX Runtime DLL 曾不兼容，不要用默认 `python` 盲跑。
- 正式 HyperLPR3 基准环境记录为 Python 3.10.20、Windows、16逻辑处理器、ONNX Runtime 1.23.2、CPU provider。
- CUDA 当前不可用；Windows主测为CPU-only。
- `python_deps_ocr` 含本地 HyperLPR3/ORT 依赖，目录内可能混有不同 Python ABI 产物，因此更要固定解释器。

### 13.2 RK3588

- 远程板历史地址：`192.168.8.88`，用户 `root`。
- 板端项目：`/root/alpr_topk_rk3588`。
- 离线模型包：`/root/rk3588_alpr_roadtest_bundle_20260701`。
- 摄像头：SC850SL `/dev/video71`，3840×2160 NV12。
- 浏览器预览通常读取 `/tmp/frame.jpg`；旧帧不代表识别程序仍在运行。
- `rkaiq_3A_server` 是 ISP 工作的一部分，不得随意停止。
- ALPR、mediamtx 和 `/opt/MultiSensing/bin/multisense` 不应同时抢占 `/dev/video71`。
- `multisense` 当前是否已临时禁用、权限是否恢复：待确认，必须先只读检查。

---

## 14. 常用运行命令

### 14.1 当前推荐：原速播放 + HyperLPR3 纯识别

```powershell
& "D:\miniconda\envs\alpr_env\python.exe" -u .\alpr_realtime_async.py `
  --video "D:\YOLO_ALPR_Project\测试图\14.mp4" `
  --output "D:\YOLO_ALPR_Project\runs_realtime_async_hyperlpr3_rec" `
  --ocr-engine hyperlpr3-rec `
  --pipeline vehicle `
  --plate-stage always `
  --tracking iou `
  --recognition-initial-state on `
  --min-ocr-conf 0.5 `
  --ocr-warmup 20 `
  --torch-threads 4 `
  --show-video
```

操作：

- `R`：暂停/恢复后台识别，播放继续。
- `Q` 或 `Esc`：保存并退出。
- `FPS/SRC`：播放速度。
- `INFER`：后台处理速度。
- `DROP`：为保持原速主动覆盖的过期帧。

### 14.2 同步 demo 纯识别

```powershell
& "D:\miniconda\envs\alpr_env\python.exe" -u .\alpr_topk_capture_demo.py `
  --video "D:\YOLO_ALPR_Project\测试图\14.mp4" `
  --output "D:\YOLO_ALPR_Project\captures_demo_hyperlpr3_rec" `
  --live-ocr `
  --ocr-engine hyperlpr3-rec `
  --min-ocr-conf 0.5 `
  --show-ocr-timing `
  --show-window
```

不要同时加 `--with-ocr`，否则退出后会对 Top-K 再做一次离线 OCR。纯识别基线也不要加 deblur。

### 14.3 单张纯识别

```powershell
& "D:\miniconda\envs\alpr_env\python.exe" -u .\hyperlpr3_recognize_once.py `
  --image "D:\YOLO_ALPR_Project\Dataset\dataset\test\sharp\grab10003.jpg" `
  --warmup 20 `
  --show
```

### 14.4 1041张批量基准

```powershell
& "D:\miniconda\envs\alpr_env\python.exe" -u .\benchmark_hyperlpr3_image_dir.py `
  --input-dir "D:\YOLO_ALPR_Project\Dataset\dataset\test\sharp" `
  --output "D:\YOLO_ALPR_Project\runs_hyperlpr3_image_dir" `
  --warmup 50 `
  --repeats 1
```

### 14.5 完整接口分阶段

```powershell
& "D:\miniconda\envs\alpr_env\python.exe" -u .\benchmark_hyperlpr3_full_stages.py `
  --input-dir "D:\YOLO_ALPR_Project\Dataset\dataset\test\sharp" `
  --output "D:\YOLO_ALPR_Project\runs_hyperlpr3_full_stages" `
  --warmup 50 `
  --repeats 1
```

### 14.6 PP-OCR 冒烟

正式训练前先读 `ppocr_plate/README.md`。当前 smoke 示例：

```powershell
& "D:\miniconda\envs\alpr_env\python.exe" -m ppocr_plate.train smoke `
  --paddleocr-root third_party\PaddleOCR `
  --splits ppocr_plate\data\splits_smoke_rgb_contract_20260808 `
  --data-root ppocr_plate\data
```

不要把 smoke 当正式模型。

### 14.7 RK 只读第一步

在用户明确回到 RK 任务后，先只读检查，不直接杀进程：

```bash
date
pgrep -af multisense || true
fuser -v /dev/video71 || true
stat -c '%a %A %n' /opt/MultiSensing/bin/multisense
cat /root/alpr_topk_rk3588/multisense_mode_before_alpr.txt 2>/dev/null || true
```

具体稳定测试和权限恢复命令以 `NEW_CHAT_HANDOFF_20260717.md` 为准。

---

## 15. 已尝试但未采用或暂缓的方案

| 方案 | 结果 | 当前决定 |
|---|---|---|
| PaddleOCR 通用 OCR | 小而模糊中文车牌不稳定且较慢 | 不作为当前主OCR |
| `plate_rec_sim.onnx` | 速度与文字质量均不达标 | 放弃正式接入 |
| HyperLPR3 完整接口识别已裁车牌 | 重复检测、漏掉部分紧裁车牌，耗时高 | 保留作完整接口/双层牌；单层速度路径用pure-rec |
| 直接把 Python 全量改 C++ | 模型推理占主导，改写成本大 | 暂缓；先优化模型/后端和数据流 |
| 每帧同步识别保证不丢 | 播放约4-10 FPS，无法原速 | 改为latest-frame异步 |
| 强行把24FPS视频显示成30FPS | 只能加速或重复帧 | 拒绝；以源FPS验收 |
| 去模糊实时接入 | 视觉改善但OCR收益不稳定，增加算力 | 仅离线/Windows demo A/B |
| RealESRGAN/ESPCN超分 | 增加计算且无稳定实证收益 | 不进入实时主链 |
| RK复杂预测/重关联 | 框杂乱、可能错误关联、增加开销 | 当前弱化；只保留短期证据状态 |
| SC850 RAW10灰度作为主输入 | 能救急，但图像域与最终目标不一致 | 仅备用；主输入是video71 NV12 |
| `/dev/video44`/`video53` 当SC850主节点 | media graph不匹配 | 已否定；主节点是video71 |
| ROI分块无限扩展 | 能出框但广告牌/灯箱假阳性增加 | 需按车道证据收敛 |
| motion fallback | 能框真车，也会框电动车/车轮/行人 | 只作候选源，需形状和车道过滤 |

---

## 16. 当前风险、限制和待确认

### 16.1 Windows 纯识别

1. 纯识别依赖上游 OBB 四点和透视质量；裁偏、倒置、旋转和边缘不足会直接影响文字。
2. 第一版不支持双层车牌拆行，也不自动回退完整 HyperLPR3。
3. 原速播放会覆盖过期后台帧，降低车辆/OBB/OCR覆盖率。
4. 稀疏处理和IoU跟踪可能使同车 ID 断裂，影响多帧投票。
5. 当前三票门槛在异步样本中可能过严；不能直接改为单票锁定，需要先用真值评估误锁。
6. 未对完整6971帧做当前版本的正式全视频验收。
7. OCR延迟对CPU负载和线程配置敏感；基准时必须固定预热、线程和后台进程。

### 16.2 模型质量

1. 1041张 sharp 目录无人工真值，不能报告准确率。
2. 历史 summary 和旧 OCR 只可作 agreement 参考，不能当标签。
3. 现有车牌文本曾出现 `冀JC5210/冀JE5210/冀JC5216` 等字符差异，必须看原图和人工标注。
4. 高置信度和格式合法仍可能是错牌。

### 16.3 PP-OCR

1. 正式训练尚未开始。
2. 缺至少10万公开/合成样本与人工核验2000/500/500。
3. 缺官方预训练checkpoint和GPU。
4. 当前环境缺完整 paddle2onnx/onnx/OpenVINO/NNCF/RKNN工具链。
5. 尚无专用ONNX/OpenVINO/RKNN产物和双端1000次基准。

### 16.4 RK/SC850SL

1. `multisense` 当前是否禁用、谁会重新启动它、权限是否恢复：待确认。
2. 不能停止 `rkaiq_3A_server`。
3. balanced/后聚焦配置仍需要排除占用后跑满至少1000 processed frames。
4. RK约4 FPS仍不足以覆盖高速车辆。
5. 曝光、增益和自动曝光控制项/单位未完全确认。
6. 部分历史 lock evidence 只有一张图，尽管 `lock.json` 有两次投票；证据保存仍可加强。
7. `best_obb_finetuned_e20.pt` 转 RKNN 并与当前模型 A/B 尚未完成。

---

## 17. 已过时、不能继续照搬的旧结论

1. “SC850SL 当前 sensor 未上线、video71 不能出帧”已经过时。
2. “SC850SL 主节点是 `/dev/video53`”错误；当前确认主节点是 `/dev/video71`。
3. `/dev/video33` RAW10 灰度只保留为备用，不是主路线。
4. `DECISIONS.md` 决定25“纯识别只离线”已被后续 demo 和异步接入取代。
5. `PROJECT.md` 早期“视频不叠加性能文字”已被用户后来明确要求左上角 FPS HUD 更新。
6. `NEW_CHAT_HANDOFF_20260717.md` 中“当前不要跑去单独调Windows OCR”已经被8月用户最新任务改变；该文档仍是RK专项权威历史。
7. `_publish/PLR-Test/README.md` 的完整HyperLPR3/0.70阈值示例落后于本地pure-rec/0.50实现。
8. `PROJECT_HANDOFF.md` 是早期历史，里面的IMX585/video53/MIPI 0字节主结论不能当当前事实。

---

## 18. Git 与远端发布状态

### 18.1 本地主仓库

- 当前分支：`main`。
- HEAD：`cbdc197b`（创建本文前检查）。
- 工作区不是 clean 状态，包含用户已有修改、未跟踪源码、结果和分析目录。
- 不得为了“清理”执行 `git reset --hard`、`git checkout --` 或删除未跟踪目录。
- `alpr_topk_capture.py` 当前未显示修改，继续作为受保护基准。

### 18.2 Gitea 轻量仓库

仓库地址：`http://47.102.197.116:3000/gcvision_admin/PLR-Test.git`

发布副本：`_publish\PLR-Test`  
远端提交：`37580c3 Add lightweight async ALPR core`

远端只包含：

```text
.gitignore
README.md
requirements.txt
alpr_realtime_async.py
alpr_topk_capture_demo.py
hyperlpr3_ocr.py
plate_rec_ocr.py
```

当前哈希核对：

- 本地 `alpr_realtime_async.py` 与发布副本不同。
- 本地 `alpr_topk_capture_demo.py` 与发布副本不同。
- 本地 `hyperlpr3_ocr.py` 与发布副本不同。
- `plate_rec_ocr.py` 与发布副本相同。

因此远端是8月6日历史快照，尚未包含8月12日完整 pure-rec、事件和原速收紧版本。若要再次发布，应单独做差异审查、语法测试、敏感信息扫描，再由用户明确要求推送。

---

## 19. 推荐下一步

### P0：Windows 当前直接任务

1. 用当前 `alpr_realtime_async.py` 跑完整 6971 帧，保留 GUI 或无窗口两种结果。
2. 同时汇报：源FPS、播放FPS、提交帧、后台处理帧、DROP、车辆命中、plate stage、OCR调用、有效OCR、投票和锁定。
3. 从实际 OBB plate crop 建立人工真值集，优先标注同一车辆连续帧和双层牌。
4. 计算纯识别整牌准确率、字符准确率、格式误接收率、最终锁定召回和误锁。
5. 在保持24 FPS播放的前提下，提高后台覆盖率：优先评估车辆YOLO输入尺寸、检测间隔、道路ROI、OpenVINO/ONNX和线程组合。
6. 对 `torch=2/4/8`、ORT线程和OpenCV线程做独占CPU A/B，固定warmup和P50/P95。
7. 若三票导致召回不足，先基于人工真值比较2票/3票，不要直接单票上线。

### P1：HyperLPR3推理优化

1. 为纯识别适配器增加可控 ONNX Runtime `SessionOptions`，A/B intra-op 1/2/4/8。
2. 评估 OpenVINO FP32/INT8 或模型量化，但每次都必须回归文字质量。
3. 保持预处理和解码协议不变，避免为了速度造成隐性准确率变化。
4. 不在未测出Python控制流占比前启动全量C++迁移。

### P1：PP-OCR正式训练前置

1. 获取并核查公开数据许可证。
2. 构建至少10万训练样本和人工核验2000/500/500。
3. 确保同车/同视频group不跨集合。
4. 下载官方 `ch_PP-OCRv4_rec_train` checkpoint。
5. 准备GPU环境后再执行 formal train。
6. 完成Paddle/ONNX/OpenVINO/RKNN parity、量化和双端1000次测试。

### P1：RK/SC850SL

1. 先只读检查 `multisense` 和 `/dev/video71` owner。
2. 确认节点空闲后做30帧4K NV12直采。
3. balanced或后聚焦配置跑满至少1000 processed frames，保存完整证据包。
4. 补齐capture read、NV12->BGR、ROI resize、tracker/绘制/保存的完整timing。
5. 明确曝光/增益控制后做短曝光运动模糊A/B。
6. 将 e20 OBB 转RKNN并同条件A/B。

---

## 20. 新对话建议提示词

可在新对话中直接发送：

```text
请先完整阅读以下文件，不要先修改代码或跑重型实验：

1. D:\YOLO_ALPR_Project\AGENTS.md
2. D:\YOLO_ALPR_Project\NEW_CHAT_HANDOFF_20260814.md

然后根据我的任务选择源码：

- Windows原速纯识别：alpr_realtime_async.py、alpr_topk_capture_demo.py、hyperlpr3_ocr.py
- HyperLPR3性能：benchmark_hyperlpr3_image_dir.py、benchmark_hyperlpr3_full_stages.py、hyperlpr3_recognize_once.py
- PP-OCR训练：ppocr_plate\README.md及ppocr_plate源码
- RK/SC850SL：NEW_CHAT_HANDOFF_20260717.md、rk3588_topk_capture_mipi_debug_sc850.py、rk3588_topk_capture_mipi_debug_sc850_postfocus.py、RK3588_dev\run_sc850_*.sh

当前最近目标是Windows按源24 FPS原速播放，同时后台只运行HyperLPR3纯识别。车辆YOLO和车牌OBB只负责定位；不能调用HyperLPR3检测器/颜色分类器，也不能识别车辆crop。每次OCR都要保存在recognition_results.jsonl，并用track_id区分同车。

已验证610帧为24.029 FPS，用户2502帧GUI运行是24.001 FPS。该原速方案会覆盖过期后台帧，所以播放FPS、后台覆盖率、OCR延迟、投票锁定和准确率必须分开汇报。

长期目标仍是RK3588 + SC850SL /dev/video71 4K NV12真实道路识别。video71已经验证可出30 FPS，旧的sensor未上线结论已过时；回到RK任务时先检查multisense占用，不要停止rkaiq_3A_server。

PP-OCRv4正式训练尚未开始，目前只有100步CPU结构冒烟。没有审计数据、预训练权重和GPU时，不得宣称已经在正式训练，也不得把smoke模型当可用OCR。

请先用中文回答：
1. 你理解的当前直接目标和长期目标分别是什么？
2. 当前已经实现了什么？
3. 哪些测试数字是正式基准，哪些只是历史/受负载影响？
4. 哪些旧结论已经过时？
5. 你准备读取哪些源码和结果文件？
6. 你建议的下一步是什么？

要求区分事实、推断、待确认和建议；不要覆盖用户现有改动；不要修改Windows基准alpr_topk_capture.py。
```

---

## 21. 最终一句话

当前 Windows 已经实现“源24 FPS原速播放 + 后台车辆/OBB定位 + HyperLPR3纯识别 + 每次OCR JSONL + 同车投票”，但原速依赖覆盖过期推理帧，下一步要用人工真值和完整视频同时优化识别覆盖率与锁定质量；PP-OCR仍是训练准备，RK长期线则以已通的SC850SL `/dev/video71` 4K NV12为基础继续解决节点独占、4 FPS吞吐和高速车辆运动模糊。
