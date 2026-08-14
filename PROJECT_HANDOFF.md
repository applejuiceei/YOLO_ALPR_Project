# YOLO_ALPR_Project 项目交接文档

更新时间：2026-07-03  
项目根目录：`D:\YOLO_ALPR_Project`

这份文档用于把当前 ALPR 项目的目标、代码结构、实验路线、RK3588 移植结果、MIPI 摄像头排查、去模糊尝试、离线部署包和下一步计划完整交接给后续对话或接手人员。

## 1. 项目最终目标

项目目标是在高速路固定摄像头场景下，尽可能接近原视频速度完成中文车牌识别，并最终部署到 RK3588 板端进行实地测试。

理想流程是：

1. 从固定摄像头或视频流中检测车辆。
2. 对车辆区域内车牌进行 OBB 检测。
3. 对车牌进行透视拉正，得到 `320x96` plate crop。
4. 调用 OCR 识别真实车牌号。
5. 对同一辆车多帧 OCR 结果进行投票。
6. 一旦投票锁定车牌号，后续不再对该 track 做 OBB/OCR，只继续跟踪车辆并显示已锁定车牌号。
7. 板端实时输出画面到 `/tmp/frame.jpg`，由浏览器流服务展示。

一句话目标：

> 锁定前识别，锁定后不再识别，只跟踪车辆并持续显示已锁定车牌号。

注意：`ocr-engine none` 或显示 `PLATE` 只是诊断模式，不是最终目标。最终目标必须显示真实车牌号。

## 2. 当前总体结论

### 2.1 Windows 主线已经形成

Windows 端主线是 `alpr_topk_capture.py`。它承担行为基准作用，不建议随意改动。

当前 Windows 主线能力包括：

- 车辆检测。
- 车牌 OBB 检测。
- vehicle track 维护。
- 每辆车 Top-K plate crop 保存。
- HyperLPR3 OCR。
- OCR 投票与锁定。
- 锁定后跳过该 track 的 plate/OCR。
- 可选弹窗显示。
- 输出 summary、候选 crop、rejected 样本、投票记录等诊断信息。

`alpr_topk_capture_demo.py` 是实验副本，可以污染主流程，用于测试去模糊、A/B、弹窗显示等功能。

### 2.2 RK3588 已经完成可运行部署

板端主脚本是 `rk3588_topk_capture.py`。它不是简单复制 Windows 代码，而是针对 RK3588 计算资源、依赖环境和实时要求设计过的板端流程。

已验证：

- RKNN 车辆模型可加载运行。
- RKNN 车牌 OBB 模型可加载运行。
- HyperLPR3 可在板端导入并运行。
- `/root/deploy/144.mp4` 视频自测可识别并锁定车牌。
- 新离线板部署后也能跑通视频自测。
- 离线依赖恢复包可在新板上恢复 `cv2`、`numpy`、`hyperlpr3`、`rknnlite`、`onnxruntime`。

典型视频自测结果：

- 新板 `run_video_selftest.sh --max-frames 1000` 可跑通。
- 能锁定 `冀JC5210`。
- 浏览器预览中曾看到 `LOCK 冀B6R9F9`。
- 新板视频自测 FPS 曾显示约 `13 FPS`。

### 2.3 RK 不能完全照搬 Windows 的原因

Windows 端和 RK 端差异很大，不能把 `alpr_topk_capture.py` 原封不动搬到板端。

主要原因：

1. Windows 端可用 Ultralytics/PyTorch，RK 端主要依赖 RKNNLite、OpenCV、NumPy。
2. Windows 端算力更强，能承受更频繁的检测和诊断保存；RK 端每次车辆检测、OBB、OCR 都会明显影响 FPS。
3. RK 端模型是 RKNN，输出结构、量化误差、推理速度和 Windows PyTorch 模型不同。
4. RK 端摄像头输入涉及 V4L2、MIPI、ISP、pixel format、media graph，不只是 `cv2.VideoCapture`。
5. RK 端实时流需要持续写 `/tmp/frame.jpg`，显示、写图、发布帧都会带来额外开销。
6. 板端 Python 环境缺少完整桌面生态，依赖安装和版本匹配比 Windows 更敏感。
7. 高速场景车辆远、小、运动快，板端不能对每帧所有目标都做完整 OCR 链路。

因此板端策略是：

- 车辆检测可降频。
- 已锁定 track 不再 OBB/OCR。
- 用 Kalman/predicted box 辅助显示。
- 支持 ROI 限定处理区域。
- 保留 Windows 等价模式用于对比，但实战使用 RK 自适应流程。

### 2.4 MIPI 摄像头当前结论

原板曾能看到 MIPI 画面，但存在发绿、发紫、暗、帧率低、手机图片测试不稳定等现象。

新线下测试板当前最大阻塞是：**MIPI 摄像头没有真实出帧**。

新板情况：

- IP：`192.168.8.88`
- 系统：Debian/Linux aarch64，`linaro-alip`
- 已部署离线包。
- 视频文件识别链路正常。
- MIPI 节点存在，`/dev/video53` 对应 `rkisp_mainpath`。
- media link 显示 enabled。
- V4L2/GStreamer 可以协商格式。
- 但抓图结果始终是 0 字节。

关键内核错误：

```text
imx585 2-0010: start stream failed while write regs
rkcif_update_sensor_info failed -19
get remote terminal sensor failed!
```

当前判断：

> 这不是 ALPR 代码、模型、Python 依赖的问题，而是新板 MIPI 摄像头硬件连接、sensor 型号、设备树、驱动、供电、接口或 IQ/ISP 初始化链路问题。

## 3. 远程与板端环境

### 3.1 Ubuntu 开发机

- IP：`192.168.217.128`
- 用户名：`apple`
- 系统：Ubuntu 22.04.5 LTS x86_64
- SSH 已验证可连接。

连接：

```powershell
ssh apple@192.168.217.128
```

### 3.2 原 RK3588 板子

- IP：`192.168.137.168`
- 用户名：`root`
- 系统：Debian/Linux aarch64，`linaro-alip`
- Windows 到板端 SSH 免密已配置。

连接：

```powershell
ssh root@192.168.137.168
```

板端主要目录：

```bash
/root/alpr_topk_rk3588
/root/deploy
```

板端测试视频：

```bash
/root/deploy/144.mp4
```

对应 Windows 视频：

```text
D:\YOLO_ALPR_Project\测试图\14.mp4
```

浏览器流：

```bash
cd /root/deploy
python3 stream.py
```

Windows 浏览器打开：

```text
http://192.168.137.168:8080
```

注意：`stream.py` 只负责读取 `/tmp/frame.jpg` 并展示，不负责摄像头采集或识别。

### 3.3 新线下实测板

- IP：`192.168.8.88`
- 通过向日葵远程控制另一台电脑，再由那台电脑 SSH 到板子。
- 远程电脑执行 `Test-NetConnection 192.168.8.88 -Port 22` 显示 `TcpTestSucceeded : True`。
- 已能从远程电脑 PowerShell 执行：

```powershell
ssh root@192.168.8.88
```

当前结论：

- 远程电脑可直连新板。
- Codex 当前所在机器未确认能直连 `192.168.8.88`。
- 由于是双层远程，不建议通过 UI 自动操作终端；更稳的是给命令、人工粘贴、截图反馈。

## 4. 项目文件结构

项目根目录：

```text
D:\YOLO_ALPR_Project
```

当前重要目录：

```text
D:\YOLO_ALPR_Project
  blur models
  captures
  captures_deblur_ab_full
  captures_deblur_bg_vote_full
  captures_deblur_bg_vote_probe
  captures_deblur_demo
  captures_topk
  captures_topk_ab
  captures_topk_ab_demo
  captures_topk_ab_demo_noocr
  Dataset
  LibreOffice
  LPDGAN
  models_run
  My_models
  obb_ab_single_frames
  PaddleCache
  python_deps
  python_deps_ocr
  report_render_work
  RK3588
  RK3588_dev
  tools
  Ultralytics
  汇报
  测试图
  论文
```

说明：

- `测试图`：本地测试图片和视频，重点是 `14.mp4`。
- `Dataset`：CCPD、CRPD、OBB 微调、去模糊数据集等。
- `RK3588_dev`：RKNN 模型、转换脚本、板端测试结果、离线部署包。
- `blur models`：去模糊模型和评估结果。
- `captures_*`：Windows 端 Top-K、deblur、A/B 输出。
- `汇报`：阶段汇报文档。
- `tools`：报告生成、辅助工具。
- `python_deps` / `python_deps_ocr`：Windows 侧依赖缓存或离线依赖。

## 5. 关键脚本与作用

### 5.1 `alpr_topk_capture.py`

路径：

```text
D:\YOLO_ALPR_Project\alpr_topk_capture.py
```

作用：

- Windows 主线行为基准。
- 使用 YOLO 车辆检测和 YOLO OBB 车牌检测。
- 维护车辆 track。
- 对每辆车保存 Top-K plate crop。
- 调 HyperLPR3 OCR。
- 维护 vote history、vote counts、locked_text。
- 生成 summary、候选图、rejected 样本。

重要原则：

- 不要随意改。
- 需要 Windows 实验时优先改 `alpr_topk_capture_demo.py`。

### 5.2 `alpr_topk_capture_demo.py`

路径：

```text
D:\YOLO_ALPR_Project\alpr_topk_capture_demo.py
```

作用：

- Windows 实验副本。
- 可用于接入去模糊、弹窗显示、A/B 测试。
- 用户明确允许污染 demo 主流程。

已做尝试：

- 接入去模糊实验分支。
- 支持 deblur 后后台 OCR 再投票的方向。
- 用于完整视频 deblur A/B 测试。

### 5.3 `rk3588_topk_capture.py`

路径：

```text
D:\YOLO_ALPR_Project\rk3588_topk_capture.py
```

板端路径：

```bash
/root/alpr_topk_rk3588/rk3588_topk_capture.py
```

作用：

- RK3588 板端主识别程序。
- 使用 RKNNLite 运行 vehicle 和 plate OBB RKNN 模型。
- 支持视频文件输入。
- 支持 MIPI 摄像头输入。
- 支持 HyperLPR3 OCR。
- 支持 `--publish-frame /tmp/frame.jpg` 给浏览器展示。
- 支持 RK 自适应流程、vehicle detect interval、predicted display、ROI、gray-world 等。

当前定位：

- 板端优化重点。
- 当前视频识别可跑通。
- MIPI 新板阻塞不在该脚本，而在摄像头链路。

### 5.4 `rk3588_topk_capture_mipi_debug.py`

路径：

```text
D:\YOLO_ALPR_Project\rk3588_topk_capture_mipi_debug.py
```

作用：

- MIPI/手机图片/临时 debug 版本。
- 用于排查摄像头、画面、直接 plate scan 等问题。
- 不作为道路实测主链路。

### 5.5 `mipi_current_frame_probe.py`

路径：

```text
D:\YOLO_ALPR_Project\mipi_current_frame_probe.py
```

作用：

- 读取 `/tmp/frame.jpg` 当前帧。
- 对当前画面跑 vehicle/plate/OCR 探测。
- 保存 `current_frame.jpg`、`annotated_probe.jpg`、`summary.json` 和 plate candidates。

注意：

- 它分析的是已有 `/tmp/frame.jpg`。
- 如果 `/tmp/frame.jpg` 是旧图，就会误以为正在识别旧视频画面。

### 5.6 `rk3588_mipi_isp_probe.py`

路径：

```text
D:\YOLO_ALPR_Project\rk3588_mipi_isp_probe.py
```

作用：

- 排查 RK3588 MIPI/ISP 颜色和取流问题。
- 关注 video node、pixel format、gray-world、ISP/3A 等。

### 5.7 `stream.py`

板端路径：

```bash
/root/deploy/stream.py
```

作用：

- 浏览器 MJPEG/HTTP 展示服务。
- 只读取 `/tmp/frame.jpg`。
- 不做识别、不做摄像头采集。

### 5.8 `test_deblur_hyperlpr3.py`

路径：

```text
D:\YOLO_ALPR_Project\test_deblur_hyperlpr3.py
```

作用：

- 独立测试静态图片经去模糊模型处理后，再送入 HyperLPR3 的识别情况。
- 可用于检查 deblur 是否真的提升 OCR，而不仅是视觉变锐。

### 5.9 `topk_report.py`

路径：

```text
D:\YOLO_ALPR_Project\topk_report.py
```

作用：

- 从 Top-K 输出目录生成 HTML 报告。
- 可查看每辆车候选 plate、vehicle crop、分数、OCR、rejected 原因。

### 5.10 `ocr_compare_topk.py`

路径：

```text
D:\YOLO_ALPR_Project\ocr_compare_topk.py
```

作用：

- 对已有 Top-K crop 复跑不同 OCR。
- 用于比较 plate-rec、HyperLPR3 等 OCR 效果。

### 5.11 OBB 与去模糊训练脚本

```text
prepare_obb_finetune_dataset.py
train_obb_colab.py
prepare_deblur_dataset.py
prepare_deblur_dataset_v2.py
train_deblur_colab.py
test_deblur_image.py
COLAB_DEBLUR_V2_E20_STEPS.md
OBB_FINETUNE_COLAB.md
```

作用概述：

- 构建 OBB 微调数据集。
- Colab 微调 OBB 模型。
- 构建去模糊数据集 v1/v2。
- Colab 训练轻量去模糊模型。
- 静态测试去模糊结果。

## 6. 模型与数据

### 6.1 Windows 模型

```text
D:\YOLO_ALPR_Project\yolo11n.pt
D:\YOLO_ALPR_Project\best_obb.pt
D:\YOLO_ALPR_Project\best_obb_finetuned_e8.pt
D:\YOLO_ALPR_Project\best_obb_finetuned_e20.pt
```

说明：

- `yolo11n.pt`：车辆检测。
- `best_obb.pt`：原始车牌 OBB。
- `best_obb_finetuned_e8.pt`：OBB 微调 8 轮。
- `best_obb_finetuned_e20.pt`：OBB 微调 20 轮，后续应转 RKNN 做板端 A/B。

### 6.2 RKNN 模型

主要路径：

```text
D:\YOLO_ALPR_Project\RK3588_dev
```

关键文件：

```text
vehicle.rknn
plate_obb.rknn
plate_rec.rknn
yolo11n.onnx
best_obb.onnx
plate_rec.onnx
onnx_to_rknn.py
convert_obb_640.py
convert_obb_640_fp16.py
```

板端部署路径：

```bash
/root/deploy/vehicle.rknn
/root/deploy/best_obb.rknn
```

说明：

- 当前板端主链路使用 `vehicle.rknn` 和 `best_obb.rknn`。
- OCR 当前主推 HyperLPR3，不主推 `plate_rec.rknn`。

### 6.3 去模糊模型

路径：

```text
D:\YOLO_ALPR_Project\blur models\deblur_v2_e20
```

关键文件：

```text
plate_restore_lite_v2_e20_320x96.onnx
plate_restore_lite_v2_e20_best.pt
plate_restore_lite_v2_e20_last.pt
metrics.csv
test_metrics.json
training_config.json
eval_captures_topk_all
static_hyperlpr3_test
```

当前结论：

- 去模糊模型已经训练好。
- 视觉上能改善部分 crop。
- OCR 增益不稳定，需要通过静态 Top-K crop 和完整视频 A/B 继续评估。
- 不建议立即接入 RK 实时主链路。
- 推荐先作为 Windows demo 后台 OCR 补票分支或离线复核层。

### 6.4 测试视频

Windows：

```text
D:\YOLO_ALPR_Project\测试图\14.mp4
```

板端：

```bash
/root/deploy/144.mp4
```

这两个视频内容相同，是 Windows/RK 对齐测试基准。

## 7. 已做的重要尝试

### 7.1 从单帧 fallback 改为 Top-K

早期 `alpr_sahi_snapshot2.py` 能从视频中截取车辆和车牌，但单帧 fallback 经常糊。

改进：

- 新建 Top-K 流程。
- 对每辆车多帧候选进行质量排序。
- 保存 full frame、vehicle crop、plate crop、summary。

结论：

- Top-K 能找到比单帧 fallback 更清晰的车牌帧。
- 是当前主线基础。

### 7.2 OCR 引擎比较

尝试过：

- PaddleOCR
- plate-rec
- plate-rec-cv2
- plate-rec-ort
- HyperLPR3

结论：

- PaddleOCR 对小而模糊的中文车牌不稳定，且速度慢。
- plate-rec 系列出现较多泛中文乱码。
- HyperLPR3 当前中文车牌识别相对最好。
- 当前主推 HyperLPR3。

### 7.3 OCR 投票

已实现和尝试：

- `vote_window`
- `vote_threshold`
- `min_char_vote_ratio`
- `min_ocr_conf`
- `vote_history`
- `vote_counts`
- `locked_text`
- `locked_confidence`

当前常用参数：

```text
vote_window=10
vote_threshold=3
min_char_vote_ratio=0.65
min_ocr_conf=0.70 或 0.75
```

结论：

- 投票是必要的。
- 不能只看单次 OCR。
- 增加 OCR 次数可能增加命中，也可能增加噪声。

### 7.4 RK Windows 等价模式

目的：

- 不先优化策略。
- 先让 RK 行为尽可能接近 Windows。
- 观察差异来自 RKNN 输出、输入尺寸、ROI、tracker、车辆检测降频、predicted box、HyperLPR3 调用对象还是诊断不足。

关键设置：

```bash
--vehicle-detect-interval 1
不启用 --plate-on-predicted
不启用 --hyperlpr-pre-ocr
不启用 --lock-on-plate-detect
--min-ocr-conf 0.70
--vote-window 10
--vote-threshold 3
--min-char-vote-ratio 0.65
```

结论：

- 等价模式有利于定位差异。
- 但速度明显慢，不适合实战默认。

### 7.5 RK 专用流程

为了接近实时，板端保留：

- `vehicle-detect-interval > 1`
- RK adaptive vehicle detection
- Kalman/predicted display
- `--plate-on-predicted`
- `--hyperlpr-pre-ocr`
- MIPI
- `--publish-frame`
- gray-world 白平衡
- ROI

结论：

- RK 应以最终目标为导向设计专门流程，而不是机械复刻 Windows。
- Windows 主线用于基准和实验，RK 主线用于部署实战。

### 7.6 tracker 与 re-association

观察：

- 有车辆在跟踪过程中 ID 会变化。
- 车牌号有时只显示一瞬间。
- `predicted=false` 表示当前框来自真实检测，不是预测框。

尝试：

- track max age。
- 中心距离阈值。
- Kalman predicted box。
- locked track re-association。
- plate anchor。

结论：

- 轻量 tracker 仍有优化空间。
- re-association 可能解决断轨，也可能引入错误关联。
- 当前先以简单、可解释、可诊断为优先。

### 7.7 Ctrl+C 保存保护

问题：

- 早期用户 Ctrl+C 后没有看到 summary 和 plate 截图。
- 后续观察到脚本可以捕获 KeyboardInterrupt 并保存当前 Top-K run。

正常表现：

```text
Interrupted by user; saving current Top-K results...
Saved Top-K capture run: /root/alpr_topk_rk3588/...
```

注意：

- 如果异常发生在 RKNN inference 内部，可能先抛 traceback。
- 当前脚本已尽量在 finally/interrupt 时保存结果。

### 7.8 去模糊尝试

用户提出的最终设计：

- 对当前没识别出来的 plate，在后台做 deblur。
- deblur 后再送入 OCR。
- deblur 结果不直接显示在当前视频画面。
- deblur OCR 结果进入后台投票。

当前判断：

- 这是合理方向。
- 但去模糊会占用算力，若每帧都跑会明显影响速度。
- 应先在 Windows demo 和离线 Top-K crop 中验证收益。
- RK 实时主链路暂不接入，除非静态 A/B 证明 OCR 提升足够明显。

已准备：

```text
D:\YOLO_ALPR_Project\blur models\deblur_v2_e20\eval_captures_topk_all
D:\YOLO_ALPR_Project\blur models\deblur_v2_e20\static_hyperlpr3_test
```

### 7.9 MIPI 颜色和亮度问题

观察：

- 画面有时发绿，有时正常。
- 画面很黑。
- 手机上举车辆图片给 MIPI 识别时，帧率低且识别不稳定。

判断：

- 颜色问题可能来自 pixel format、Bayer 顺序、ISP/IQ、白平衡、曝光。
- 低帧率可能来自摄像头高分辨率、MIPI 取流方式、OCR/OBB 开销、显示发布开销。
- 手机图片测试不是道路真实场景，容易受屏幕反光、摩尔纹、亮度、角度影响。

## 8. RK 测试结果摘要

### 8.1 视频自测基础结果

已在原板和新板验证：

- `/root/deploy/144.mp4` 可跑。
- RKNN 模型可加载。
- HyperLPR3 可导入。
- 能锁定至少部分车牌。
- run 目录会保存结果。

新板截图中出现：

```text
Processed 100 frames ... fps=13.58
[LOCK] track=4 plate=冀JC5210 frame=293 events=3
Processed 600 frames ... fps=13.06
```

### 8.2 不同 RK 实验目录

`D:\YOLO_ALPR_Project\RK3588_dev` 下保留了多轮结果：

```text
rk_baseline_no_reassoc
rk_tracker_defaults
rk_tracker_tune
rk_tracker_tune_ocr075
rk_plate_predicted_i1
rk_plate_predicted_i2
rk_hyperlpr_pre_i2
rk_hyperlpr_pre_dedup_i1
rk_noocr_plate_lock_ab
rk_windows_equiv_i1
rk_windows_equiv_i3
rk_windows_equiv_i3_pred
rk_windows_equiv_i3_pre
rk_adaptive_i3
run_20260626_074232
```

经验结论：

- `vehicle-detect-interval 1` 更接近 Windows，但速度明显下降。
- `vehicle-detect-interval 3` 或 RK adaptive 更适合板端速度。
- `--plate-on-predicted` 能增加 plate/OCR 机会，但也可能引入噪声。
- `--hyperlpr-pre-ocr` 对部分车辆有帮助，对部分车辆会引入错误票。
- no-OCR plate-lock 可以证明“检测到车牌后跟踪显示”可行，但不是最终目标。

### 8.3 速度现象

用户观察到不同命令 FPS 差异明显：

- 一些 RK 自适应视频测试可达到约 `11-13 FPS`。
- Windows 等价模式或更重诊断模式可能降到 `4-5 FPS`。
- MIPI 手机图片测试时可能只有 `2-3 FPS`。

主要原因：

- 车辆检测频率不同。
- 是否每帧做 OBB/OCR。
- 是否启用 predicted plate。
- 是否发布画面。
- 是否写图和保存诊断。
- MIPI 分辨率和取流方式不同。
- 摄像头/ISP 状态影响输入。

## 9. 新板离线部署包

Windows 离线包路径：

```text
D:\YOLO_ALPR_Project\RK3588_dev\offline_bundle\rk3588_alpr_roadtest_bundle_20260701.tar.gz
```

大小约：

```text
502 MB
```

SHA256：

```text
97CB350E15B4A9E4A0423C606E2E692D7127A5DBBF29D36BD339650348D15046
```

配套文档：

```text
D:\YOLO_ALPR_Project\RK3588_dev\offline_bundle\README_ROAD_TEST.md
D:\YOLO_ALPR_Project\RK3588_dev\offline_bundle\ROAD_TEST_OPERATOR_GUIDE.md
```

包内主要内容：

```text
alpr_topk_rk3588/rk3588_topk_capture.py
alpr_topk_rk3588/rk3588_topk_capture_mipi_debug.py
alpr_topk_rk3588/mipi_current_frame_probe.py
alpr_topk_rk3588/run_mipi_road.sh
alpr_topk_rk3588/run_video_selftest.sh
deploy/stream.py
deploy/run_stream.sh
deploy/vehicle.rknn
deploy/best_obb.rknn
deploy/144.mp4
tools/check_env.sh
tools/restore_python_packages.sh
tools/install_to_root.sh
tools/stop_all.sh
offline_python/python3.9_dist-packages
wheels/rknn_toolkit_lite2-1.6.0-cp39-cp39-linux_aarch64.whl
```

安装：

```bash
cd /root
tar -xzf rk3588_alpr_roadtest_bundle_20260701.tar.gz
/root/rk3588_alpr_roadtest_bundle_20260701/tools/install_to_root.sh
/root/rk3588_alpr_roadtest_bundle_20260701/tools/check_env.sh
```

如果缺依赖：

```bash
/root/rk3588_alpr_roadtest_bundle_20260701/tools/restore_python_packages.sh
/root/rk3588_alpr_roadtest_bundle_20260701/tools/check_env.sh
```

曾遇到：

```text
ERROR: No matching distribution found for psutil
```

但离线 site-packages 已复制，后续 `check_env.sh` 显示关键模块均 OK：

```text
cv2: OK
numpy: OK
hyperlpr3: OK
rknnlite: OK
onnxruntime: OK
RKNNLite import: OK
```

视频自测：

```bash
cd /root/alpr_topk_rk3588
./run_video_selftest.sh --max-frames 1000
```

## 10. 新板 MIPI 排查记录

### 10.1 节点枚举

新板发现的关键节点：

```text
/dev/video22 - /dev/video32   rkcif-mipi-lvds2
/dev/video44 - /dev/video50   rkisp0-vir0 mainpath
/dev/video53 - /dev/video59   rkisp0-vir2 mainpath
/dev/video62...               rkisp1-vir0
```

`/dev/video53` 对应：

```text
rkisp_mainpath
device node name /dev/video53
```

media 链路中可见：

```text
rkcif-mipi-lvds2 -> rkisp-isp-subdev -> rkisp_mainpath /dev/video53
```

### 10.2 试过的 V4L2 命令

`/dev/video22`：

```bash
timeout 5 v4l2-ctl -d /dev/video22 \
  --set-fmt-video=width=1280,height=720,pixelformat=UYVY \
  --stream-mmap=4 \
  --stream-count=30 \
  --stream-to=/tmp/video22.raw \
  --verbose
```

结果：

- `UYVY is invalid`
- `STREAMON Input/output error`
- raw 0 字节。

`/dev/video44`：

```bash
timeout 5 v4l2-ctl -d /dev/video44 \
  --set-fmt-video=width=1280,height=720,pixelformat=NV12 \
  --stream-mmap=4 \
  --stream-count=30 \
  --stream-to=/tmp/video44_nv12.raw \
  --verbose
```

结果：

- 格式可设。
- `STREAMON Operation not permitted`
- raw 0 字节。

`/dev/video53`：

```bash
timeout 5 v4l2-ctl -d /dev/video53 \
  --set-fmt-video=width=1280,height=720,pixelformat=NV12 \
  --stream-mmap=4 \
  --stream-count=30 \
  --stream-to=/tmp/video53_nv12.raw \
  --verbose
```

结果：

- `STREAMON Success`
- 但 raw 仍为 0 字节。

4K 原生测试：

```bash
timeout 8 v4l2-ctl -d /dev/video53 \
  --set-fmt-video=width=3840,height=2160,pixelformat=UYVY \
  --stream-mmap=4 \
  --stream-count=5 \
  --stream-to=/tmp/video53_4k_uyvy.raw \
  --verbose
```

结果：

- `STREAMON Success`
- raw 仍为 0 字节。

### 10.3 试过的 GStreamer 命令

```bash
timeout 8 gst-launch-1.0 -e -v \
  v4l2src device=/dev/video53 num-buffers=1 io-mode=2 \
  ! "video/x-raw,format=UYVY,width=3840,height=2160,framerate=30/1" \
  ! videoconvert \
  ! jpegenc \
  ! filesink location=/tmp/video53_gst.jpg
```

结果：

- 管线能建立。
- `video53_gst.jpg` 仍是 0 字节。
- 没有真实图像帧。

### 10.4 进程占用排查

发现过：

```text
/dev/video53 被 gst-launch-1.0 占用
/root/mediamtx 进程运行
```

尝试停止：

```bash
pkill -f mediamtx
pkill -f gst-launch-1.0
pkill -f rk3588_topk_capture.py
pkill -f v4l2-ctl
fuser -v /dev/video53 /dev/video44 /dev/video62
```

结果：

- 停止占用后仍然无法出图。
- 因此不是单纯进程占用导致。

### 10.5 内核错误

清空日志后重测：

```bash
dmesg -C
# run gst/v4l2 test
dmesg | tail -n 100
```

关键错误反复出现：

```text
imx585 2-0010: start stream failed while write regs
rockchip-mipi-csi2 ... stream on
rockchip-csi2-dphy ... stream on
rkcif_update_sensor_info failed -19
get remote terminal sensor failed!
```

结论：

- sensor `imx585` 启流时写寄存器失败。
- 需要检查摄像头硬件、排线、供电、设备树、驱动、IQ 文件、MIPI 接口。

### 10.6 发给现场人员的检查事项

现场应做：

1. 断电后重新插拔 MIPI 排线，不要热插拔。
2. 检查排线方向、金手指方向、卡扣是否压紧。
3. 确认摄像头模组是否真的是 IMX585。
4. 确认摄像头插在当前设备树对应的 MIPI 口。
5. 尝试替换排线或摄像头模组。
6. 使用厂家原厂摄像头测试程序确认能否出画面。
7. 检查是否有正确的 IMX585 IQ 文件。
8. 如果仍报 `start stream failed while write regs`，应联系板卡/模组厂家确认驱动和硬件匹配。

## 11. 常用运行命令

### 11.1 Windows demo，完整视频加 deblur

```powershell
cd D:\YOLO_ALPR_Project

D:\miniconda\envs\alpr_env\python.exe .\alpr_topk_capture_demo.py `
  --video "D:\YOLO_ALPR_Project\测试图\14.mp4" `
  --output "D:\YOLO_ALPR_Project\captures_deblur_bg_vote_full" `
  --live-ocr `
  --ocr-engine hyperlpr3 `
  --deblur-model "D:\YOLO_ALPR_Project\blur models\deblur_v2_e20\plate_restore_lite_v2_e20_320x96.onnx" `
  --deblur-mode always `
  --progress-interval 100
```

去模糊后图片和识别结果位置应查看输出目录：

```text
D:\YOLO_ALPR_Project\captures_deblur_bg_vote_full
```

重点看：

- 每个 track 的 summary。
- deblur 相关 crop。
- vote history。
- OCR/deblur OCR 记录。

### 11.2 Windows 静态 deblur + HyperLPR3 测试

```powershell
cd D:\YOLO_ALPR_Project

D:\miniconda\envs\alpr_env\python.exe .\test_deblur_hyperlpr3.py `
  --model "D:\YOLO_ALPR_Project\blur models\deblur_v2_e20\plate_restore_lite_v2_e20_320x96.onnx" `
  --input "D:\YOLO_ALPR_Project\blur models\deblur_v2_e20\eval_captures_topk_all" `
  --output "D:\YOLO_ALPR_Project\blur models\deblur_v2_e20\static_hyperlpr3_test"
```

### 11.3 板端视频自测

```bash
cd /root/alpr_topk_rk3588

python3 rk3588_topk_capture.py \
  --video /root/deploy/144.mp4 \
  --vehicle-model /root/deploy/vehicle.rknn \
  --plate-model /root/deploy/best_obb.rknn \
  --ocr-engine hyperlpr3 \
  --output /root/alpr_topk_rk3588/runs_rk_video_equiv \
  --vehicle-detect-interval 1 \
  --vehicle-conf 0.45 \
  --min-process-vehicle-conf 0.45 \
  --min-ocr-conf 0.70 \
  --vote-window 10 \
  --vote-threshold 3 \
  --min-char-vote-ratio 0.65 \
  --publish-frame /tmp/frame.jpg \
  --publish-interval 2 \
  --progress-interval 100
```

更适合速度的 RK 自适应测试：

```bash
cd /root/alpr_topk_rk3588

python3 rk3588_topk_capture.py \
  --video /root/deploy/144.mp4 \
  --vehicle-model /root/deploy/vehicle.rknn \
  --plate-model /root/deploy/best_obb.rknn \
  --ocr-engine hyperlpr3 \
  --output /root/alpr_topk_rk3588/runs_rk_adaptive_full \
  --vehicle-detect-interval 3 \
  --rk-adaptive \
  --min-ocr-conf 0.70 \
  --vote-window 10 \
  --vote-threshold 3 \
  --min-char-vote-ratio 0.65 \
  --publish-frame /tmp/frame.jpg \
  --publish-interval 2 \
  --progress-interval 100
```

### 11.4 板端浏览器显示

```bash
cd /root/deploy
python3 stream.py
```

或离线包脚本：

```bash
cd /root/deploy
./run_stream.sh
```

浏览器：

```text
http://板子IP:8080
```

### 11.5 新板 MIPI road 命令

如果摄像头链路修好，推荐从：

```bash
cd /root/alpr_topk_rk3588

CAMERA_DEVICE=/dev/video53 ./run_mipi_road.sh \
  --mipi-fourcc UYVY \
  --mipi-color-mode uyvy \
  --process-roi 0.05 0.25 0.95 1.00 \
  --draw-process-roi
```

如果实际节点不是 `/dev/video53`，替换 `CAMERA_DEVICE`。

## 12. 结果目录怎么看

板端 run 目录通常类似：

```bash
/root/alpr_topk_rk3588/runs_mipi_road/run_时间戳
/root/alpr_topk_rk3588/runs_rk_adaptive_full/run_时间戳
/root/alpr_topk_rk3588/runs_rk_video_equiv/run_时间戳
```

常见文件：

```text
run_summary.json
track_*/summary.json
track_*/plate_rank*.jpg
track_*/vehicle_rank*.jpg
track_*/full_rank*.jpg
track_*/rejected/
```

关注点：

- `locked_text`
- `locked_frame`
- `locked_confidence`
- `vote_history`
- `vote_counts`
- `seen_frames`
- `plate_hits`
- `rejected_candidates`
- FPS

拉回 Windows：

```powershell
scp -r root@192.168.137.168:/root/alpr_topk_rk3588/runs_rk_adaptive_full D:\YOLO_ALPR_Project\RK3588_dev
```

新板如果能被当前 Windows 直连：

```powershell
scp -r root@192.168.8.88:/root/alpr_topk_rk3588/runs_mipi_road D:\YOLO_ALPR_Project\RK3588_dev\road_test_new_board
```

如果无网络，用板端打包后 U 盘拷贝：

```bash
cd /root/alpr_topk_rk3588
tar -czf road_test_runs_$(date +%Y%m%d_%H%M%S).tar.gz runs_mipi_road
```

## 13. 当前未解决问题

### 13.1 新板 MIPI 摄像头不出帧

当前最紧急阻塞。

状态：

- V4L2/GStreamer 均无法获得非 0 字节图像。
- 内核报 `imx585 start stream failed while write regs`。

下一步：

- 现场硬件检查。
- 确认 sensor 型号。
- 确认设备树和 MIPI 口。
- 查 IQ 文件。
- 找厂家原厂摄像头测试命令。

### 13.2 RK 跟踪和锁定显示仍需优化

表现：

- 某些车辆 ID 会变化。
- 车牌号有时只显示一瞬间。
- 锁定文本和车辆框绑定还需更稳。

下一步：

- 优化 locked track 的预测显示。
- 谨慎引入 re-association。
- 保留诊断字段，逐轮对比。

### 13.3 OBB 命中仍不足

表现：

- 部分车辆最适合识别时没有足够 plate hit。
- OCR 有效票数不足。

下一步：

- 将 `best_obb_finetuned_e20.pt` 转 RKNN。
- 与当前 `best_obb.rknn` 做 A/B。
- 分析 rejected 样本和 Top-K crop 质量。

### 13.4 去模糊是否进入主链路仍未定

当前建议：

- Windows demo 和离线 crop 先验证。
- 若 OCR 收益明确，再考虑作为后台补票层。
- 不建议马上放入 RK 实时主链路。

### 13.5 FPS 仍需分场景优化

方向：

- 合理 ROI。
- 降低车辆检测频率。
- 已锁定 track 跳过 OBB/OCR。
- 降低发布帧频率。
- 减少实时写图诊断。
- 修通 MIPI 后再测真实摄像头 FPS。

## 14. 后续建议路线

### 第一阶段：先修通新板 MIPI 出图

完成标准：

- `gst-launch` 或 `v4l2-ctl` 能生成非 0 字节 jpg/raw。
- 浏览器能看到新板真实摄像头画面。
- `rk3588_topk_capture.py --video mipi` 能持续处理帧。

### 第二阶段：现场道路实测

完成标准：

- MIPI 对准真实道路车辆。
- 跑 `run_mipi_road.sh`。
- 保存完整 run。
- 至少记录 FPS、vehicle hits、plate hits、locked_text、错误样本。

### 第三阶段：OBB 模型上板 A/B

完成标准：

- `best_obb_finetuned_e20.pt` 转 RKNN。
- 同视频、同参数、同 1000 帧对比。
- 重点比较 plate hit、locked frame、OCR 票数、FPS。

### 第四阶段：deblur 离线/后台补票验证

完成标准：

- 完整视频 Windows demo 跑 deblur A/B。
- 输出 deblur crop。
- 比较 deblur 前后 HyperLPR3 OCR。
- 判断是否值得加入 RK 后台补票。

## 15. 新对话关键提醒

1. `alpr_topk_capture.py` 是 Windows 基准脚本，不要随意改。
2. Windows 实验用 `alpr_topk_capture_demo.py`。
3. RK 优化重点是 `rk3588_topk_capture.py`。
4. 当前 OCR 主推 HyperLPR3。
5. 板端视频测试至少跑到 frame 1000，不要只看前几百帧。
6. 浏览器显示的是 `/tmp/frame.jpg`，不代表识别程序一定正在跑。
7. 如果识别程序不写新帧，浏览器会显示旧画面。
8. 新板视频识别链路正常，MIPI 不出帧是硬件/驱动链路问题。
9. 去模糊已训练好，但是否进入实时链路要看 OCR A/B 收益。
10. RK 不能机械复刻 Windows，需要专门为算力、NPU、MIPI、实时性设计流程。

## 16. 当前一句话状态

Windows Top-K + HyperLPR3 主线已经成型；RK3588 视频文件识别和离线部署已跑通；去模糊模型已训练并进入 Windows demo/离线评估阶段；新线下板当前阻塞在 MIPI IMX585 摄像头无法出帧，需先由现场检查摄像头硬件、驱动、设备树和原厂取流方式，修通出图后再继续道路实测。
