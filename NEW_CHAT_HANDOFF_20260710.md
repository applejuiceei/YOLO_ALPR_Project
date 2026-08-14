# 新对话交接文档：SC850SL /dev/video71 NV12 实时道路识别调试

更新时间：2026-07-10  
用途：新开对话后，先读本文件，快速接上当前项目目标、代码结构、实验结论、关键脚本、已尝试方案和下一步动作。  
说明：本文件根据当前项目文件、项目记忆文档和本轮对话整理。凡无法从现有文件或用户反馈确认的内容，均标注“待确认”。

---

## 1. 新 AI 必须先读什么

建议阅读顺序：

1. `AGENTS.md`
2. `NEW_CHAT_HANDOFF_20260710.md`
3. `PROJECT.md`
4. `STATUS.md`
5. `DECISIONS.md`
6. `HANDOFF.md`
7. `PR0JECT_0708.md`
8. `STATUS_0708.md`
9. `DECISIONS_0708.md`
10. `HANDOFF_0708.md`
11. `NEW_CHAT_HANDOFF_20260708.md`
12. `rk3588_topk_capture_mipi_debug_sc850.py`
13. `RK3588_dev/sc850_video71_vehicle_probe_collect.sh`
14. `RK3588_dev` 下最近的 `sc850_*probe*`、`mediamtx_*probe*` 解包目录和 tar.gz 包

必须注意：

- 默认中文沟通。
- 先读项目记忆文件，再动代码或跑实验。
- 信息不确定必须标注“待确认”。
- 不得把 `ocr-engine none` 或显示 `PLATE` 当成真实车牌识别完成。
- 不得把 MIPI 0 字节出帧问题草率归因到 Python、模型或 ALPR 逻辑。
- `alpr_topk_capture.py` 是 Windows 基准主线，不要随意改。
- Windows 实验优先用 `alpr_topk_capture_demo.py`。
- RK3588 端实时主线围绕 `rk3588_topk_capture.py` / `rk3588_topk_capture_mipi_debug.py` / `rk3588_topk_capture_mipi_debug_sc850.py` 推进。
- 当前 OCR 主推 HyperLPR3。
- 板端视频测试至少跑到 frame 1000 才能下比较可靠的结论。
- 浏览器里的 `/tmp/frame.jpg` 可能是旧帧，不代表识别程序正在运行。

---

## 2. 项目最终目标

项目要完成的是：

在 RK3588 板端，使用远程电脑那块板子上连接的 SC850SL 摄像头，通过 ISP 后处理端口 `/dev/video71` 输出的 NV12 实时画面，实现道路场景车辆检测、车牌候选检测、OCR 识别、Top-K 候选保存、投票锁定和浏览器实时预览。

最终希望达到的效果：

- 远程板子上的 SC850SL 摄像头实时采集道路画面。
- 识别程序使用 `/dev/video71` 的 NV12 ISP 后处理画面作为主输入。
- 能稳定检测道路车辆。
- 能从车辆 ROI 中检测车牌候选。
- 能使用 HyperLPR3 或后续确定的 OCR 引擎输出真实车牌文本。
- 能通过 Top-K、轨迹投票、锁定策略降低误识别。
- 浏览器访问类似 `http://192.168.8.88:8080/view.html` 可以看到实时帧、检测框、车牌框、锁定结果。
- 运行结果能保存 summary、Top-K 图、rejected 样本、vote history，便于继续调参。

验收不能只看：

- 只看到 `PLATE` 占位。
- 只看到黄色框或蓝色车辆框。
- 只看到 `/tmp/frame.jpg` 被浏览器展示。
- 只跑了内置视频。
- 只跑了手机图片。

真正验收必须看：

- SC850SL 真实 MIPI 摄像头链路恢复正常。
- `/dev/video71` 能稳定输出 NV12 帧，单帧大小应为 3840x2160 NV12，即 12441600 bytes。
- 真实道路场景中车辆检测起量。
- OCR 输出真实文本，而不是 `none` 或占位。
- 锁定结果经过 vote / Top-K 证据验证。

---

## 3. 当前总体结论

### 3.1 已确定的事实

- Windows 基准流程已经跑通。
- 本地 RK3588 + IMX585 的内置视频流程已经跑通。
- 远程 SC850SL 板子跑内置视频也已经证明 ALPR 主流程可用。
- 远程 SC850SL 真实摄像头链路曾经在 `/dev/video71` 上成功输出过 NV12 帧。
- 用户已明确确认：`/dev/video71` 是 SC850SL ISP 处理后的主端口，不再把 `/dev/video53` 当主线替代。
- 早期 SC850SL `/dev/video71` 实拍道路画面曾经有车辆检测、车牌候选和 HyperLPR3 OCR 输出。
- 后续多轮 probe 表明：当前主要卡点转移到 SC850SL 摄像头链路本身，表现为 `/dev/video71` 0 字节、`STREAMON Operation not permitted`、media graph 退回异常状态、I2C 0x30 不响应、dmesg 出现 sensor id `000000`。
- 用户最近已经重新插拔过摄像头模组。

### 3.2 当前推断

- 当前优先问题不是 ALPR Python 主逻辑，而是 SC850SL sensor / I2C / reset / power / device-tree / media graph / rkaiq 绑定链路。
- 如果重插后 I2C 0x30 恢复，下一步应先验证 `/dev/video71` 单帧 NV12，再跑 ALPR。
- 如果重插后 I2C 0x30 仍不出现，则应继续查物理连接、供电、reset GPIO、I2C bus、模组方向和板端摄像头接口，而不是继续调 OCR 或 Top-K。

### 3.3 待确认

- 用户重插 SC850SL 后，I2C 0x30 是否恢复。
- 重插后 `/dev/video71` 是否能输出 12441600 bytes 的 NV12 单帧。
- 重插后 media7 是否重新出现 SC850SL sensor upstream。
- 当前远程板是否需要冷重启才会重新 probe sensor。
- SC850SL reset GPIO `gpio-39` 与 debugfs 中 `gpio-38 reset` 显示差异的具体原因待确认。

---

## 4. 已经实现了什么

### 4.1 Windows 基准识别

主脚本：

- `alpr_topk_capture.py`
- `alpr_topk_capture_demo.py`

已实现能力：

- 视频输入。
- YOLO / OBB 车牌候选检测。
- 车辆检测。
- OCR。
- Top-K 截图保存。
- track 级别投票。
- 锁定车牌输出。
- rejected 样本保存。
- summary / vote history 保存。

已知一次 Windows 基准运行：

- 输入：`D:\YOLO_ALPR_Project\测试图\14.mp4`
- 输出：`D:\YOLO_ALPR_Project\captures_topk_codex_win_20260708\run_20260708_131529`
- 处理帧数：6971
- track 数：8
- 已锁定结果包括：
  - `冀JC5216`
  - `冀B6R9F9`
  - `鲁V0JU1Q`
  - `冀CH7V97`
- 注意：`冀JC5216` 与常见候选 `冀JC5210` 有差异，需人工复核。

### 4.2 RK3588 内置视频识别

主脚本：

- `rk3588_topk_capture.py`
- `rk3588_topk_capture_mipi_debug.py`

已实现能力：

- RKNN 车辆检测。
- RKNN 车牌 OBB 候选。
- HyperLPR3 OCR。
- Top-K 保存。
- track 投票锁定。
- summary / vote history 输出。
- 可用内置视频验证 RK 侧主流程。

已知本地 IMX585 / RK 视频测试：

- 输入：`/root/deploy/144.mp4`
- 输出板端：`/root/alpr_topk_rk3588/runs_codex_mipi_debug_video_20260708/run_20260708_053036`
- 已拉回本地：`D:\YOLO_ALPR_Project\RK3588_dev\runs_codex_mipi_debug_video_20260708\run_20260708_053036`
- 处理帧数：1000
- 约 4.07 FPS
- 锁定结果：
  - `冀JE5210`
  - `冀B6R9F9`
- 注意：`冀JE5210` 与人工常见判断 `冀JC5210` 有差异，需复核。

另一次更早 RK 视频测试结论记录：

- 处理 1000 帧。
- 约 10 FPS。
- 可锁定 `冀JC5210`、`冀B6R9F9`。

### 4.3 远程 SC850SL 内置视频

用户已反馈：

- 远程电脑那块 RK3588 板子运行内置视频可以达到本地板类似效果。
- 说明远程板子的模型、Python、RKNN、OCR、Top-K 主流程本身不是完全不可用。

### 4.4 SC850SL 实时摄像头调试脚本

主脚本：

- `rk3588_topk_capture_mipi_debug_sc850.py`

已实现或后补能力：

- MIPI V4L2 输入。
- 支持 `/dev/video71` NV12。
- 支持 `--mipi-backend v4l2ctl`。
- 支持 `--mipi-color-mode nv12`。
- 支持 `--vehicle-source rknn|motion|hybrid`。
- 支持 detect ROI 和 process ROI。
- 支持浏览器发布 `/tmp/frame.jpg`。
- 支持 `--ocr-engine none|hyperlpr3|rknn`。
- 支持 Top-K 和投票锁定。
- 支持 `--strict-plate-format`，用于要求 OCR 文本更像中国车牌格式。
- 修复过 `consensus()` 中空 `scored_ratios` 的警告风险。

辅助采集脚本：

- `RK3588_dev/sc850_video71_vehicle_probe_collect.sh`

作用：

- 在远程板上运行 SC850SL `/dev/video71` 采集和 ALPR 探针。
- 收集 date、进程、rkaiq 状态、v4l2 设备、media graph、dmesg、journal。
- 先测 `/dev/video71` 单帧 NV12。
- 再运行 `rk3588_topk_capture_mipi_debug_sc850.py`。
- 自动打包到 `/tmp/sc850_video71_vehicle_probe_${TAG}.tar.gz`，方便用户传回本地。

---

## 5. 当前文件结构和各文件作用

### 5.1 项目根目录 `D:\YOLO_ALPR_Project`

核心记忆文档：

- `AGENTS.md`：AI 员工手册，长期规则、工作流程、红线。
- `PROJECT.md`：项目目标、验收标准、当前主线。
- `STATUS.md`：当前状态、已完成、卡点、下一步。
- `DECISIONS.md`：已经做出的关键决定及原因。
- `HANDOFF.md`：交接阅读顺序和接手第一步。
- `PROJECT_HANDOFF.md`：旧版或补充交接文档。
- `NEW_CHAT_HANDOFF_20260708.md`：2026-07-08 的新对话交接。
- `NEW_CHAT_HANDOFF_20260710.md`：本文件，2026-07-10 新对话交接。
- `AGENTS_0708.md`：用户要求 0708 创建的 AI 员工手册副本。
- `PR0JECT_0708.md`：注意文件名是 `PR0JECT`，中间是数字 0，不是字母 O；记录 0708 项目目标。
- `STATUS_0708.md`：0708 状态记录。
- `DECISIONS_0708.md`：0708 决策记录。
- `HANDOFF_0708.md`：0708 交接记录。
- `REMOTE_CODEX_HANDOFF.md`：远程协作相关交接信息。

Windows / 通用识别脚本：

- `alpr_topk_capture.py`：Windows 基准主线，原则上不随意修改。
- `alpr_topk_capture_demo.py`：Windows 实验优先脚本，用于避免污染基准主线。
- `hyperlpr3_ocr.py`：HyperLPR3 OCR 封装或测试相关脚本。
- `plate_rec_ocr.py`：plate_rec OCR 相关脚本。
- `ocr_compare_topk.py`：OCR 对比和 Top-K 分析相关脚本。
- `topk_report.py`：Top-K 报告生成或汇总相关脚本。

RK3588 主线脚本：

- `rk3588_topk_capture.py`：RK3588 板端优化重点脚本。
- `rk3588_topk_capture_mipi_debug.py`：RK3588 MIPI 调试版脚本。
- `rk3588_topk_capture_mipi_debug_sc850.py`：SC850SL 后补主脚本，当前远程板主要运行它。
- `mipi_current_frame_probe.py`：MIPI 当前帧探针脚本。
- `rk3588_mipi_isp_probe.py`：RK3588 MIPI/ISP 探针脚本。

模型和权重：

- `best_obb.pt`：车牌 OBB 相关 PyTorch 权重。
- `best_obb_finetuned_e20.pt`：微调后的 OBB 权重。
- `yolo11n.pt`、`yolov8n.pt`：YOLO 检测权重。
- `RealESRGAN_x4plus.pth`：超分模型，不能未验证就接入 RK 实时主链路。

结果目录：

- `captures_topk_codex_win_20260708`：Windows 基准测试结果。
- `captures_*`：不同 Windows 或实验输出目录。
- `runs_*`：部分运行结果目录。
- `debug_*` / `analysis_*`：调试和分析输出。

数据目录：

- `Dataset`：项目数据集或样本数据目录。
- `测试图`：测试视频或图片目录。

### 5.2 `D:\YOLO_ALPR_Project\RK3588_dev`

RK 模型和转换文件：

- `best_obb.onnx`：OBB ONNX 模型。
- `vehicle.rknn`：车辆检测 RKNN 模型。
- `plate_obb.rknn`：车牌 OBB RKNN 模型。
- `plate_rec.rknn`：车牌识别 RKNN 模型。
- `plate_rec.onnx`：车牌识别 ONNX。
- `plate_rec_sim.onnx`：简化后的车牌识别 ONNX。
- `yolo11n.onnx`：YOLO ONNX。
- `dict.txt`：OCR 字典。
- `dataset.txt`：转换或量化数据列表。
- `convert_obb_640.py`、`convert_obb_640_fp16.py`：OBB 模型转换脚本。
- `onnx_to_rknn.py`：ONNX 到 RKNN 转换脚本。
- `main.cpp`、`CMakeLists.txt`：C++ 或 RKNN 示例/构建相关文件。

离线包：

- `offline_bundle`：给远程板部署用的离线包目录。
- `offline_bundle\rk3588_alpr_roadtest_bundle_20260701`：已解压的道路测试部署包。
- `offline_bundle\rk3588_alpr_roadtest_bundle_20260701.tar`
- `offline_bundle\rk3588_alpr_roadtest_bundle_20260701.tar.gz`
- `offline_bundle\README_ROAD_TEST.md`
- `offline_bundle\ROAD_TEST_OPERATOR_GUIDE.md`

SC850SL 探针脚本：

- `sc850_isp_probe.sh`：SC850 ISP 探针脚本。
- `sc850_video71_vehicle_probe_collect.sh`：当前主要用于远程板打包反馈的 `/dev/video71` ALPR 探针脚本。

SC850SL 反馈包和解包目录：

- `sc850_video71_vehicle_probe_20250626_111756.tar.gz`
- `sc850_video71_vehicle_probe_20250626_113214.tar.gz`
- `sc850_video71_vehicle_probe_20250626_144216.tar.gz`
- `sc850_video71_vehicle_probe_20250626_150317.tar.gz`
- `sc850_video71_vehicle_probe_20250626_103725.tar.gz`
- `sc850_video71_vehicle_probe_20250626_110254.tar.gz`
- `sc850_video71_vehicle_probe_20250626_112854.tar.gz`
- `sc850_video71_vehicle_probe_20250626_115610.tar.gz`
- `sc850_video71_vehicle_probe_20250626_123643.tar.gz`
- `sc850_video71_vehicle_probe_20250626_093419.tar.gz`
- `sc850_video71_recover_probe_20250626_130350.tar.gz`
- `sc850_video71_rkaiq_restart_probe_20250626_132231.tar.gz`
- `sc850_rkaiq_binding_probe_20250626_133404.tar.gz`
- `sc850_video71_after_reboot_probe_20250626_084815.tar.gz`
- `sc850_media_graph_probe_20250626_105135.tar.gz`
- `sc850_sensor_health_probe_20250626_110349.tar.gz`
- `sc850_sensor_health_probe_20250626_084905.tar.gz`
- `mediamtx_probe_20250626_085507.tar.gz`
- `mediamtx_live_probe_20250626_090155.tar.gz`
- `sc850_file_versions_20250626_092450.tar.gz`
- `sc850_old_behavior_short_probe_20250626_093419.tar.gz`
- `sc850_video71_upstream_probe_20250626_094644.tar.gz`
- `sc850_dt_gpio_power_probe_20250626_095237.tar.gz`
- `sc850_deep_dt_phandle_probe_20250626_095747.tar.gz`

这些包的作用：

- 每个包都是用户从远程 RK3588 板传回来的诊断结果。
- 包内通常包含 `run.log`、`run_summary.json`、`v4l2` 输出、`media-ctl` 输出、`dmesg`、`journalctl`、原始帧、预览 jpg、Top-K 结果等。
- 新对话应优先用这些包做事实依据，不要凭截图或记忆判断。

RK 运行结果：

- `runs_codex_mipi_debug_video_20260708`：本地 RK 内置视频测试结果。
- `mipi_color_probe`：MIPI 颜色或格式探针结果。
- `rk_*`、`runs_*`：不同实验输出目录，需按时间和 summary 判断用途。

---

## 6. 关键脚本参数和使用方式

### 6.1 `rk3588_topk_capture_mipi_debug_sc850.py`

重要参数：

- `--camera-device`：摄像头设备。SC850 主线使用 `/dev/video71`。
- `--mipi-fourcc`：像素格式，SC850 `/dev/video71` 主线用 `NV12`。
- `--mipi-color-mode`：颜色转换方式，SC850 `/dev/video71` 主线用 `nv12`。
- `--mipi-backend`：采集后端，当前常用 `v4l2ctl`。
- `--vehicle-source`：车辆候选来源，可选 `rknn`、`motion`、`hybrid`。
- `--detect-roi`：检测 ROI，避免全画面无效区域干扰。
- `--process-roi`：处理 ROI，用于裁剪实际道路区域。
- `--vehicle-detect-interval`：车辆检测间隔。
- `--vehicle-conf`：车辆检测阈值。
- `--ocr-engine`：OCR 引擎，可选 `none`、`hyperlpr3`、`rknn`。
- `--publish-frame`：发布浏览器预览图，常用 `/tmp/frame.jpg`。
- `--publish-interval`：发布间隔。
- `--progress-interval`：进度输出间隔。
- `--max-frames`：最大处理帧数。
- `--strict-plate-format` / `--no-strict-plate-format`：是否启用严格车牌格式过滤。

注意：

- 脚本默认 `--camera-device` 可能不是 `/dev/video71`，运行 SC850 实时主线时必须显式指定。
- 如果 `/dev/video71` 0 字节，先查 sensor 链路，不要先调 OCR。

### 6.2 `RK3588_dev/sc850_video71_vehicle_probe_collect.sh`

常用环境变量：

- `MAX_FRAMES=300`
- `MIN_PROCESS_VEHICLE_CONF=1.10`
- `OCR_ENGINE=none`
- `MIN_CHAR_VOTE_RATIO=0.65`
- `MIN_OCR_CONF=0.70`
- `MIN_LOCK_VEHICLE_CONF=0.70`
- `MIN_LOCK_CANDIDATE_SCORE=0.0`
- `MIN_LOCK_OBB_CONF=0.0`
- `STRICT_PLATE_FORMAT=0`
- `TIMEOUT_SECONDS=900`

典型用途：

- 跑一次 SC850 `/dev/video71` 道路画面探针。
- 自动打包反馈，减少截图沟通。
- 用户把 tar.gz 放回 `D:\YOLO_ALPR_Project\RK3588_dev` 后，本地解包分析。

重要说明：

- `OCR_ENGINE=none` 只用于检测车辆和车牌候选链路，不能作为真实 OCR 验收。
- `MIN_PROCESS_VEHICLE_CONF=1.10` 是故意卡掉所有车辆候选的诊断参数，不代表车辆检测没有输出。
- 如果要看 OCR，必须设置 `OCR_ENGINE=hyperlpr3`。

---

## 7. 已完成测试结果汇总

### 7.1 Windows 基准测试

事实：

- Windows 上 `alpr_topk_capture` 跑通过。
- 输出包含 Top-K 图片、summary、rejected 样本、track 目录。
- 结果目录：`captures_topk_codex_win_20260708\run_20260708_131529`

结论：

- Windows 基准流程可作为 OCR / Top-K / 投票策略参考。
- 不能机械复制到 RK，因为 RK 端受 NPU、MIPI、实时性和 sensor 链路限制。

### 7.2 本地 RK3588 IMX585 内置视频

事实：

- 本地板内置视频跑通过。
- 处理 1000 帧。
- 可锁定至少两个主要车牌。

结论：

- RKNN 车辆检测、车牌 OBB、HyperLPR3、Top-K、投票主链路可用。

### 7.3 远程 SC850SL 内置视频

事实：

- 用户反馈远程板内置视频识别也可以达到类似效果。

结论：

- 远程板的 Python / RKNN / OCR / Top-K 主流程不是当前最大问题。

### 7.4 SC850SL `/dev/video71` 早期成功阶段

#### `sc850_rkaiq_debug_20250626_142419`

事实：

- `/dev/video71` 曾能输出 NV12。
- 5 帧 raw 共约 60 MB。
- 3840x2160 30 FPS。
- dmesg 有 `sc850sl 4-0030: s_stream:1 3840x2160`。
- rkaiq media7 stream 正常。
- `rkisp1-vir1: first params buf queue` 出现。

结论：

- SC850SL 到 ISP 再到 `/dev/video71` 的链路曾经真实工作过。

#### `sc850_video71_vehicle_probe_20250626_111756`

事实：

- `/dev/video71` NV12 raw 单帧大小 12441600 bytes。
- `/tmp/frame.jpg` 被刷新。
- rkaiq media7 正常。
- vehicle raw / nms 有输出。
- `MIN_PROCESS_VEHICLE_CONF=1.10` 故意让车辆候选全部不过处理阈值。
- `track_count=0`。

结论：

- 这个包不能证明车辆检测失败，只能证明高阈值门控生效。

#### `sc850_video71_vehicle_probe_20250626_113214`

事实：

- `OCR_ENGINE=none`。
- 300 帧。
- 约 1.23 FPS。
- `vehicle_detections_raw=404`
- `vehicle_detections_nms=287`
- `vehicles_ready=193`
- `plate_attempts=193`
- `obb_candidates=43`
- `accepted_candidates=26`
- `ocr_skipped:none=26`
- `plate_detect_locks=26`

结论：

- SC850 实拍画面中车辆检测和车牌候选检测起量。
- 但因为 OCR 是 none，显示 `PLATE` / `LOCK PLATE` 只是占位，不能当成真实车牌识别。

#### `sc850_video71_vehicle_probe_20250626_144216`

事实：

- HyperLPR3 日志中出现 `[LOCK] track=20 plate=苏E8H8R5 frame=46 events=4`。
- 但 run 目录为空或缺少 summary / crops。

结论：

- 有过疑似 OCR lock，但缺少证据链，不能作为最终效果确认。

#### `sc850_video71_vehicle_probe_20250626_150317`

事实：

- 120 帧完成。
- 约 1 FPS。
- `vehicle_detections_raw=374`
- `vehicle_detections_nms=249`
- `plate_attempts=185`
- `obb_candidates=208`
- `ocr:hyperlpr3=69`
- `accepted_candidates=69`
- 无 `locked_text`。
- `track_49` 疑似 `粤E2KPA8`。
- `track_2` 存在 OCR 漂移。
- `track_25/27/29` 后缀稳定但省份漂移。

结论：

- SC850 实拍道路 + HyperLPR3 已经产生大量 OCR 候选。
- 投票锁定还不稳，需要格式过滤、阈值、ROI、车辆置信度和候选评分继续调。

### 7.5 OCR 调参阶段

#### `sc850_video71_vehicle_probe_20250626_103725`

事实：

- 120 帧。
- `ocr:hyperlpr3=15`
- 无 vote_events / locked_text。

推断：

- 可能画面里缺少足够近、足够清晰的可读车牌。

#### `sc850_video71_vehicle_probe_20250626_110254`

事实：

- 300 帧。
- 5 个 OCR vote。
- 无 lock。
- `track_42` 有接近格式的 `苏E69T60`，但被 `MIN_LOCK_VEHICLE_CONF=0.80` 卡住，vehicle_conf 约 0.765。
- `track_48` 有 `E377883`，被合理拦截。

结论：

- 锁定阈值过高可能阻止真实候选。
- 但不能简单放低所有阈值，否则会增加误锁。

#### `sc850_video71_vehicle_probe_20250626_112854`

事实：

- 车辆锁定阈值降到约 0.75。
- 只有 1 个低质量 vote：`沪V9MVF2`。
- 无 lock。

结论：

- 降阈值没有直接改善该批画面，也没有明显误锁。

#### `sc850_video71_vehicle_probe_20250626_115610`

事实：

- 300 帧完成。
- HyperLPR3 accepted OCR 31 个。
- 无 locked_text。
- `track_23` 真实蓝牌区域明显，但 OCR 出现 `粤189M14` 这类格式可疑文本。

结论：

- 需要严格车牌格式过滤，所以后续加入 `--strict-plate-format`。

### 7.6 加入严格格式过滤后的情况

代码侧事实：

- `rk3588_topk_capture_mipi_debug_sc850.py` 已加入 `--strict-plate-format`。
- 加入了中国车牌格式校验。
- 增加 `ocr_rejected:plate format` 统计。
- `python -m py_compile` 通过。

脚本侧事实：

- `sc850_video71_vehicle_probe_collect.sh` 增加 `STRICT_PLATE_FORMAT` 环境变量传入。
- 默认 `STRICT_PLATE_FORMAT=0`，不改变旧行为。

远程校验事实：

- 远程板上的 sc850 Python 和 sh 文件 hash 曾与本地一致：
  - py：`eb23c2df4ed89d2066d08c2655b65617cfbb5a636a9dac80eccba6be3e0f97f9`
  - sh：`1307fe364ba6bf559ad0bc6f6386d1a0ec7f8150524110d5e7a83893f2f967b7`

### 7.7 后续 `/dev/video71` 链路退化阶段

#### `sc850_video71_vehicle_probe_20250626_123643`

事实：

- 没有 run_summary。
- `video71_1f_nv12.raw` 0 bytes。
- `/tmp/frame.jpg` 是旧帧风险。
- ALPR 只打印 MIPI init，然后 timeout。

结论：

- 不是 OCR 或 Top-K 阶段卡住，而是 MIPI 输入无有效帧。

#### `sc850_video71_recover_probe_20250626_130350`

事实：

- 仍然 raw 0 或流失败。

结论：

- 简单恢复命令没有恢复 `/dev/video71`。

#### `sc850_video71_rkaiq_restart_probe_20250626_132231`

事实：

- 重启 rkaiq 后仍未恢复正常。

结论：

- 不能只归因于 rkaiq service。

#### `sc850_rkaiq_binding_probe_20250626_133404`

事实：

- rkaiq 绑定和 media graph 状态异常。

结论：

- rkaiq/media/sensor 链路存在更底层问题。

#### `sc850_video71_after_reboot_probe_20250626_084815`

事实：

- reboot 后仍异常。

结论：

- 不是单纯用户态进程残留问题。

#### `sc850_media_graph_probe_20250626_105135`

事实：

- dmesg 有 `sc850sl 4-0030: Unexpected sensor id(000000)`。
- media3 没有正常 SC850SL entity。
- rkcif-mipi-lvds4 terminal subdev 缺失。
- media7 退回 800x600 默认状态。

结论：

- sensor 没有被正常识别。

#### `sc850_sensor_health_probe_20250626_110349`

事实：

- 没有 ALPR 进程占用。
- `/dev/video71` raw 0。
- STREAMON 失败。
- I2C bus 4/5/7 没有 0x30 响应。
- sysfs 中 4-0030 / 5-0030 / 7-0030 更像 device-tree client，不代表真实 I2C 应答。
- dmesg 仍有 sensor id `000000`。

结论：

- 不是 ALPR 占用导致。
- 更像 sensor 没上电、reset 状态不对、排线/接口/模组连接问题、I2C 不通或板级供电问题。

#### `sc850_sensor_health_probe_20250626_084905`

事实：

- 与 110349 类似。
- I2C 0x30 仍不出现。

结论：

- 问题持续存在。

### 7.8 mediamtx / 推流工具验证

#### `mediamtx_probe_20250626_085507`

事实：

- 板上存在 `/root/mediamtx` 推流工具。
- 包含 `gstPushStream.sh`、`start_4_stream.sh`、`stop_4_stream.sh`、`receive_h264.sh`、`mediamtx.yml` 等。
- 历史日志显示它曾经能用 `/dev/video71` 推流。

#### `mediamtx_live_probe_20250626_090155`

事实：

- 当前 GST 推流失败，报 `not-negotiated`。
- RTSP 拉流 404。
- `rtsp_pull_8s.h264` 为 0。
- I2C 0x30 仍缺失。
- media7 仍 800x600。

结论：

- 推流工具不是根因。
- 因为底层 sensor 链路没恢复，推流也无法工作。

### 7.9 文件回滚和旧行为验证

#### `sc850_file_versions_20250626_092450`

事实：

- 远程目录没有找到 `.bak` / `.old` 可直接回滚的历史版本。
- 本地 offline bundle 只有通用脚本 `rk3588_topk_capture.py`、`rk3588_topk_capture_mipi_debug.py`。
- offline bundle 中没有原始 `rk3588_topk_capture_mipi_debug_sc850.py` 或 SC850 sh。

结论：

- 不能精确回到“换 sh 之前”的 SC850 文件状态。

#### `sc850_old_behavior_short_probe_20250626_093419`

事实：

- 使用 `STRICT_PLATE_FORMAT=0` 旧行为仍然 `/dev/video71` 0 帧。

结论：

- 当前 0 帧不是 strict format 改动导致。
- 问题在 ALPR 代码执行之前。

### 7.10 `/dev/video71` upstream / device-tree / GPIO 深查

#### `sc850_video71_upstream_probe_20250626_094644`

事实：

- `/dev/video71` 是 `rkisp1-vir1 mainpath`。
- 3840 和 800 stream 都失败。
- media7 退回 800x600。
- media3 有 rkcif-mipi-lvds4，但没有 SC850 sensor entity。
- I2C 0x30 absent。
- dmesg 有 reset gpio、power gpio/regulator 相关信息和 terminal subdev 缺失。

结论：

- `/dev/video71` 设备节点存在，但上游 sensor 没连上。

#### `sc850_dt_gpio_power_probe_20250626_095237`

事实：

- DT 中存在 `sc850sl-4@30`，compatible `smartsens,sc850sl`，reg `0x30`。
- DT 中 `sc850sl-4@30` 有 xvclk、reset-gpios、module index/name/lens/facing。
- 没有明确 power-gpios。
- regulator 看起来是 dummy 或缺省绑定。
- 还存在 `sc850sl-1@30`、`sc850sl-2@30` 等节点。
- debug gpio 中出现 reset 输出低电平；具体与 dmesg 中 gpio-39 的映射关系待确认。

结论：

- 设备树节点不是完全缺失。
- 更可能是实际供电、reset、I2C、接口或模组状态问题。

#### `sc850_deep_dt_phandle_probe_20250626_095747`

事实：

- `sc850sl-4@30` endpoint data-lanes 是 1 2 3 4。
- endpoint phandle `0x37` remote 到 `0x15f`。
- `0x15f` 对应 `csi2-dphy3/ports/port@0/endpoint@1`，并且 remote 回 `0x37`。
- pinctrl-0 `0x15e` 指向 `mipim0-camera2-clk`。
- reset `<0x129 7 1>` 对应 gpio1 offset7，即 gpio39。
- I2C4 pinctrl 是 `i2c4m3-xfer`。
- 但 I2C 0x30 仍 absent，sensor id 000000，media7 没有 SC850 upstream。

结论：

- 不优先怀疑 endpoint phandle 方向错误。
- 继续优先查硬件连接、供电、reset 和 I2C。

---

## 8. 我们做过哪些尝试

按阶段概括如下：

1. 建立 Windows 基准流程。
2. 建立 RK3588 板端视频流程。
3. 用本地 IMX585 板端内置视频验证 RK 主流程。
4. 将离线包打到远程 SC850SL 板子。
5. 用远程板内置视频确认 ALPR 主逻辑可运行。
6. 尝试 SC850SL MIPI 摄像头实拍道路识别。
7. 确认 `/dev/video71` 是 ISP 后处理目标端口。
8. 早期用 `/dev/video71` 抓到 NV12 raw，并跑出车辆检测、车牌候选和 OCR 候选。
9. 对 `ocr-engine none` 的假锁定做了澄清，明确它不是最终识别。
10. 分析 `111756` 包，确认高阈值导致 track 为 0。
11. 分析 `113214` 包，确认车辆和车牌候选链路起量，但 OCR 是 none。
12. 分析 `144216` 包，看到疑似 lock 日志但证据链不足。
13. 分析 `150317` 包，确认 HyperLPR3 候选很多但投票不稳定。
14. 分析 `103725`、`110254`、`112854`、`115610`，逐步定位 OCR 候选质量、阈值和格式问题。
15. 在 `rk3588_topk_capture_mipi_debug_sc850.py` 增加 `--strict-plate-format`。
16. 在 `sc850_video71_vehicle_probe_collect.sh` 增加 `STRICT_PLATE_FORMAT` 透传。
17. 用 hash 确认远程 py 和 sh 与本地一致。
18. 发现 `/dev/video71` 后续突然 0 字节或 STREAMON 失败。
19. 多次通过 recover、rkaiq restart、binding、after reboot 排查用户态和 rkaiq 层。
20. 检查 media graph，发现 SC850 sensor entity / terminal subdev 不正常。
21. 检查 sensor health，发现 I2C 0x30 不响应、sensor id 000000。
22. 检查 mediamtx 推流工具，确认当前推流也失败，不是 ALPR 独占问题。
23. 尝试回到旧行为，确认 strict format 不是 0 帧原因。
24. 深查 `/dev/video71` upstream、DT、GPIO、phandle，确认设备树链路大体存在但 sensor 实际未响应。
25. 用户已经重新插拔 SC850SL 模组，下一步要验证重插后 I2C 和 `/dev/video71` 是否恢复。

---

## 9. 当前关键限制和不能随便改的决定

### 9.1 不能改的主线决定

- `/dev/video71` 是 SC850SL ISP 后处理主端口，当前不再用 `/dev/video53` 替代主线。
- `alpr_topk_capture.py` 是 Windows 基准主线，不随便改。
- Windows 新实验优先用 `alpr_topk_capture_demo.py`。
- RK 实时识别不能机械复制 Windows 逻辑。
- OCR 主推 HyperLPR3，`none` 只作诊断。
- `PLATE` 只是占位，不是真识别。
- SC850 当前 0 帧问题优先按 sensor 链路查，不按 ALPR 逻辑查。

### 9.2 风险操作限制

- 不要随意改 device-tree、GPIO、reset、电源相关配置。
- 不要随意 toggle reset GPIO，除非用户明确同意并已做好物理风险接受。
- 不要继续大量跑 ALPR 长任务，直到 `/dev/video71` 单帧恢复。
- 不要只看浏览器旧图判断链路恢复。
- 不要把旧的 `/tmp/frame.jpg` 当作当前帧。

### 9.3 文件更新规则

- 完成重要工作后，同步更新 `PROJECT.md`、`STATUS.md`、`DECISIONS.md`、`HANDOFF.md`。
- 只有工作规则变化时才更新 `AGENTS.md`。
- 信息不确定写“待确认”。

---

## 10. 新对话接手后的第一步

因为用户最后反馈“我现在已经重插了”，新对话第一步应先验证重插后的 SC850SL sensor 是否重新上线。

### 10.1 最小快速检查

让用户在远程板终端执行：

```bash
i2cdetect -y -r 4
dmesg | tail -n 300 | grep -Ei 'sc850|0030|sensor id|terminal|rkcif-mipi-lvds4|rkisp1|isp input'
```

判断：

- 如果 I2C 表里出现 `30` 或 `UU`，说明 sensor 至少可能重新被看到。
- 如果仍然没有 `30` / `UU`，并且 dmesg 仍是 sensor id `000000`，则优先继续查硬件、供电、reset、I2C 和模组连接。

### 10.2 `/dev/video71` 单帧检查

如果 I2C 有恢复迹象，再执行：

```bash
timeout 8 v4l2-ctl -d /dev/video71 \
  --set-fmt-video=width=3840,height=2160,pixelformat=NV12 \
  --stream-mmap=3 \
  --stream-count=1 \
  --stream-to=/tmp/video71_test.raw
ls -l /tmp/video71_test.raw
```

判断：

- 期望大小：12441600 bytes。
- 如果是 0 bytes，说明 `/dev/video71` 仍未恢复。
- 如果成功，再考虑跑 ALPR。

### 10.3 建议的打包反馈方式

如果需要减少截图沟通，建议让用户执行一个新的 post-replug probe，并把 tar.gz 传回 `D:\YOLO_ALPR_Project\RK3588_dev`。

可用命令：

```bash
TAG=$(date +%Y%m%d_%H%M%S)
BASE=/tmp/sc850_after_replug_probe_$TAG
mkdir -p "$BASE"

date > "$BASE/date.txt"
ps -ef | grep -E 'rkaiq|rk3588_topk|v4l2-ctl|http.server|gst|mediamtx' | grep -v grep > "$BASE/process.txt" 2>&1 || true
systemctl status rkaiq_3A.service --no-pager > "$BASE/rkaiq_status.txt" 2>&1 || true
journalctl -u rkaiq_3A.service -n 300 --no-pager > "$BASE/rkaiq_journal.txt" 2>&1 || true

for b in 4 5 7; do
  i2cdetect -y -r "$b" > "$BASE/i2c_bus_${b}.txt" 2>&1 || true
done

v4l2-ctl --list-devices > "$BASE/v4l2_list_devices.txt" 2>&1 || true
v4l2-ctl -d /dev/video71 --all > "$BASE/video71_all.txt" 2>&1 || true
v4l2-ctl -d /dev/video71 --list-formats-ext > "$BASE/video71_formats.txt" 2>&1 || true

for m in /dev/media0 /dev/media1 /dev/media2 /dev/media3 /dev/media4 /dev/media5 /dev/media6 /dev/media7; do
  [ -e "$m" ] && media-ctl -d "$m" -p > "$BASE/$(basename "$m").txt" 2>&1 || true
done

timeout 8 v4l2-ctl -d /dev/video71 \
  --set-fmt-video=width=3840,height=2160,pixelformat=NV12 \
  --stream-mmap=3 \
  --stream-count=1 \
  --stream-to="$BASE/video71_1f_nv12.raw" \
  > "$BASE/video71_stream_3840.log" 2>&1 || true
ls -l "$BASE/video71_1f_nv12.raw" > "$BASE/video71_raw_size.txt" 2>&1 || true

dmesg | tail -n 500 > "$BASE/dmesg_tail_500.txt" 2>&1 || true
dmesg | grep -Ei 'sc850|0030|sensor id|terminal|rkcif-mipi-lvds4|rkisp1|isp input|reset|gpio|i2c' > "$BASE/dmesg_sc850_related.txt" 2>&1 || true

tar -czf "$BASE.tar.gz" -C /tmp "$(basename "$BASE")"
echo "$BASE.tar.gz"
```

用户传回后，新对话应分析：

- `i2c_bus_4.txt`
- `video71_raw_size.txt`
- `video71_stream_3840.log`
- `media7.txt`
- `media3.txt`
- `dmesg_sc850_related.txt`
- `rkaiq_status.txt`
- `rkaiq_journal.txt`

### 10.4 如果 `/dev/video71` 恢复后的 ALPR 命令方向

恢复条件：

- I2C 0x30 可见。
- `/dev/video71` 单帧 NV12 raw = 12441600 bytes。
- media graph 出现合理 SC850 upstream。

恢复后再跑类似：

```bash
cd /root/alpr_topk_rk3588
OCR_ENGINE=hyperlpr3 \
STRICT_PLATE_FORMAT=1 \
MAX_FRAMES=300 \
VEHICLE_SOURCE=rknn \
MIN_LOCK_VEHICLE_CONF=0.75 \
MIN_CHAR_VOTE_RATIO=0.65 \
MIN_OCR_CONF=0.70 \
bash ./sc850_video71_vehicle_probe_collect.sh
```

注意：

- 具体 env 名称以远程板当前 `sc850_video71_vehicle_probe_collect.sh` 为准。
- 如果脚本不接受某 env，需要先读脚本再下命令。
- 如果用户希望实时看输出，不要把整个运行包在完全静默后台；应保留终端进度，同时最后 tar 打包。

---

## 11. 当前最重要的判断树

```text
用户已重插 SC850SL
|
+-- I2C bus 4 是否出现 0x30 / UU？
|   |
|   +-- 否：
|   |   继续查物理连接、供电、reset、I2C、模组方向、接口。
|   |   不要继续调 ALPR。
|   |
|   +-- 是：
|       继续测 /dev/video71 3840x2160 NV12 单帧。
|
+-- /dev/video71 单帧是否 12441600 bytes？
|   |
|   +-- 否：
|   |   查 media graph、rkaiq、ISP 绑定、sensor stream。
|   |
|   +-- 是：
|       开始短帧 ALPR probe，先 120/300 帧。
|
+-- ALPR 是否有 vehicle + plate + OCR？
    |
    +-- vehicle 无：
    |   查 ROI、颜色转换、曝光、画面范围、vehicle rknn 输入。
    |
    +-- plate/OCR 不稳：
        调 strict format、vote、ROI、车辆置信度、候选评分，保存 rejected 样本分析。
```

---

## 12. 下一位 AI 最容易犯的错误

- 看到浏览器有旧画面就以为摄像头恢复。
- 看到 `PLATE` 就以为真实识别完成。
- 忽略 `/dev/video71` raw 0 bytes。
- 忽略 I2C 0x30 absent。
- 把 `/dev/video53` 当主线替代 `/dev/video71`。
- 继续调 OCR 参数而不先确认 sensor 出帧。
- 直接让用户截图，而不是让用户执行命令并传回 tar.gz。
- 未读 `sc850_video71_vehicle_probe_collect.sh` 就假设 env 参数存在。
- 未读 tar 包内容就凭文件名下结论。
- 随意修改 Windows 基准主线 `alpr_topk_capture.py`。

---

## 13. 给新对话的简短接手口径

可以这样开始：

> 我先接上当前状态：Windows 和 RK 内置视频主流程已经跑通，远程 SC850SL 的 ALPR 主程序也在内置视频上证明可用。当前卡点不是 OCR 或 Top-K，而是 SC850SL 实拍链路在 `/dev/video71` 上后续变成 0 字节 / STREAMON 失败 / I2C 0x30 不响应。你已经重插了模组，所以第一步我会先让你打包一个 post-replug probe，确认 I2C 0x30、media graph 和 `/dev/video71` 单帧是否恢复；恢复后才继续跑 ALPR。

---

## 14. 当前状态一句话

当前不是“识别算法从零开始”，而是“识别主流程已基本具备，SC850SL `/dev/video71` 实时摄像头链路曾经跑出候选和 OCR，但后来 sensor/I2C/ISP 链路异常；用户已重插模组，下一步必须先验证 sensor 是否重新上线”。

---

## 15. 2026-07-10 重插后的最新反馈

用户已在远程板执行：

```bash
i2cdetect -y -r 4
dmesg | tail -n 300 | grep -Ei 'sc850|0030|sensor id|terminal|rkcif-mipi-lvds4|rkisp1|isp input'
```

截图事实：

- I2C bus 4 扫描结果全是 `--`，没有出现 `0x30` 或 `UU`。
- dmesg 中持续出现 `rkcif_update_sensor_info: stream[...] get remote terminal sensor failed!`。
- 日志中出现 `rkcif-mipi-lvds4` 相关失败。
- 日志末尾出现 `rkisp1-vir1: check rkisp_mainpath link or isp input`。

结论：

- 重插后，SC850SL 仍未在 I2C4 上正常应答。
- `/dev/video71` 的 ISP mainpath 上游仍没有正常 sensor input。
- 当前仍不应继续跑 ALPR、OCR 或 Top-K 调参；必须继续查 sensor 物理连接、供电、reset、I2C bus、模组方向、接口和必要的冷启动/重新 probe。

建议下一步：

1. 先做一次远程板冷重启，而不是只热插拔。
2. 冷重启后重新执行 I2C4 扫描和 `/dev/video71` 单帧 NV12 检查。
3. 如果 I2C4 仍没有 `0x30/UU`，优先让现场确认模组排线方向、接口座、供电、reset 和是否插在与 device-tree `sc850sl-4@30` 对应的物理口。
