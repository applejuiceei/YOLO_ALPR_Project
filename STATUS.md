# 项目状态

更新时间：2026-08-14

## 已完成

- 已新增 `NEW_CHAT_HANDOFF_20260708.md`，用于新开对话快速接手；内容包含现有项目目标、当前结论、关键脚本、测试结果、文件结构、各文件作用和本轮 SC850SL 调试尝试。
- Windows Top-K + HyperLPR3 主线已形成，主脚本为 `alpr_topk_capture.py`。
- Windows 实验副本 `alpr_topk_capture_demo.py` 已用于 deblur、A/B 和弹窗显示等尝试。
- RK3588 板端主脚本 `rk3588_topk_capture.py` 已可运行。
- RKNN 车辆模型和车牌 OBB 模型已在板端加载运行。
- HyperLPR3 已在板端导入并运行。
- `/root/deploy/144.mp4` 视频自测已跑通，并曾锁定 `冀JC5210`。
- 新板离线部署包已准备并验证关键依赖可恢复。
- deblur v2 e20 模型已训练完成，并进入 Windows demo/离线评估阶段。
- 新板 MIPI 节点已排查到 `/dev/video53` 等相关 video node。
- 已确认新板 MIPI 当前抓图结果为 0 字节，并伴随内核错误。
- 已创建长期项目记忆文件：`AGENTS.md`、`PROJECT.md`、`STATUS.md`、`DECISIONS.md`、`HANDOFF.md`。
- 已确认实际摄像头模组为 SC850SL，系统中存在 SC850SL 驱动、设备树节点和 IQ 文件。
- 已确认 `/dev/video33` 可输出 SC850SL BG10 RAW10 原始帧，5 帧约 51 MB，约 30 FPS。
- 已生成 SC850SL RAW10 灰度预览，曝光 1200 档画面可见道路和车辆。
- 已在 `rk3588_topk_capture.py` 增加 `BG10` / `raw10-gray` 输入支持，并通过本地语法检查。
- 已在 `rk3588_topk_capture.py` 增加 `--detect-roi` / `--draw-detect-roi`，支持车辆检测前裁剪放大并映射回全图坐标。
- 已确认 `rk3588_topk_capture_mipi_debug.py` 是更新的 MIPI 调试参考脚本，包含 MIPI 低光增强和 plate scan 诊断能力。
- 已创建副本 `rk3588_topk_capture_mipi_debug_sc850.py`，用于 SC850SL 适配，不直接修改原 debug 脚本。
- 已在 `rk3588_topk_capture_mipi_debug_sc850.py` 加入 `BG10` / `raw10-gray` / `raw10-stride` 和 `--detect-roi` / `--draw-detect-roi`，并通过本地语法检查。
- 已通过 `/tmp/frame.jpg` + 浏览器服务实时看到远程 SC850SL 摄像头画面。
- 已确认实时画面中可见道路，车辆速度较快；1000 帧测试仍为 `tracks=0`、`new_hits=0`、`total_hits=0`，问题位于 vehicle 检测未起量，而不是 OCR 阶段。
- 已在 `rk3588_topk_capture_mipi_debug_sc850.py` 增加 `--detect-roi-tiles` / `--detect-roi-overlap`，支持将检测 ROI 分块后分别送入 vehicle 模型，并在日志/画面显示 `vehicle_boxes`。
- 已确认分块 ROI 后模型开始输出框：300 帧测试中 `vehicle_detections_raw=79`、`vehicle_detections_nms=79`、`vehicles_ready=79`、`plate_attempts=79`，但画面观察显示多数框落在广告牌/灯箱/路边结构上，不是真实车辆；`PLATE` 锁定来自低阈值诊断模式，属于假阳性，不能视为有效识别。
- 已确认白天沿用夜间曝光参数会严重过曝，画面大片接近纯白，车辆/车牌/车道纹理丢失；白天测试需先降低 SC850SL `exposure`，再调 ROI 和检测阈值。
- 第一次白天曝光扫描截图左上角均显示同一 `frame:500`，疑似复制了已停止识别程序留下的旧 `/tmp/frame.jpg`；曝光扫描前必须确认采集/发布程序仍在刷新。
- 实时刷新后，白天 `exposure=380` 画面已恢复道路、车身和车道线层次；高光区域仍有部分溢出，但可作为日间检测候选曝光继续测试。
- 白天实时测试中观察到运动中的车辆仍无法稳定框住；当前完整脚本约 `1 fps`，快车容易在检测帧之间通过，同时 ROI 内固定高对比结构仍会造成假阳性。
- 已在 `rk3588_topk_capture_mipi_debug_sc850.py` 增加 `--vehicle-source motion|hybrid` 固定机位运动目标 fallback，用背景差分生成运动车辆候选框，避免 SC850SL 灰度视角下 vehicle RKNN 不适配导致 `veh:0`。
- 已创建 `REMOTE_CODEX_HANDOFF.md`，用于远程 Windows 新 Codex 接手；其中包含需传输文件清单、项目目标、当前结论、关键脚本、测试结果、文件结构、已做尝试和下一步 motion 测试命令。
- 远程 SC850SL 使用 `--vehicle-source motion` 已能在实时画面中框到真实汽车，说明固定机位运动目标 fallback 方向成立。
- 已确认 `motion` 也会框到电动车、车轮等非汽车运动物体；已在 `rk3588_topk_capture_mipi_debug_sc850.py` 增加 `--motion-min-aspect`、`--motion-min-fill-ratio`、`--motion-accept-roi`，用于过滤过小/过瘦/非车道内的运动框，并通过本地语法检查。
- 2026-07-06 已通过 SSH 在用户本地 IMX585 RK3588 板上重跑内置场地视频 `/root/deploy/144.mp4` 1000 帧：平均约 10 FPS，锁定 `冀JC5210` 和 `冀B6R9F9`，结果目录为 `/root/alpr_topk_rk3588/runs_video_selftest_codex/run_20260706_031136`。
- 2026-07-06 用户确认远程 SC850SL 板运行同一内置场地视频时，识别表现与本地 IMX585 板一致：可正常显示彩色视频、约 10 FPS，并锁定 `冀JC5210`。这说明板端 ALPR 主流程、模型、OCR、投票锁定和浏览器发布链路在 SC850SL 板上也可用。
- 已创建 `RK3588_dev/sc850_isp_probe.sh`，用于在远程 SC850SL 板上一键采集 media 拓扑、subdev/video node 能力、rkaiq/IQ 线索、dmesg，并对 `/dev/video33` 与 `/dev/video44` 做短帧数非破坏性取流测试。
- 已分析用户传回的 `RK3588_dev/sc850_isp_probe_20250626_124614` 证据包：`/dev/video33` 是 SC850SL `BG10` RAW10 可用原始节点；`/dev/video44` 属于 `rkisp0-vir0`，默认/能力仅显示 `800x600`，不是当前 SC850SL 4K ISP 主输出节点。
- 已从证据包确认 SC850SL 的完整链路是 `m01_b_sc850sl 4-0030` -> `rockchip-csi2-dphy3` -> `rockchip-mipi-csi2` -> `rkcif-mipi-lvds4` -> `rkisp1-vir1` -> `/dev/video71`。
- 已确认 `/dev/video71` 是 `rkisp1-vir1` 的 `rkisp_mainpath`，格式能力支持 `NV12/UYVY` 等标准 YUV，最高到 `3840x2160`；`/dev/video-camera0` 也链接到 `video71`。这是下一步优先测试的 SC850SL ISP 输出节点。
- 已确认 `/dev/video53` 确实是 ISP mainpath，但它属于 `rkisp0-vir2`，上游为 `rkcif-mipi-lvds2/SRGGB12_1X12`，不是 SC850SL 已确认的 `rkcif-mipi-lvds4/SBGGR10_1X10` 链；因此不能把 `/dev/video53` 当作 SC850SL 的 ISP 输出。
- 已更新 `RK3588_dev/sc850_isp_probe.sh`，增加 `/dev/video53`、`/dev/video71` 和 `/dev/video72` 的标准 YUV 短流测试；`/dev/video53` 保留用于对照，SC850SL 优先看 `/dev/video71`。
- 远程 SC850SL 板手动测试 `/dev/video71` 4K `NV12` 时，`VIDIOC_STREAMON returned 0 (Success)`，但 `/tmp/video71_nv12.raw` 仍为 0 字节；dmesg 报 `rkisp1-vir1: waiting on params stream event timeout` 和 `rkisp1-vir1: can not get first iq setting in stream on`。
- 远程板已确认 `rkaiq_3A.service` 处于 active/running，进程为 `/usr/bin/rkaiq_3A_server`，并存在 `/etc/iqfiles/sc850sl_GC_12MM.json` 与 `/etc/iqfiles/sc850sl_2L_GC_12MM.json`。
- `rkaiq_3A.service` 日志显示 `/dev/media5: wait stream start event...`；但当前证据包中 SC850SL 对应 ISP 链路是 `/dev/media7` -> `/dev/video71`，而 `/dev/media5` 对应 `/dev/video53` 的另一条 `rkcif-mipi-lvds2/SRGGB12_1X12` 链。当前怀疑 rkaiq 监听/绑定了错误 media 设备，导致 `/dev/video71` 无法获得 first IQ setting。
- 已查看 `rkaiq_3A.service` 和 `/etc/init.d/rkaiq_3A.sh`：service 仅执行 `/etc/init.d/rkaiq_3A.sh start`，脚本中 `start_3A()` 以无参数方式启动 `/usr/bin/rkaiq_3A_server 2>&1 | logger -t rkaiq &`。
- `rkaiq_3A_server` 实际 cmdline 仅为 `/usr/bin/rkaiq_3A_server`，没有显式指定 media、IQ 文件或 camera。
- `rkaiq_3A_server` 的 fd 列表中能看到 `/dev/v4l-subdev7` 和 `/dev/v4l-subdev8` 等节点，说明它至少打开过 SC850SL sensor/rkisp1 相关 subdev；但仍需确认是否打开 `/dev/media7`，以及为何日志仍停在 `/dev/media5: wait stream start event...`。
- 已分析用户传回的 `RK3588_dev/sc850_rkaiq_debug_20250626_142419.tar.gz`：`/dev/video71` 4K `NV12` 取流成功，`VIDIOC_STREAMON returned 0 (Success)`，连续得到 5 帧，每帧 `12441600` bytes，总 raw 文件约 60 MB，帧率约 30.01 FPS。
- 同一日志包显示 rkaiq 已识别 `/dev/video71` 为 `rkisp_mainpath`，日志出现 `/dev/media7: wait stream start event success ...` 和 `wait stream stop event success ...`；dmesg 显示 `sc850sl 4-0030: s_stream: 1. 3840x2160, hdr: 0, bpp: 10`，并有 `rkisp rkisp1-vir1: first params buf queue`。
- 当前结论更新：SC850SL 的 `/dev/video71` 标准 ISP `NV12` 输出链路已经可用；此前 `/dev/video71` 0 字节更像是 rkaiq 未完成初始化/事件等待状态下的偶发或时序问题，不能再作为当前主结论。

## 正在进行

- 建立长期项目文档体系，确保后续 AI 接手时先读规则、目标、状态、决策和交接。
- 围绕新线下测试板 SC850SL 实时摄像头输入继续排查；内置视频已证明 ALPR 主流程可用，当前重点转向实时摄像头图像域、曝光、ROI、候选质量和 RKISP 输出链路。
- 针对远景灰度画面车辆过小/过快和静态广告牌误检问题，先收敛车道 ROI 与 vehicle 阈值。
- 白天场景先做曝光扫描，避免过曝导致检测输入不可用。

## 当前卡点

### RKISP 输出链路已通，待切换实时 ALPR 输入

现象：

- `/dev/video33` 原始 BG10 RAW10 可以出帧。
- `/dev/video71` 已确认 4K `NV12` 可以出帧，5 帧约 60 MB，约 30 FPS。
- `/dev/video44` 取流仍报：

```text
VIDIOC_STREAMON returned -1 (Operation not permitted)
rkisp0-vir0: check rkisp_mainpath link or isp input
```

当前判断：

- 摄像头硬件、排线、SC850SL 驱动、MIPI/CSI/DPHY/CIF 前级已经可用。
- 当前新判断：`/dev/video44` 很可能是错误节点，属于 `rkisp0-vir0`，不是 SC850SL 4K 链路对应输出。
- 下一优先验证节点是 `/dev/video71`，它属于 `rkisp1-vir1` 的 `rkisp_mainpath`，并已在 media graph 中连到 SC850SL 所在 `rkcif-mipi-lvds4`。
- `/dev/video71` 的 3A/IQ 事件已在新日志包中确认成功；下一主线应优先验证 `/dev/video71` ISP 画面质量，并把实时 ALPR 输入从 `/dev/video33` RAW10 灰度切到 `/dev/video71` 标准 `NV12`。
- 短期仍可保留 `/dev/video33` RAW10 灰度输入作为对照，但不再作为主路线。
- 初次灰度整图测试、低阈值测试和单块 `--detect-roi` 1000 帧测试均为 `tracks=0`；分块 `--detect-roi-tiles 1 3` 后模型有输出框，但当前主要是假阳性，并未稳定框住真实车辆。
- 当前新卡点：低阈值 + 宽 ROI 会把广告牌/灯箱/路边结构误检为车辆/车牌；需要先收窄到真实车道 ROI，并提高 vehicle/plate 阈值，避免诊断模式假锁定。
- 白天画面当前建议先用 `exposure=380` 附近继续测试；更优日间值可在 `320/350/380` 中微调，待确认。
- 当前还需先跑“车辆框专用测试”：跳过车牌阶段、收窄车道 ROI、减少 tile 数量，提高有效检测帧率，确认运动真车是否能被 vehicle 模型框住。
- `--vehicle-source motion` 已验证可框住真实汽车，但也会框住电动车/车轮等非汽车运动目标；下一步需用 motion 车辆形状过滤和车道 ROI 过滤减少误框，再接 plate OBB。
- 曝光扫描结果必须基于正在更新的实时帧；若 `frame:` 数字不变或文件时间不变，则扫描无效。
- `mipi_plate_scan_*` 是早期因只能用手机图片测试而加入的诊断能力，不是最终道路实测目标；最终必须将车牌号绑定到车辆 track 并显示在车辆上方。

## 下一步

0. 新开对话时先阅读 `AGENTS.md` 和 `NEW_CHAT_HANDOFF_20260708.md`，再继续围绕 `/dev/video71` NV12 实时输入调车辆框质量。
1. 在远程 SC850SL 板用 `/dev/video71` 抓取 1-5 帧 `NV12` 并转 jpg，确认 ISP 画面是否正常彩色/亮度是否可用。
2. 用 `rk3588_topk_capture_mipi_debug_sc850.py` 切换到 `/dev/video71`、`--mipi-fourcc NV12`、`--mipi-color-mode nv12` 跑实时道路 ALPR。
3. 观察 `/tmp/frame.jpg`、FPS、vehicle hits、plate hits、OCR 结果和 run 目录；如果 `/dev/video71` 画面质量正常，则停止把 `/dev/video33` 灰度作为主测试输入。
4. 若 `/dev/video71` 实时 ALPR 出现画面过曝/偏色，再围绕 SC850SL IQ/曝光/增益调参，而不是回退到灰度域。
5. 后续进行 `best_obb_finetuned_e20.pt` 转 RKNN 并做板端 A/B。
6. 后续继续评估 deblur 对 HyperLPR3 OCR 的真实增益。

## 待确认

- Codex 当前机器是否能直连 `192.168.8.88`。
- 厂家原厂摄像头测试命令。
- 是否需要创建 `PR0JECT.md` 兼容用户首次拼写。
- 灰度 RAW10 输入下 ALPR 的实际 FPS 和识别率。
- 本地 IMX585 板和远程 SC850SL 板内置视频回归均已跑通；这不代表远程 SC850SL 灰度实时输入可用，实时摄像头图像域问题仍待解决。
- `--detect-roi` 后 vehicle tracks 是否能从 0 起量。
- `--detect-roi-tiles` 后出现 vehicle boxes，但是否能稳定框住真实车辆仍待确认。
- 白天 SC850SL 合适的 `exposure` 值初步候选为 380，最终值待检测效果确认。
- SC850SL 副本跑通后，车牌号是否能锁定并跟随对应车辆直到检测/预测失效。
- 新增 motion 过滤参数能否在保留真实汽车框的同时过滤电动车、车轮和行人，待远程实测确认。
- `/dev/video44` ISP 输出链路具体缺失的 media link / rkaiq / ISP 配置项。
## 2026-07-10 新对话交接

- 已新增 `NEW_CHAT_HANDOFF_20260710.md`，用于新开对话时完整接手 SC850SL `/dev/video71` NV12 实时道路识别调试。
- 文档已汇总项目目标、当前结论、关键脚本、文件结构、测试结果、已尝试方案和下一步 post-replug 检查。
- 当前下一步仍是：在用户已重插 SC850SL 后，先确认 I2C 0x30、media graph 和 `/dev/video71` 3840x2160 NV12 单帧是否恢复，再继续 ALPR。

## 2026-07-10 重插后最新结果

- 用户截图显示：重插 SC850SL 后执行 `i2cdetect -y -r 4`，I2C4 仍未出现 `0x30/UU`。
- dmesg 仍有 `get remote terminal sensor failed!`，并出现 `rkisp1-vir1: check rkisp_mainpath link or isp input`。
- 当前结论：sensor 仍未正常上线，`/dev/video71` 上游 ISP input 仍异常；暂不继续 ALPR/OCR/Top-K 调参。

## 2026-07-10 推流恢复与基准复测

- 用户反馈板端 `/root/mediamtx/start_4_stream.sh` 已可从 `/dev/video71` 推出 RTSP 流，VLC 打开 `rtsp://192.168.8.88:8559/video71` 可看到真实道路画面。
- 用户截图中 dmesg 出现 `sc850sl 4-0030: Detected sc850sl id 009d1e`，这更新了此前“重插后 sensor 仍未上线”的状态；当前至少在 mediamtx/GStreamer 路径下，SC850SL sensor/I2C/ISP/`/dev/video71` 链路已经恢复过。
- 注意：mediamtx/GStreamer 可能占用 `/dev/video71`，跑 ALPR 前应先停止推流，再用 `v4l2-ctl` 直接验证 `/dev/video71` 单帧 NV12 raw 是否为 `12441600` bytes。
- 本机 Windows 端 2026-07-10 短跑 `alpr_topk_capture.py` 120 帧成功生成 run：`D:\YOLO_ALPR_Project\captures_topk_codex_win_20260710\run_20260710_133357`；但当前 Windows Python 环境 HyperLPR3/onnxruntime DLL 加载失败，因此该轮 OCR 未生效，不能作为 Windows OCR 效果回归。
- 2026-07-10 通过 SSH 在用户本地 IMX585 RK3588 板运行 `rk3588_topk_capture_mipi_debug.py` 对 `/root/deploy/144.mp4` 跑 1000 帧，结果目录为 `/root/alpr_topk_rk3588/runs_codex_imx585_video_20260710/run_20260710_053723`。
- 本次 IMX585 板端视频回归处理 `1000` 帧，用时约 `228.83s`，约 `4.37 FPS`；锁定 `冀JE5210` 和 `冀B6R9F9`，与 2026-07-08 板端回归结论一致。

## 2026-08-05 Windows 异步原速识别

已完成：

- 新增 `alpr_realtime_async.py`，使用视频线程 + 单槽最新帧缓冲 + 后台识别线程；未修改 `alpr_topk_capture.py` 和 `alpr_topk_capture_demo.py`。
- 原始视频窗口不叠加检测框、车牌文字或性能文字；识别结果输出终端 `[RESULT]` 和 `recognition_results.jsonl`。
- 支持 `R` 键切换识别、`--recognition-start-frame`、`--recognition-stop-frame` 和可选 `--control-file`。
- 支持 `--tracking none|iou`、`--plate-stage off|fallback|always`、`--pipeline vehicle|direct`、`--no-save-results` 和 `--no-show-video`。
- 当前 Windows 环境实测为 CPU-only：`torch 2.12.0+cpu`、CUDA 不可用、16 个逻辑处理器。
- 当前测试视频已确认是 `1920x1080`、`24.000 FPS`、`6971` 帧。

验证结果：

- 速度优先模式（HyperLPR3、`plate-stage=off`、无 tracking）跑 650 帧：视频循环 `24.011 FPS`，后台识别 `9.265 FPS`，397 个过期帧被替换；在 frame 594 输出 `冀B6R9F9`，置信度 `0.9977`。
- 自动开关测试：frame 24 开启、frame 72 关闭，实际提交 48 帧，开关日志与预期一致。
- 完整 fallback 短测显示重帧中 plate OBB 可达约 `2928 ms`，OCR 约 `512 ms`，车辆检测约 `208 ms`；当前主要性能风险是模型推理和 plate OBB，而不是视频显示或 Python 画框。
- 诊断性 30 FPS 加速读取测试达到约 `29.889 FPS`，但源文件只有 24 FPS，该结果不作为原速播放验收结论。

待确认：

- 新脚本可见窗口模式需由用户继续观察长时间播放是否存在肉眼卡顿；无窗口原速循环已经完成量化验证。
- 速度优先 `plate-stage=off` 会牺牲部分车牌召回率；是否接受需用完整视频对比识别结果集合。
- C++ 暂不立即迁移；先评估 YOLO PT 导出 ONNX/OpenVINO 后的 CPU 推理收益，再决定是否需要 C++ 承载。

## 2026-08-06 核心源码已发布

- 已向 `http://47.102.197.116:3000/gcvision_admin/PLR-Test` 的 `main` 分支推送轻量核心源码。
- 远端提交：`37580c306a9b9f5132dde07218c7d89e9d410680`。
- 发布文件共 7 个：`.gitignore`、`README.md`、`requirements.txt`、`alpr_realtime_async.py`、`alpr_topk_capture_demo.py`、`hyperlpr3_ocr.py`、`plate_rec_ocr.py`。
- 已验证远端 `main` 哈希与本地发布提交一致；敏感信息扫描无命中，未上传模型、视频、结果或凭据。

## 2026-08-07 HyperLPR3 计时与阈值

- `alpr_realtime_async.py` 默认 `--min-ocr-conf` 已从 `0.70` 调整为 `0.50`。
- 每条 JSONL 结果新增 `ocr_engine`、单次 `ocr_ms`、后台整帧 `recognition_total_ms` 和 `end_to_end_ms`；终端新增 `[OCR_SPEED]`。
- `summary.json` 新增 `ocr_calls` 和 `average_ocr_ms`，`[PERF]` 新增 `ocr_frame_ms` 与 `ocr_avg_ms`。
- 650 帧源速链路测试的有效结果中，单次 HyperLPR3 为 `85.820–113.483 ms`；整帧/端到端耗时明显更高，主要受车辆 YOLO CPU 推理影响。
- 对同一真实车辆 crop 连续重复10次的纯 HyperLPR3 基准：最小 `117.855 ms`、中位数 `170.423 ms`、平均 `177.296 ms`、最大 `278.142 ms`。CPU 竞争会造成较大波动，不能只引用单次数字。

## 2026-08-07 HyperLPR3 纯识别模块 A/B

- 新增独立脚本 `benchmark_hyperlpr3_recognition.py`，不改 Windows 基准和异步实时程序。
- 默认读取 `captures_topk_codex_win_20260708/run_20260708_131529` 的18组 `vehicle_rank`/`plate_rank` 配对样本，执行完整接口车辆图、完整接口车牌图、纯识别车牌图三路对比。
- 默认完整测试已完成：18组样本、每路预热20次、每样本重复10次，样本失败和三路调用失败均为0。
- 纯识别总耗时 `P50=81.616 ms`、`P95=186.169 ms`；预处理 `P50=0.181 ms`、推理 `P50=81.184 ms`、解码 `P50=0.221 ms`，瓶颈为 ONNX 推理，未达到20ms。
- 已确认车牌 `冀B6R9F9` 在 track 4/rank 2 的三路结果中均正确命中；纯识别合法车牌率为 `0.6111`，与 summary 参考文本一致率仅 `0.1333`，暂不接入实时主链路。
- 完整结果位于 `runs_hyperlpr3_recognition_ab/run_20260807_170904/results.json` 和 `results.csv`。

## 2026-08-08 PP-OCRv4 Mobile 训练准备与 CPU 冒烟

已完成：

- 新增隔离目录 `ppocr_plate`，覆盖数据清单审计、合成样本、PP-OCRv4 Mobile 训练、Paddle/ONNX 导出、ONNX Runtime/OpenVINO/RKNN 基准和跨后端一致性比较；Windows/RK 实时主线均未修改。
- 核对 HyperLPR3 官方字符表为 76 个非 blank 字符；新 CTC 模型总输出类数为 77。模型统一使用 RGB `1x3x48x160`，OpenCV API 仍接收 BGR crop。
- 定位并修复原冒烟“卡死”：训练辅助 NRTR 编码还需 BOS/EOS，`max_text_length=8` 会拒绝全部 7/8 位标签并触发数据集递归换样本；现保持原始标签最长 8 位，训练内部序列槽设为 10。
- CPU 100 步冒烟已完成：`runs_ppocr_plate_train/smoke_20260808_092616`，实际训练约 17 分钟，`global_step=100`，loss 从约 151.83 降至 101.46。该运行从随机初始化开始，仅验证结构，不用于准确率结论。
- 冒烟 checkpoint 已成功导出 Paddle 推理模型；实际 predictor 输入为 `(1,3,48,160)`、输出为 `(1,20,77)` 且数值有限。随机/短训模型输出 `CHN` 不代表有效车牌识别。
- 修正 PIL 合成蓝牌/黄牌的 RGB 颜色顺序，并用 `ppocr_plate/data/synthetic_smoke_rgb_20260808` 重新完成小样本分组、哈希和泄漏审计。
- `plate_rec_sim.onnx` 按其真实 BGR/48x320/6625 类协议完成独立 1000 次基准：4 线程总耗时 `P50=47.30 ms`、`P95=79.76 ms`，推理 `P95=75.38 ms`；18 张仅 1 张通过车牌格式，确认样本 `冀B6R9F9` 输出为 `WB6R9F9`，因此不进入正式链路。

待完成/外部条件：

- 正式微调尚未开始：当前缺少通过门槛审计的数据集、已下载的官方 PP-OCRv4 训练权重和可用 GPU。CPU 冒烟速度不适合完整训练。
- 当前环境缺少 `paddle2onnx`、`onnx`、OpenVINO、NNCF 和 RKNN 工具链；对应脚本已完成语法/CLI 验证，真实转换、量化和板端基准仍待匹配环境执行。
- 未取得人工真值前，不报告整牌/字符准确率；未通过准确率与 Windows/RK3588 双端 `P95 < 20 ms` 前，不接入实时程序。

## 2026-08-11 HyperLPR3 清晰车牌目录基准

- 新增独立脚本 `benchmark_hyperlpr3_image_dir.py`，未修改 Windows/RK 实时主线。
- 输入目录共有 1041 张 JPG，全部可解码、尺寸均为 350×150；其中至少64张按宽松规则仍偏暗或低纹理，因此目录名 `sharp` 不等于所有样本都真正清晰。
- 完整 HyperLPR3 公共接口：1041次无运行错误，输出779次（74.83%）；总耗时 `P50=78.266 ms`、`P95=210.520 ms`、平均 `94.841 ms`。
- HyperLPR3 纯识别模块：1041次全部输出，格式合法1012次（97.21%）；端到端 OCR `P50=26.034 ms`、`P95=43.254 ms`、平均 `28.206 ms`、最小 `13.345 ms`。
- 纯识别耗时几乎全部集中于 ONNX 推理：推理 `P50=25.572 ms`、`P95=42.778 ms`；预处理和解码的 P95 分别为 `0.299 ms`、`0.301 ms`。
- 纯识别相对完整接口的 P50 加速约3.01倍、P95约4.87倍；但 P50/P95 均未达到20ms。
- 在完整接口有输出的779张中，两路文本完全一致722张（92.68%）；完整接口漏掉的262张中，纯识别产生240个格式合法输出。该目录无人工标签，这些只能说明输出/一致性，不能作为准确率。
- 完整结果：`runs_hyperlpr3_image_dir/run_20260811_112914/results.json` 和 `latencies.csv`。

## 2026-08-11 HyperLPR3 完整接口分阶段基准

- 新增无侵入插桩脚本 `benchmark_hyperlpr3_full_stages.py`；只在独立进程临时包装本机 HyperLPR3 0.1.3 的绑定方法，结束后恢复，未修改第三方包和实时主线。
- 同一1041张预载图片、低精320检测器、预热50次、batch=1、单并发；插桩前后5张公开结果完全一致，OCR调用数与单双层候选关系违规为0。
- 公共完整调用：`P50=79.474 ms`、`P95=205.369 ms`、平均`96.817 ms`。与未插桩基准的P50差1.54%、平均差2.08%，属于运行波动/轻微计时扰动范围。
- 检测每图必跑：预处理/推理/后处理P50分别`1.488/10.918/0.403 ms`，检测合计`P50=13.053 ms`、`P95=83.683 ms`、平均`31.641 ms`。
- 1041张中825张产生1个检测候选、216张零候选；本批无双层候选。透视拉正实际调用825次，单次`P50=1.229 ms`、`P95=1.638 ms`。
- OCR实际调用825次：预处理/推理/CTC解码P50分别`0.154/61.101/0.202 ms`，OCR合计`P50=61.531 ms`、`P95=182.872 ms`、平均`74.336 ms`。
- 颜色分类器实际调用717次：预处理/推理/后处理P50分别`0.175/1.539/0.001 ms`，合计`P50=1.715 ms`、`P95=34.982 ms`、平均`5.556 ms`。
- 每张输入的平均总耗时贡献：检测`31.641 ms (32.68%)`、OCR`58.912 ms (60.85%)`、分类`3.827 ms (3.95%)`、透视`1.616 ms (1.67%)`，其余流水线/解析/包装合计约`0.82 ms`。
- 216张在检测阶段无候选；另有46张已有候选并执行OCR但未形成最终结果，因此“完整接口空输出262张”不等于全部是检测失败。
- 正式结果：`runs_hyperlpr3_full_stages/run_20260811_114704/results.json` 和 `stage_latencies.csv`。

## 2026-08-11 HyperLPR3 单张纯识别入口

- 新增 `hyperlpr3_recognize_once.py`，只加载 `PPRCNNRecognitionORT/rpv3_mdict_160_r3.onnx`；不执行检测、透视拉正、单双层拆分或颜色分类。
- 默认可直接测试 `Dataset/dataset/test/sharp/grab10003.jpg`，也支持 `--image` 选择任意裁正车牌、`--warmup` 设置预热次数、`--show` 显示输入图。
- 冷调用验证：识别`苏E803JV`、置信度`0.999943`，OCR预处理`0.333 ms`、ONNX推理`21.643 ms`、CTC解码`0.195 ms`、总计`22.174 ms`。
- 预热20次后的单次验证：相同文字和置信度，OCR预处理`0.151 ms`、ONNX推理`17.410 ms`、CTC解码`0.168 ms`、总计`17.735 ms`。
- 单次结果只反映当次调度；稳定性能仍以1041张分布的P50/P95为准。

## 2026-08-12 `alpr_topk_capture_demo` 纯识别状态

- 已实现 `HyperLPR3RecognitionOCR`，模型路径从 HyperLPR3 配置动态解析；官方预处理、ONNX 推理和 CTC 解码保持复用，模型只初始化一次。
- 已增加 `--ocr-engine hyperlpr3-rec` 与 `--show-ocr-timing`；终端逐次显示 frame、track、来源、文字、置信度、`ocr_ms`、格式/置信度过滤及投票状态。
- 已验证确认样本输出 `冀B6R9F9`，置信度 `0.991709`。
- 610 帧无窗口冒烟通过：19 次 OCR、0 错误，来源全部为 `plate`，无 vehicle OCR；低于 0.5 和格式非法结果保留在 JSONL 但未投票。
- 冒烟中 track 4 在第 594、595 帧输出 `冀B6R9F9`，第 595 帧经过3次有效结果锁定；JSONL 19 行与 summary `call_count=19` 一致。
- 本次冒烟同时存在一个自 2026-08-11 起运行的 Python 进程，实时延迟 P50=`106.428 ms`、P95=`167.481 ms` 只能视为受并发负载影响的现场结果，不能当作独占 CPU 基准。
- `py_compile`、新旧引擎构造、阈值/格式过滤和 JSONL/summary 一致性检查通过；正式 GUI 运行仍由用户按实际视频操作并按 `Q` 退出。
- 预览窗口左上角新增滑动30帧统计的实际处理/显示帧率，并同时显示源视频帧率，格式为 `FPS 实时值 / SRC 源FPS`。

## 2026-08-12 原速播放 + HyperLPR3 纯识别后台链路

- `alpr_realtime_async.py` 已固定为 `hyperlpr3-rec` 纯识别模式；车辆 YOLO 与车牌 OBB 只负责定位和透视，OCR 仅接收 OBB 拉正后的 `plate` crop。
- 主线程按源视频 FPS 播放，后台单槽缓冲只保留最新帧；识别慢于播放时覆盖过期帧，不再拖慢视频窗口。
- 默认启动识别、IoU 跟踪、20次 OCR 预热；可按 `R` 开关后台识别，按 `Q/Esc` 保存退出。
- 每次 OCR（含非法、低置信或空结果）均写入 `recognition_results.jsonl`，包含 frame、track_id、文字、置信度、ocr_ms、过滤/投票状态；不再按文字全局去重。
- 610帧实测：源24 FPS，理论25.417秒，实际25.386秒、`24.029 FPS`；后台处理340帧，覆盖270个过期帧，失败0帧。
- 实测纯OCR调用4次，JSONL恰好4行且全部 `engine=hyperlpr3-rec/source=plate`；平均OCR `32.436 ms`，识别出 `冀B6R9F9`。

## 2026-08-14 新对话完整交接

- 已新增 `NEW_CHAT_HANDOFF_20260814.md`，共约900行，汇总当前项目目标、已实现功能、对话工作历程、关键脚本、文件结构、正式测试结果、历史尝试、版本风险、过时结论和下一步路线。
- 文档已核对当前工作区和实际 JSON/JSONL：补充用户 2502 帧 GUI 原速运行 `24.001 FPS`、7月30日板端长跑/对焦/后聚焦结果、PP-OCR尚未正式训练，以及 Gitea 轻量发布版落后于本地8月12日实现等状态。
- 未删除、覆盖或回滚任何历史结果；Windows 基准 `alpr_topk_capture.py` 未修改。

## 2026-08-15 GitHub 发布白名单同步

- 新增 `release_manifest.txt`，覆盖根目录一方 Python/Markdown、PP-OCR源码配置、RK3588直接源码/启动脚本和项目维护工具；不递归进入数据集、第三方源码、依赖副本、运行结果、证据包或 offline bundle。
- 新增 `tools/sync_github_release.py`，默认 dry-run；使用 `--apply` 时先验证目标是干净的 `codex/github-release` worktree，再执行新增/更新复制。
- 同步器不删除目标文件，不自动暂存、提交或推送；单文件硬上限为 95 MiB，并检查禁止目录、文件类型、敏感文件名和常见凭据格式。
- Windows 基准 `alpr_topk_capture.py` 未修改；现有 `.idea/vcs.xml` 和运行结果目录不在白名单中，不会被同步。
