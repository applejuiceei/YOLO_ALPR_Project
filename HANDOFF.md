# 新 AI 接手说明

更新时间：2026-08-14

## 阅读顺序

新 AI 接手本项目时，请按以下顺序阅读：

1. `AGENTS.md`：先读规则、红线、协作方式。
2. `NEW_CHAT_HANDOFF_20260814.md`：当前全局最新接手总览，覆盖 Windows 原速纯识别、HyperLPR3 性能、PP-OCR和RK/SC850SL。
3. `NEW_CHAT_HANDOFF_20260717.md`：需要继续 RK3588/SC850SL 真实道路专项时阅读。
4. `PROJECT.md`：确认项目目标、需求、验收标准和不能改的内容。
5. `STATUS.md`：确认当前完成情况、卡点和下一步。
6. `DECISIONS.md`：理解关键技术决定和原因。
7. `REMOTE_CODEX_HANDOFF.md`：远程 Windows 协作历史和传输清单。
8. `PROJECT_HANDOFF.md`、`NEW_CHAT_HANDOFF_20260708.md`、`NEW_CHAT_HANDOFF_20260710.md`：仅作历史背景。
9. 相关脚本源码：只读当前任务相关文件，不要一上来全局乱改。

## 当前状态

- 已新增 `NEW_CHAT_HANDOFF_20260708.md`，用于新开对话快速接手当前项目和本轮 SC850SL 实时调试结论。
- Windows Top-K + HyperLPR3 主线已经成型。
- RK3588 视频文件识别和离线部署已跑通。
- 去模糊模型已训练完成，但仍处于 Windows demo/离线评估阶段。
- 新线下测试板实际摄像头为 SC850SL，不是 IMX585。
- `/dev/video33` 已确认可输出 SC850SL BG10 RAW10 原始帧，并能生成灰度道路预览。
- `/dev/video44` RKISP mainpath 输出仍未通，报 `check rkisp_mainpath link or isp input`。
- 灰度整图和低阈值测试均为 `tracks=0`，当前判断是远景车辆在整图缩放后太小。
- `rk3588_topk_capture.py` 已新增 `--detect-roi`，用于 vehicle RKNN 前裁剪放大道路区域。
- `rk3588_topk_capture_mipi_debug.py` 是更新的 MIPI 调试参考脚本；不要直接改它。
- SC850SL 适配副本是 `rk3588_topk_capture_mipi_debug_sc850.py`，已加入 RAW10 灰度和检测前 ROI。
- 浏览器实时预览已经能看到远程 SC850SL 当前画面，说明 `/tmp/frame.jpg` 发布链路可用。
- 单块检测 ROI 1000 帧仍为 `tracks=0`；分块 ROI 后模型开始输出框，但画面观察显示主要是假阳性。
- `rk3588_topk_capture_mipi_debug_sc850.py` 已新增 `--detect-roi-tiles` / `--detect-roi-overlap`；300 帧低阈值测试中 boxes/plate attempts 已出现，但主要框在广告牌/灯箱/路边结构上，不是真实车辆。
- 2026-07-04 白天画面显示夜间曝光参数严重过曝，大片接近纯白；白天测试要先降低 SC850SL `exposure`，再继续调 ROI/vehicle/plate。
- 第一次白天曝光扫描截图均显示 `frame:500`，疑似 `/tmp/frame.jpg` 未刷新；后续曝光测试需先保持采集程序运行，或检查 `/tmp/frame.jpg` 修改时间/MD5 是否变化。
- 实时刷新后，白天 `exposure=380` 画面已有可用层次，可先作为日间候选曝光跑检测；右侧和白色物体仍有高光溢出。
- 白天实时测试显示运动车辆仍无法稳定框住；完整脚本约 `1 fps`，当前需先做车辆框专用测试，跳过车牌阶段并收窄 ROI。
- `rk3588_topk_capture_mipi_debug_sc850.py` 已新增 `--vehicle-source motion|hybrid`；`motion` 用背景差分生成固定机位运动目标候选，适合先验证运动真车框。
- 远程 SC850SL 实测中 `motion` 已能框到真实汽车，但也会框到电动车、车轮等非汽车运动目标。
- `rk3588_topk_capture_mipi_debug_sc850.py` 已新增 `--motion-min-aspect`、`--motion-min-fill-ratio`、`--motion-accept-roi`，用于过滤过瘦/过碎/非车道内的运动框。
- 2026-07-06 用户本地 IMX585 RK3588 板已重跑 `/root/deploy/144.mp4` 1000 帧回归：约 10 FPS，锁定 `冀JC5210` 和 `冀B6R9F9`，结果目录 `/root/alpr_topk_rk3588/runs_video_selftest_codex/run_20260706_031136`。
- 2026-07-06 用户确认远程 SC850SL 板运行同一内置场地视频时，识别表现与本地 IMX585 板一致，可正常显示彩色视频并锁定 `冀JC5210`。
- 当前最重要的工程判断已更新：SC850SL 板端主流程没有坏，实时失败集中在 SC850SL 摄像头输入图像域和 RKISP 链路；`/dev/video33` RAW10 灰度只作为临时调试/救生绳，不应视为最终路线。
- 已创建 `RK3588_dev/sc850_isp_probe.sh`，远程板运行后会生成 `/tmp/sc850_isp_probe_*` 证据包，用于判断 `/dev/video44`/RKISP 输出链路断点。
- 用户已将远程探针包传回并解压到 `RK3588_dev/sc850_isp_probe_20250626_124614`。
- 探针包显示 `/dev/video44` 属于 `rkisp0-vir0`，默认/能力仅 `800x600`，不是 SC850SL 4K ISP 主输出；不要继续把 `/dev/video44` 当成 SC850SL 的主判断节点。
- 探针包显示 `/dev/video53` 确实是 ISP mainpath，但它属于 `rkisp0-vir2`，上游是 `rkcif-mipi-lvds2/SRGGB12_1X12`，不是 SC850SL 已确认的 `rkcif-mipi-lvds4/SBGGR10_1X10` 链。
- 探针包显示 `/dev/video71` 属于 `rkisp1-vir1` 的 `rkisp_mainpath`，支持 `NV12/UYVY` 到 `3840x2160`，且 media graph 链接到 SC850SL 所在 `rkcif-mipi-lvds4`；`/dev/video-camera0 -> video71`，下一步优先测试它。
- `RK3588_dev/sc850_isp_probe.sh` 已更新，包含 `/dev/video53`、`/dev/video71` 和 `/dev/video72` 的标准 YUV 短流测试。
- 用户手动测试 `/dev/video71` 4K `NV12` 时 `VIDIOC_STREAMON returned 0 (Success)`，但输出 raw 仍为 0 字节；dmesg 报 `rkisp1-vir1: waiting on params stream event timeout` 和 `rkisp1-vir1: can not get first iq setting in stream on`。
- 已确认 `rkaiq_3A.service` active/running，进程为 `/usr/bin/rkaiq_3A_server`，并且 `/etc/iqfiles` 下存在 `sc850sl_GC_12MM.json` 与 `sc850sl_2L_GC_12MM.json`。
- 当前关键推断：rkaiq 服务不是没启动，IQ 文件也不是完全缺失；更可疑的是 rkaiq 日志显示 `/dev/media5: wait stream start event...`，而 SC850SL ISP 链路是 `/dev/media7 -> /dev/video71`。下一步应检查 `/etc/init.d/rkaiq_3A.sh` 和 systemd service 如何选择 media/camera。
- 最新检查显示 `rkaiq_3A.service` 只是调用 `/etc/init.d/rkaiq_3A.sh start`，脚本无参数启动 `/usr/bin/rkaiq_3A_server`；cmdline 中没有显式 media/IQ/camera 参数。fd 列表能看到 `/dev/v4l-subdev7` 和 `/dev/v4l-subdev8`，说明 rkaiq 至少打开过 SC850SL 相关 subdev，但是否打开 `/dev/media7` 和是否对 `/dev/video71` 收到 stream event 仍待确认。
- 已分析 `RK3588_dev/sc850_rkaiq_debug_20250626_142419.tar.gz`：`/dev/video71` 4K `NV12` 已成功出帧，5 帧约 60 MB，约 30 FPS；rkaiq 日志确认 `/dev/media7` stream start/stop event success，dmesg 出现 `rkisp1-vir1: first params buf queue`。当前应把 SC850SL 实时输入从 `/dev/video33` RAW10 灰度切到 `/dev/video71` 标准 `NV12`。
- 已创建 `REMOTE_CODEX_HANDOFF.md`，专门用于远程 Windows 新 Codex 快速接手，包含文件传输清单、项目总结、关键结论、已做尝试和推荐下一步。

## 接手后的第一步

如果用户没有给出新的明确任务，第一步应是围绕 SC850SL 实时摄像头输入继续推进，优先修正常 ISP 彩色/YUV 输出；灰度 RAW10 仅作临时对照：

1. 在远程 SC850SL 板用 `/dev/video71` 抓取 1-5 帧 `NV12` 并转 jpg，确认 ISP 画面质量。
2. 如果画面正常，把实时 ALPR 摄像头输入从 `/dev/video33` RAW10 灰度切到 `/dev/video71`：`--mipi-fourcc NV12 --mipi-color-mode nv12`。
3. 跑实时道路测试并观察 `/tmp/frame.jpg`、FPS、vehicle hits、plate hits、OCR 结果和 run 目录。
4. 只有 `/dev/video71` 再次不稳定或画面质量不可用时，才临时回退 `/dev/video33` RAW10 灰度 + motion/ROI。

## 常用路径

Windows 项目根目录：

```text
D:\YOLO_ALPR_Project
```

Windows 测试视频：

```text
D:\YOLO_ALPR_Project\测试图\14.mp4
```

RK 板端主目录：

```bash
/root/alpr_topk_rk3588
/root/deploy
```

RK 测试视频：

```bash
/root/deploy/144.mp4
```

新板 IP：

```text
192.168.8.88
```

原板 IP：

```text
192.168.137.168
```

## 注意事项

- `/tmp/frame.jpg` 可能是旧帧，不能单独证明识别程序正在运行。
- `stream.py` 只负责浏览器展示，不负责采集或识别。
- 浏览器画面中 `veh:0` 或终端 `vehicle_boxes=0` 表示 vehicle YOLO 未框车，后续 plate/OCR 不会触发。
- 画面大片纯白时不要继续调模型阈值，先降低 `exposure`；过曝会让真实车辆和车牌纹理丢失。
- `ocr-engine none` 和 `PLATE` 是诊断模式，不是最终目标。
- `mipi_plate_scan_only` 是诊断模式，不是最终目标。
- 最终目标是车牌号显示在对应车辆上方，并跟随车辆直到 YOLO/预测跟踪失效。
- MIPI 出图前，板端道路实测无法真正开始。
- 现在 SC850SL RAW10 已能出图，但 RKISP 输出还未修通；不要再把 `/dev/video53` 当作新板正确摄像头节点。
- 信息不确定时写“待确认”，不要补脑。

## 待确认

- 是否需要额外创建 `PR0JECT.md`。
- 新板是否能从当前 Codex 所在机器直连。
- `/dev/video33` RAW10 灰度输入下 ALPR 的实际识别效果；但该路径只作为临时方案，最终仍需确认正常 ISP 输出或灰度域模型适配方案。
- `/dev/video44` RKISP 输出链路的缺失配置。
## 2026-07-10 接手补充

新开对话请优先阅读 `NEW_CHAT_HANDOFF_20260710.md`。该文件已经整合本轮对话中的项目目标、文件结构、关键脚本、SC850SL `/dev/video71` 历次 probe 结论、已尝试方案和用户重插模组后的第一步检查。

接手后的第一步：不要直接调 OCR 或 Top-K，先让用户在远程板验证 I2C 0x30、media graph 和 `/dev/video71` NV12 单帧是否恢复。

补充最新反馈：用户重插后截图显示 I2C4 仍无 `0x30/UU`，dmesg 仍报 remote terminal sensor failed 和 rkisp mainpath/isp input 异常。新对话应继续按 sensor/供电/reset/I2C/物理连接方向排查，暂不进入 ALPR 调参。

## 2026-07-10 推流恢复后接手补充

最新状态：
- 用户通过 `/root/mediamtx/start_4_stream.sh` 成功推出 `/dev/video71` RTSP 流，VLC 可见真实道路画面。
- dmesg 截图显示 `Detected sc850sl id 009d1e`，说明 SC850SL 已至少在该次启动中恢复 sensor id 和推流链路。
- 现在不要继续沿“sensor 一直离线”旧判断推进；应转为验证 ALPR 直接采集 `/dev/video71` 是否可用。
- 由于 mediamtx/GStreamer 会占用 `/dev/video71`，跑 ALPR 前先执行 `cd /root/mediamtx && ./stop_4_stream.sh`，再做 `v4l2-ctl` 单帧 NV12 检查。
- 本机 Windows 2026-07-10 短跑 `alpr_topk_capture.py` 120 帧可运行，但当前 Windows 环境 HyperLPR3/onnxruntime 不可用；不要把该轮当 OCR 效果回归。
- 用户本地 IMX585 RK3588 板 2026-07-10 跑 `/root/deploy/144.mp4` 1000 帧通过，锁定 `冀JE5210` 和 `冀B6R9F9`，输出 `/root/alpr_topk_rk3588/runs_codex_imx585_video_20260710/run_20260710_053723`。

接手第一步：
1. 远程 SC850SL 板先停止 mediamtx/GStreamer 推流。
2. 直接用 `v4l2-ctl` 从 `/dev/video71` 抓 3840x2160 NV12 单帧，确认 raw size 为 `12441600`。
3. 若成功，再运行 `rk3588_topk_capture_mipi_debug_sc850.py` 的短帧数 ALPR probe；若失败，再回查当前是否仍有推流进程占用、media7/rkaiq/dmesg 状态。

## 2026-08-05 Windows 异步实时脚本

新增脚本：

```text
D:\YOLO_ALPR_Project\alpr_realtime_async.py
```

推荐速度优先命令（按源文件 24 FPS 原速播放，按 `R` 开始/暂停后台识别）：

```powershell
D:\miniconda\envs\alpr_env\python.exe .\alpr_realtime_async.py `
  --video "D:\YOLO_ALPR_Project\测试图\14.mp4" `
  --pipeline vehicle `
  --plate-stage off `
  --ocr-engine hyperlpr3 `
  --tracking none `
  --recognition-initial-state off `
  --show-video
```

更高召回但更慢的模式：将 `--plate-stage off` 改为 `--plate-stage fallback`；需要 track ID 时将 `--tracking none` 改为 `--tracking iou`。

运行控制：

- `R`：开始/暂停后台识别。
- `Q` 或 `Esc`：退出。
- `--recognition-start-frame N` / `--recognition-stop-frame N`：按帧自动开关。
- `--control-file D:\YOLO_ALPR_Project\recognition.control`：允许外部写入 `on`、`off` 或 `quit`。

输出：

```text
D:\YOLO_ALPR_Project\runs_realtime_async\run_时间戳\recognition_results.jsonl
D:\YOLO_ALPR_Project\runs_realtime_async\run_时间戳\summary.json
```

关键验证：

- `测试图\14.mp4` 实际为 `1920x1080 @ 24 FPS`，默认自动按 24 FPS 原速播放。
- 650 帧速度优先测试：视频 `24.011 FPS`、后台识别 `9.265 FPS`，识别到 `冀B6R9F9`（frame 594，置信度 `0.9977`）。
- 单槽缓冲会替换识别来不及处理的旧帧，这是保持低延迟和视频原速的设计，不是丢帧故障。
- 当前 Windows 为 CPU-only；plate OBB 是已观察到的主要重开销。不要在没有 ONNX/OpenVINO A/B 前直接判断必须改写 C++。

## 2026-08-06 轻量核心源码远端

远端仓库：

```text
http://47.102.197.116:3000/gcvision_admin/PLR-Test
```

分支与提交：

```text
main
37580c306a9b9f5132dde07218c7d89e9d410680
```

远端只包含 `.gitignore`、`README.md`、`requirements.txt` 和 4 个 Windows 核心 Python 文件。模型、视频、运行结果、RK 脚本、项目内部记忆和凭据均未上传。独立发布工作区位于：

```text
D:\YOLO_ALPR_Project\_publish\PLR-Test
```

## 2026-08-07 查看 HyperLPR3 毫秒耗时

当前本地主程序默认有效置信度为 `0.50`。推荐命令：

```powershell
D:\miniconda\envs\alpr_env\python.exe .\alpr_realtime_async.py `
  --video "D:\YOLO_ALPR_Project\测试图\14.mp4" `
  --output "D:\YOLO_ALPR_Project\runs_realtime_ocr_history" `
  --pipeline vehicle `
  --plate-stage off `
  --ocr-engine hyperlpr3 `
  --tracking iou `
  --dedupe-seconds 0 `
  --min-ocr-conf 0.50 `
  --recognition-initial-state on `
  --show-video
```

终端 `[OCR_SPEED]` 中：`ocr_ms` 是单次 HyperLPR3，`total_ms` 是后台整帧，`end_to_end_ms` 是帧提交到结果完成。JSONL 保存相同字段；`summary.json` 的 `average_ocr_ms` 是本轮所有 OCR 调用的平均耗时。

## 2026-08-07 HyperLPR3 纯识别离线 A/B

脚本：

```text
D:\YOLO_ALPR_Project\benchmark_hyperlpr3_recognition.py
```

默认运行命令：

```powershell
D:\miniconda\envs\alpr_env\python.exe .\benchmark_hyperlpr3_recognition.py
```

脚本只读18组现有 `vehicle_rank`/`plate_rank` 样本，为每次运行新建结果目录，输出 `results.json` 和 UTF-8 BOM 的 `results.csv`。可用 `--input-run`、`--output`、`--warmup` 和 `--repeats` 调整。

完整基准结果：`runs_hyperlpr3_recognition_ab/run_20260807_170904`。纯识别 `P50=81.616 ms`、`P95=186.169 ms`，ONNX 推理是明确瓶颈；预处理和解码各约0.2ms。18组无运行错误，`冀B6R9F9` 在 track 4/rank 2 正确命中，但整体一致率不足，因此尚未接入 `alpr_realtime_async.py`。

## 2026-08-08 PP-OCRv4 Mobile 交接

入口说明：

```text
D:\YOLO_ALPR_Project\ppocr_plate\README.md
```

当前已完成 100 步 CPU 结构冒烟，运行目录：

```text
D:\YOLO_ALPR_Project\runs_ppocr_plate_train\smoke_20260808_092616
```

- 训练在约 17 分钟内达到 `global_step=100`，并保存 `latest.pdparams`。
- Paddle 推理模型位于该目录的 `inference` 子目录；已实跑确认输入 `(1,3,48,160)`、输出 `(1,20,77)`。
- 该模型是随机初始化后的短训产物，只验证链路，不得用于准确率或部署性能结论。
- 字典真实契约为 76 个非 blank 字符加一个 CTC blank；API 接收 BGR crop，模型 tensor 为 RGB。
- 正式 `train` 会读取 `audit.json` 并拒绝缺少 10 万公开/合成样本、2000/500/500 `real_verified`、许可证记录、哈希检查或存在 group 泄漏的数据。

继续正式训练前依次完成：人工构建并审计数据；下载官方 `ch_PP-OCRv4_rec_train` checkpoint；在 GPU 环境执行 README 的 `train` 命令。训练后再依次做 Paddle/ONNX parity、ONNX Runtime、OpenVINO FP32/INT8、RKNN FP16/INT8 和跨后端一致性测试。

通用 `plate_rec_sim.onnx` 的纠正基准位于：

```text
D:\YOLO_ALPR_Project\runs_plate_rec_sim_corrected\run_20260808_094939
```

其 4 线程 1000 次总耗时 `P50=47.30 ms`、`P95=79.76 ms`，瓶颈为 ONNX 推理；18 张仅 1 张符合车牌格式，不能作为专用模型替代。历史 summary 只统计 agreement，不是真值，也不进入质量 gate。

## 2026-08-11 HyperLPR3 纯车牌目录基准

脚本：

```text
D:\YOLO_ALPR_Project\benchmark_hyperlpr3_image_dir.py
```

复现命令：

```powershell
D:\miniconda\envs\alpr_env\python.exe .\benchmark_hyperlpr3_image_dir.py `
  --input-dir "D:\YOLO_ALPR_Project\Dataset\dataset\test\sharp" `
  --output "D:\YOLO_ALPR_Project\runs_hyperlpr3_image_dir" `
  --warmup 50 --repeats 1
```

正式结果目录：

```text
D:\YOLO_ALPR_Project\runs_hyperlpr3_image_dir\run_20260811_112914
```

1041张均为350×150且可解码。完整接口总耗时 `P50=78.266 ms`、`P95=210.520 ms`，输出率74.83%；纯识别端到端 `P50=26.034 ms`、`P95=43.254 ms`、平均28.206ms，输出率100%，格式合法率97.21%。纯识别的主要瓶颈是 ONNX 推理。目录无人工标签，输出率、格式合法率、高置信度和两路文本一致率均不等于真实准确率。

建议链路为：plate OBB → 透视拉正 → 可选 `hyperlpr3-rec` → 格式/置信度过滤 → 同车多帧投票。双层牌仍需完整接口或单独的双层处理逻辑；在人工真值 A/B 通过前，不替换默认 OCR。

## 2026-08-11 HyperLPR3 完整接口阶段计时

脚本与正式结果：

```text
D:\YOLO_ALPR_Project\benchmark_hyperlpr3_full_stages.py
D:\YOLO_ALPR_Project\runs_hyperlpr3_full_stages\run_20260811_114704
```

复现命令：

```powershell
D:\miniconda\envs\alpr_env\python.exe .\benchmark_hyperlpr3_full_stages.py `
  --input-dir "D:\YOLO_ALPR_Project\Dataset\dataset\test\sharp" `
  --output "D:\YOLO_ALPR_Project\runs_hyperlpr3_full_stages" `
  --warmup 50 --repeats 1
```

主结论：公共总耗时`P50=79.474 ms/P95=205.369 ms`。检测每图合计`P50=13.053 ms`；OCR仅在825张候选图上执行，其条件合计`P50=61.531 ms`；分类仅执行717次，条件合计`P50=1.715 ms`；透视拉正条件`P50=1.229 ms`。平均总耗时中OCR占60.85%、检测占32.68%。

注意：OCR/分类/透视是条件阶段，不能把各自P50直接相加。`results.json`同时保存per-input与per-invocation统计，`stage_latencies.csv`保存每张图阶段总账。检测后处理实际沿用HyperLPR3源码函数默认阈值`confidence=0.25`、`IoU=0.5`；本次只计时，没有顺手改阈值。

## 2026-08-11 单张纯识别命令

```powershell
D:\miniconda\envs\alpr_env\python.exe .\hyperlpr3_recognize_once.py `
  --image "D:\YOLO_ALPR_Project\Dataset\dataset\test\sharp\grab10003.jpg" `
  --warmup 20 --show
```

不需要窗口时去掉`--show`。想观察第一次冷调用时改为`--warmup 0`。终端会分别打印模型加载、图片读取、OCR预处理、ONNX推理、CTC解码和OCR总耗时；只有后三项进入OCR总耗时。

## 2026-08-12 运行 Demo 的 HyperLPR3 纯识别模式

请使用项目已验证的 Conda Python；系统默认 Python 3.13 与项目内 ONNX Runtime DLL 不兼容：

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

- 不要同时加 `--with-ocr`，否则退出后会对保存的 Top-K 再做一次离线 OCR。
- 本次不要传 `--deblur-model`；纯识别基线先保持无去模糊。
- 按 `Q` 后会保存当前结果；每次调用在 `<run_dir>\recognition_results.jsonl`，汇总在 `<run_dir>\run_summary.json`。
- `source=plate` 表示输入来自 OBB 透视车牌，`track_id` 相同表示属于同一辆车；`entered_vote=false` 的低置信度/非法结果仍保留作诊断。
- 第一版只保证单层牌；双层牌请改用 `--ocr-engine hyperlpr3`。
- `--show-window` 左上角会显示 `FPS 实时处理帧率 / SRC 源视频帧率`；实时值按最近30个已处理帧平滑，模型加载时间不计入。

## 2026-08-12 原速播放的纯识别命令

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

- 左上角 `FPS/SRC` 是播放速度，`INFER` 是后台识别帧率，`DROP` 是被最新帧覆盖的过期识别帧数。
- 按 `R` 可暂停/继续后台识别，视频仍按原速播放；按 `Q` 或 `Esc` 保存并退出。
- 输出只保存JSONL和summary，不保存视频帧；所有OCR必须为 `engine=hyperlpr3-rec`、`source=plate`。
- 原速播放依靠丢弃过期识别帧，因此不能宣称逐帧完成检测；播放速度、识别覆盖率和车牌准确率要分别汇报。

## 2026-08-14 新对话入口

新开对话请优先发送并阅读：

```text
D:\YOLO_ALPR_Project\AGENTS.md
D:\YOLO_ALPR_Project\NEW_CHAT_HANDOFF_20260814.md
```

该文档已经汇总当前项目目标、实现内容、全部关键脚本、文件结构、HyperLPR3/PP-OCR/RK测试结果、历史尝试、过时结论、Git/远端版本差异、风险和下一步，并附有可直接复制的新对话提示词。

## 2026-08-15 一条命令同步 GitHub 发布源码

原工作区继续用于开发和实验：

```text
D:\YOLO_ALPR_Project
```

发布 worktree：

```text
D:\YOLO_ALPR_Project_GitHubRelease
```

在原工作区运行以下一条命令，会按 `release_manifest.txt` 把新增或变化的一方源码同步到 `codex/github-release` 工作区：

```powershell
python .\tools\sync_github_release.py --apply
```

安全行为：

- 写入前验证发布目录存在、当前分支是 `codex/github-release` 且没有未提交更改。
- 拒绝数据、第三方依赖、运行结果、证据包、敏感文件和单个达到或超过 95 MiB 的文件。
- 只新增或更新，不删除目标文件；不自动 `git add`、commit 或 push。
- 命令完成后，在 VS Code 单独打开发布 worktree，检查源代码管理差异，再人工暂存、提交和推送。

仅查看同步计划、不写入时运行：

```powershell
python .\tools\sync_github_release.py
```

## 2026-08-19 C++ 车辆系统新工作线

新目录：

```text
D:\YOLO_ALPR_Project\rk3588_vehicle_system
```

当前已完成 PC Stage 1：单路 CameraManager、最新帧有界队列、可替换 `IVehicleDetector`、Rockchip 优化 YOLO11n ONNX detector、画框视频和 JSON 性能统计。用户确认 `deploy/144.mp4` 与 `测试图/14.mp4` 是同一段测试视频；C++ 程序使用前者的 ASCII 路径以避开 OpenCV 中文视频路径问题。

正式实测：610 个已处理帧、154 个目标框、15.423 FPS、推理 P50/P95 为 51.128/73.548 ms、工作集 390.801 MiB、过期队列帧 560。当前后端是 ONNX Runtime CPU，未使用 RK3588 NPU。目视抽查确认远处和近处 `car` 框合理，但没有足够类别多样性，不能给出整体准确率结论。

详细报告：

```text
D:\YOLO_ALPR_Project\rk3588_vehicle_system\STAGE1_REPORT.md
```

继续命令：

```powershell
cd D:\YOLO_ALPR_Project\rk3588_vehicle_system
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run_pc_demo.ps1 -MaxFrames 610 -NoDisplay
```

下一步严格实现独立 `VehicleCropper` 及其测试，不要提前接颜色、跟踪、车牌或四路；Windows 基准 `alpr_topk_capture.py` 仍不得修改。

## 2026-08-20 C++ VehicleCropper 已完成

`rk3588_vehicle_system` 已推进到 PC Stage 2。新增独立 Cropper 接口与实现，支持边界修正、四方向扩张、最小尺寸过滤、默认浅 ROI 和可选深拷贝；已接入 `vehicle_demo` 并增加单元及图片/视频集成测试。

正式结果：CTest 2/2；独立图片 1 个 ROI；独立视频 180 帧产生 32 个 ROI、0 拒绝；主链路 610 帧产生 172 个 ROI、0 拒绝、保存 64 张，15.741 FPS，Cropper 每帧平均/P95为0.001/0.004 ms。当前仍为 PC CPU，未使用 RK3588 NPU。

详细报告：

```text
D:\YOLO_ALPR_Project\rk3588_vehicle_system\STAGE2_REPORT.md
```

下一步只进入车辆颜色模块：优先取得并核对 PP-Vehicle/PPLCNet 预训练模型协议，完成 ONNX Runtime 独立分类测试后再接主程序。不要使用伪颜色结果，也不要提前加入 ByteTrack 或车牌。

## 2026-08-20 C++ 车辆颜色模块已完成

`rk3588_vehicle_system` 已推进到 PC Stage 3。官方 PP-Vehicle PP-LCNet 车辆属性模型已转换为 ONNX，并通过独立 `IVehicleColorClassifier` 接口接入 C++ 主程序；模型输出是真实推理结果，不是颜色占位符。

独立黑/白 ROI 分别输出 `black 0.621165`、`white 0.863887`；610 帧主链路完成 173 次颜色调用，处理吞吐 18.029 FPS，颜色推理 mean/P50/P95 为 5.461/5.385/7.108 ms，工作集 404.301 MiB。当前仍为 Windows ONNX Runtime CPU，未使用 RK3588 NPU，不能外推板端性能或整体颜色准确率。

详细报告：

```text
D:\YOLO_ALPR_Project\rk3588_vehicle_system\STAGE3_REPORT.md
```

下一步严格实现独立 C++ ByteTrack：每个 Camera 自己维护 Track ID，并把检测、ROI 与颜色结果关联到 `TrackedObject`。ByteTrack 通过后再实现 VehicleFusion；不要提前接车牌或四路。

## 2026-08-20 C++ ByteTrack 已完成

`rk3588_vehicle_system` 已推进到 PC Stage 4。新增独立 `IVehicleTracker/ByteTracker`，实现 Kalman、Hungarian、高低分两阶段关联、未确认轨迹、Lost恢复、类别隔离和超时移除；主链路为 `Detector → ByteTrack → Cropper → Color`。

610帧正式结果：893个>=0.10检测、148个>=0.40检测、154次已确认轨迹观测，其中14次由低分框维持；Tracker每帧mean/P95为0.026/0.070ms，端到端16.163FPS，工作集399.352MiB，仍未使用NPU。ID1连续80次；后段同车在画面底部和CPU跳帧处被分成ID2两次、ID3七十二次，这是当前已知限制。

详细报告：

```text
D:\YOLO_ALPR_Project\rk3588_vehicle_system\STAGE4_REPORT.md
```

下一步实现独立 VehicleFusion：按 `track_id` 收集颜色并做置信度加权投票，业务层不再把单帧颜色直接当最终颜色。完成后再进入车牌流水线。

## 2026-08-21 C++ VehicleFusion 已完成

`rk3588_vehicle_system` 已推进到PC Stage 5：主链路为`Camera → YOLO11n ONNX → ByteTrack → VehicleCropper → PP-Vehicle颜色 → VehicleFusion`。Fusion接口、实现和独立单测均已落地，CTest 4/4通过。

610帧正式结果：21.691FPS，897个检测，170次已确认轨迹观测和融合更新，164次稳定融合观测，3个Track ID达到稳定；Fusion更新mean/P95为0.005/0.008ms，工作集409.176MiB，NPU未使用。输出位于`rk3588_vehicle_system/runs/pc_stage5_vehicle_fusion/`，详细报告为`rk3588_vehicle_system/STAGE5_REPORT.md`。

已知边界：后段同一车辆仍可能由Tracker分裂为不同ID，Fusion不会跨ID猜测合并；视频基本只有白色车辆，不能据此证明多颜色准确率。

下一步从车牌流水线开始，先阅读已有`best_obb.onnx/rknn`相关脚本和模型协议，只实现车辆ROI内的`IPlateDetector`与`PlateCropper`并做独立测试。不要一次接入OCR、四路或RKNN，也不要修改`alpr_topk_capture.py`。

## 2026-08-21 C++ 车辆系统加入 GitHub 发布白名单

`release_manifest.txt` 已精确包含 `rk3588_vehicle_system` 的 CMake、一方源码/头文件、测试、配置、脚本、阶段报告和嵌套 `.gitignore`。不要改成整个目录递归复制；`build`、`runs`、`third_party`、模型、视频和编译产物必须继续留在本地或外部备份。

日常命令不变：

```powershell
python D:\YOLO_ALPR_Project\tools\sync_github_release.py --apply
```

发布 worktree 已有未提交内容时，同步器只允许白名单内且不会丢失内容的安全续传；出现非白名单文件、删除/重命名或内容冲突时会拒绝运行。同步完成后仍需在 VS Code 中人工检查、暂存、提交和推送。
