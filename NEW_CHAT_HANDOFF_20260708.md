# 新对话完整交接文档

更新时间：2026-07-08

用途：本文件用于新开 Codex 对话时快速接手当前项目。它是对本轮长对话、现有记忆文件、关键脚本和远程 SC850SL 调试过程的集中总结。新 AI 接手时应先读 `AGENTS.md`，再读本文件，然后按需阅读 `PROJECT.md`、`STATUS.md`、`DECISIONS.md`、`HANDOFF.md` 和源码。

重要说明：本文件中的“事实”来自用户截图、已读项目文件或已完成命令；“推断”是基于这些事实的工程判断；不确定内容统一标注“待确认”。

## 一句话目标

在 RK3588 板端接入真实道路摄像头，完成固定机位车辆车牌识别：车辆进入画面后先检测车辆，再在车辆区域内检测车牌 OBB，OCR 得到真实车牌号，多帧投票锁定后把车牌号显示在对应车辆上方，并跟随车辆直到 YOLO 或预测跟踪都无法继续框住该车辆。

## 最终验收目标

- 输入可以来自视频文件或 MIPI 摄像头，最终重点是远程 SC850SL 摄像头实时道路画面。
- 输出浏览器实时画面，车辆框、车牌框和真实车牌号要叠加显示。
- 车牌锁定前允许多帧 OCR 投票；锁定后不再重复对同一 track 做 OBB/OCR，只继续跟踪并显示锁定车牌。
- `ocr-engine none`、`PLATE`、`LOCK PLATE` 这类占位显示只是诊断模式，不能当成真实车牌识别完成。
- RK 端视频回归至少跑到 frame 1000，不能只看前几百帧下结论。

## 当前最重要结论

### 事实

- Windows Top-K + HyperLPR3 主线已经形成，基准脚本是 `alpr_topk_capture.py`。
- RK3588 视频文件链路已经跑通，主脚本是 `rk3588_topk_capture.py`。
- 本地 IMX585 RK3588 板运行内置场地视频 `/root/deploy/144.mp4` 1000 帧，约 10 FPS，曾锁定 `冀JC5210` 和 `冀B6R9F9`。
- 远程 SC850SL 板运行同一个内置场地视频时，表现与本地 IMX585 板一致，也能正常显示彩色视频并锁定 `冀JC5210`。
- 远程板实际摄像头模组是 SC850SL，不是 IMX585。
- `/dev/video33` 能输出 SC850SL `BG10` RAW10 原始帧，5 帧约 51 MB，约 30 FPS，可转灰度预览。
- `/dev/video71` 已通过 `sc850_rkaiq_debug_20250626_142419` 证据包确认可输出 SC850SL 标准 ISP `NV12`，4K 5 帧约 60 MB，约 30 FPS。
- `/dev/video71` 所属链路为 `m01_b_sc850sl 4-0030 -> rockchip-csi2-dphy3 -> rockchip-mipi-csi2 -> rkcif-mipi-lvds4 -> rkisp1-vir1 -> /dev/video71`。
- `/dev/video-camera0 -> video71`。
- `/dev/video44` 属于另一条 `rkisp0-vir0` 链路，报 `check rkisp_mainpath link or isp input`，不应再当作 SC850SL 4K ISP 主输出。
- `/dev/video53` 也是 ISP mainpath，但上游是另一条 `rkcif-mipi-lvds2/SRGGB12_1X12` 链，不是已确认的 SC850SL 链，只能作对照。
- 当前实时道路画面已能通过 `/tmp/frame.jpg` + 浏览器刷新看到。
- 用 `/dev/video71` NV12 后，实时画面已经是正常彩色图，远好于早期 `/dev/video33` RAW10 灰度图。
- 低阈值车辆检测已经能框到汽车，但也会框到电动车、车轮或非目标区域。

### 推断

- 当前 SC850SL 问题不是 ALPR 主流程坏了，而是实时摄像头输入、图像域、曝光、ROI、候选质量和模型适配问题。
- `/dev/video33` RAW10 灰度只是临时救生绳；主路线应切到 `/dev/video71` 标准 ISP `NV12`。
- 远程实时场景与内置高速视频差别很大：画面为城市道路高位俯视，车辆尺寸、角度、遮挡、车道 ROI、电动车干扰和曝光都影响 vehicle 模型。
- `vehicle-conf=0.10` 或 `0.12` 是为了找候选的诊断阈值，容易误检电动车/行人/车轮/路面结构；最终需要根据真实车辆命中率提高阈值或加过滤。
- `vehicle-source motion` 能帮助固定机位抓运动汽车，但它不是车辆分类器，必须用尺寸、长宽比、车道 ROI、稳定跟踪和车牌验证过滤非汽车运动物体。

### 建议

- 新对话不要再从“摄像头是否出图”重新开始；优先沿 `/dev/video71` NV12 实时 ALPR 继续调。
- 先把车辆框质量调稳定，再调车牌 OBB/OCR。车辆框不稳定时，车牌识别没有意义。
- 当前优先做：收窄车道 ROI、提高 vehicle 阈值、过滤电动车/行人/车轮、保留真实汽车框。

## 当前推荐实时命令

用户最近使用的方向是正确的：`/dev/video71` + `NV12` + `vehicle-source rknn`。注意原命令中 `--publish-frame` 和 `--publish-interval` 重复了一次，且 `--max-frames 300` 前一行缺少续行反斜杠时会被 shell 当成新命令；新对话需要帮用户检查命令格式。

推荐先跑车辆框诊断，不急着 OCR：

```bash
cd /root/alpr_topk_rk3588

python3 rk3588_topk_capture_mipi_debug_sc850.py \
  --video mipi \
  --camera-device /dev/video71 \
  --camera-width 3840 \
  --camera-height 2160 \
  --mipi-backend v4l2ctl \
  --mipi-fourcc NV12 \
  --mipi-color-mode nv12 \
  --vehicle-model /root/rk3588_alpr_roadtest_bundle_20260701/deploy/vehicle.rknn \
  --plate-model /root/rk3588_alpr_roadtest_bundle_20260701/deploy/best_obb.rknn \
  --ocr-engine none \
  --output /root/alpr_topk_rk3588/runs_sc850_video71_nv12_vehicle_probe \
  --detect-roi 0.03 0.15 0.55 0.95 \
  --draw-detect-roi \
  --process-roi 0.03 0.15 0.55 0.95 \
  --draw-process-roi \
  --vehicle-source rknn \
  --vehicle-detect-interval 1 \
  --vehicle-conf 0.12 \
  --detect-roi-tiles 2 2 \
  --detect-roi-overlap 0.18 \
  --min-process-vehicle-conf 1.10 \
  --publish-frame /tmp/frame.jpg \
  --publish-interval 1 \
  --progress-interval 20 \
  --max-frames 0
```

如果误检电动车、车轮很多，下一步不要立刻调 OCR，应先尝试：

- 收窄 `--detect-roi` 到机动车道，排除右侧人行道/非机动车道。
- 逐步把 `--vehicle-conf` 从 `0.12` 提到 `0.18`、`0.22`、`0.28`，观察汽车是否仍能框到。
- 如仍误检严重，考虑在代码里加 class、面积、长宽比、车道位置、运动一致性过滤。代码改动应放在 `rk3588_topk_capture_mipi_debug_sc850.py`，不要污染 Windows 基准主线。

## 浏览器实时画面原理

当前浏览器实时画面不是 RTSP，也不是真正的视频流。原理是：

1. ALPR 程序每隔 `--publish-interval` 帧把当前叠框画面写到 `/tmp/frame.jpg`。
2. 板子在 `/tmp` 目录启动一个静态 HTTP 服务，例如：

```bash
cd /tmp
python3 -m http.server 8080
```

3. `/tmp/view.html` 里有一个 `<img src="/frame.jpg">`。
4. JavaScript 每 500ms 把图片地址改成 `/frame.jpg?t=当前时间戳`，强制浏览器重新请求最新 JPEG，避免缓存。

示例：

```html
<img id="cam" src="/frame.jpg">
<script>
setInterval(function () {
  document.getElementById('cam').src = '/frame.jpg?t=' + Date.now();
}, 500);
</script>
```

注意：`/tmp/frame.jpg` 可能是旧帧。判断程序是否在跑，要看画面左上角 `frame:` 是否增长，或检查文件修改时间/MD5。

## 已实现功能

- Windows 端 Top-K 车牌识别主线。
- 车辆检测、车牌 OBB、透视拉正、HyperLPR3 OCR、多帧投票、锁定后跳过 OBB/OCR、浏览器发布。
- Windows demo/实验脚本，用于 deblur、A/B、弹窗显示。
- RK3588 视频文件输入链路。
- RKNN vehicle 和 plate OBB 模型加载。
- HyperLPR3 在 RK 端导入和调用。
- RK 端 `/tmp/frame.jpg` 发布。
- `rk3588_topk_capture.py` 支持 BG10/raw10-gray、detect ROI 等。
- `rk3588_topk_capture_mipi_debug_sc850.py` 支持 SC850SL 相关 MIPI 调试：
  - `BG10` / `raw10-gray`
  - `raw10-stride`
  - `NV12` / `nv12`
  - 检测前 ROI
  - ROI 分块检测
  - motion / hybrid 候选源
  - motion 尺寸、长宽比、填充率和 accept ROI 过滤
  - publish `/tmp/frame.jpg`
- SC850SL ISP 探针脚本 `RK3588_dev/sc850_isp_probe.sh`。
- 远程交接文档 `REMOTE_CODEX_HANDOFF.md`。

## 已做过的主要尝试

### Windows 主线

- 从早期 snapshot/SAHI 思路，逐步切到 Top-K 车辆 track 候选。
- 对 PaddleOCR、plate-rec、HyperLPR3 做过比较；当前主推 HyperLPR3。
- 建立 OCR 投票和 locked text 机制。
- 建立 rejected 样本、summary、vote history 等诊断输出。
- 做过 deblur 训练和离线 A/B，但收益未稳定，未进入 RK 实时主链路。

### RK 视频链路

- 将车辆和车牌模型转为 RKNN。
- 在 RK3588 上跑 `/root/deploy/144.mp4`。
- 验证本地 IMX585 板视频回归可锁车牌。
- 验证远程 SC850SL 板视频回归同样可锁车牌。

### SC850SL RAW10 灰度链路

- 确认 `/dev/video33` 可输出 `BG10` RAW10。
- 转灰度预览，画面可见道路和车辆。
- 加入 `raw10-gray` 输入支持。
- 发现整图缩放后车辆过小，`tracks=0`。
- 加入 `--detect-roi` 裁剪道路区域。
- 加入 `--detect-roi-tiles` 分块放大。
- 分块后 vehicle 模型开始输出框，但夜间/灰度低阈值下大量假阳性，框到广告牌、灯箱、路边结构。
- 结论：灰度 RAW10 可用作诊断，但不适合作最终主输入。

### SC850SL 曝光与图像质量

- 夜间曝光 1200 左右可看到道路。
- 白天沿用夜间曝光会严重过曝，大片纯白。
- 白天尝试降低 exposure；`exposure=380` 时图像层次明显恢复，但仍有高光溢出。
- 一次曝光扫描截图都显示同一 `frame:500`，推断当时可能复制的是旧 `/tmp/frame.jpg`，后续扫描前必须确认实时刷新。

### SC850SL ISP 链路

- 初期误以为 `/dev/video44` 可能是 ISP 输出，但它报 `check rkisp_mainpath link or isp input`。
- 通过 `sc850_isp_probe_20250626_124614` 证据包确认：
  - `/dev/video44` 不是 SC850SL 主输出。
  - `/dev/video53` 是另一路 ISP mainpath，不是 SC850SL 链。
  - `/dev/video71` 才是 SC850SL `rkisp1-vir1` mainpath。
- 初次手工测试 `/dev/video71` 曾出现 0 字节，并伴随 `can not get first iq setting`。
- 后续 `sc850_rkaiq_debug_20250626_142419` 证据包确认 `/dev/video71` 4K NV12 已成功出帧。
- 结论更新：SC850SL 标准 ISP 输出链路已通，主线切到 `/dev/video71`。

### SC850SL 实时检测

- `/dev/video71` NV12 实时画面已恢复彩色。
- 使用 `vehicle-source rknn`、低阈值和 ROI 后，汽车框明显改善。
- 仍会框电动车、车轮或其他非汽车目标。
- `vehicle-source motion` 能框到真实运动汽车，但也会框到电动车/车轮，所以只能作为候选源。
- 当前问题从“没有图/灰度不适配”推进到“实时车辆候选质量需要收敛”。

## 关键文件结构

项目根目录：

```text
D:\YOLO_ALPR_Project
```

### 长期记忆文件

- `AGENTS.md`：AI 协作规则、沟通方式、流程和红线。只有规则变化才更新。
- `PROJECT.md`：项目目标、需求、验收标准和不能随便修改的内容。
- `STATUS.md`：已完成、正在进行、当前卡点和下一步。
- `DECISIONS.md`：关键技术决定和原因。
- `HANDOFF.md`：新 AI 接手阅读顺序、当前状态和第一步。
- `PROJECT_HANDOFF.md`：较早的历史交接背景，部分结论可能已被后续更新覆盖。
- `REMOTE_CODEX_HANDOFF.md`：之前为远程 Windows 新 Codex 准备的交接材料。
- `NEW_CHAT_HANDOFF_20260708.md`：本文件，新对话完整总览。

### Windows 主线脚本

- `alpr_topk_capture.py`：Windows 基准主线，不要随意修改。
- `alpr_topk_capture_demo.py`：Windows 实验副本，适合做 demo、deblur、A/B、临时显示改动。
- `ocr_compare_topk.py`：对 Top-K crop 重新跑 OCR 比较。
- `topk_report.py`：生成 Top-K 结果报告。
- `hyperlpr3_ocr.py`：HyperLPR3 OCR 相关测试/封装。
- `plate_rec_ocr.py`：plate-rec OCR 相关测试/封装。

### RK3588 脚本

- `rk3588_topk_capture.py`：RK3588 主脚本，视频文件和板端主流程重点。
- `rk3588_topk_capture_mipi_debug.py`：较新的 MIPI 调试参考脚本，在用户 IMX585 板上摄像头能正常识别；不要直接污染。
- `rk3588_topk_capture_mipi_debug_sc850.py`：SC850SL 适配副本，当前远程实时摄像头调试主要改这个。
- `rk3588_mipi_isp_probe.py`：早期 MIPI/ISP 探针。
- `mipi_current_frame_probe.py`：分析当前 `/tmp/frame.jpg` 的工具；注意可能读到旧帧。

### RK3588_dev 目录

```text
D:\YOLO_ALPR_Project\RK3588_dev
```

主要内容：

- `vehicle.rknn`：RK 车辆检测模型。
- `plate_obb.rknn`：RK 车牌 OBB 模型。
- `plate_rec.rknn`：plate-rec 模型，当前主 OCR 不是它。
- `convert_obb_640.py`、`convert_obb_640_fp16.py`、`onnx_to_rknn.py`：模型转换脚本。
- `sc850_isp_probe.sh`：远程 SC850SL 板一键探针脚本。
- `sc850_isp_probe_20250626_124614`：用户传回并解压的 SC850SL ISP 探针包。
- `sc850_rkaiq_debug_20250626_142419.tar.gz` 和 `sc850_rkaiq_debug_20250626_142419_extract`：确认 `/dev/video71` NV12 成功出帧的证据包。
- `offline_bundle`：远程部署压缩包目录。用户提到 `rk3588_alpr_roadtest_bundle_20260701.tar` 位于此处；实际扩展名和当前内容待确认。
- `mipi_color_probe`、`mipi_current_probe_live` 等：MIPI 颜色/当前帧探针结果。
- `rk_*` 目录：不同 RK 实验 run 输出，例如 tracker、reassoc、windows-equivalent、adaptive 等。

### 训练和模型相关

- `best_obb.pt`：当前 Windows 车牌 OBB 基础模型。
- `best_obb_finetuned_e8.pt`、`best_obb_finetuned_e20.pt`：OBB finetune 结果，后续计划转 RKNN 做 A/B。
- `yolo11n.pt`、`yolov8n.pt`：YOLO 权重。
- `RealESRGAN_x4plus.pth`、`ESPCN_x4.pb`、`blur models`、`LPDGAN`：去模糊/超分相关。
- `prepare_obb_finetune_dataset.py`、`train_obb_colab.py`：OBB finetune 数据准备和训练。
- `prepare_deblur_dataset.py`、`prepare_deblur_dataset_v2.py`、`train_deblur_colab.py`、`test_deblur_image.py`、`test_deblur_hyperlpr3.py`：deblur 数据、训练和评估。

### 输出和数据目录

- `captures*`：Windows 端多轮识别输出。
- `captures_topk*`：Top-K 相关输出。
- `captures_deblur*`：deblur A/B 输出。
- `Dataset`：训练/评估数据。
- `测试图`：Windows 测试视频/图片，已知 `D:\YOLO_ALPR_Project\测试图\14.mp4` 是重要测试视频。
- `汇报`、`report_render_work`、`build_alpr_demo_report.py`、`tools/build_alpr_stage_report.py`：汇报和报告生成相关。

### 旧脚本或待确认脚本

- `alpr_sahi_snapshot.py`、`alpr_sahi_snapshot2.py`：早期 snapshot/SAHI 思路。
- `main.py`、`api_with_tracking.py`、`cascade_stream.py`、`cascade_stream2.py`、`test_image.py`、`test_image2.py`：早期入口或测试脚本，当前是否仍在主线使用待确认。
- `代码截图.docx`、`各代码含义.docx`、`对话.docx`、`谷歌云盘模型含义.docx`：文档材料，具体最新性待确认。

## 关键路径和设备信息

Windows 项目根目录：

```text
D:\YOLO_ALPR_Project
```

Windows 重要测试视频：

```text
D:\YOLO_ALPR_Project\测试图\14.mp4
```

本地/板端常用目录：

```bash
/root/alpr_topk_rk3588
/root/deploy
/root/rk3588_alpr_roadtest_bundle_20260701
```

板端内置场地视频：

```bash
/root/deploy/144.mp4
```

远程 SC850SL 板常用 IP：

```text
192.168.8.88
```

用户本地 IMX585 板曾出现 IP：

```text
192.168.137.168
```

远程实时浏览器地址：

```text
http://192.168.8.88:8080/view.html
```

## 重要测试结果

### 本地 IMX585 板内置视频

- 输入：`/root/deploy/144.mp4`
- 帧数：1000 帧
- 速度：约 10 FPS
- 锁定：`冀JC5210`、`冀B6R9F9`
- run 目录：`/root/alpr_topk_rk3588/runs_video_selftest_codex/run_20260706_031136`

### 远程 SC850SL 板内置视频

- 输入：同一内置场地视频。
- 结果：用户截图显示和 IMX585 内置视频识别一样。
- 锁定：`冀JC5210`
- 结论：SC850SL 板端 ALPR 主流程、模型、OCR、投票、叠框、浏览器发布链路可用。

### `/dev/video33` RAW10 灰度

- 格式：`BG10` / raw10-gray
- 分辨率：3840x2160
- 结果：能出 RAW10，能转灰度图。
- 问题：灰度域和高位视角下 vehicle 模型不稳定，低阈值和分块后假阳性多。

### `/dev/video71` NV12

- 格式：4K `NV12`
- 证据包：`D:\YOLO_ALPR_Project\RK3588_dev\sc850_rkaiq_debug_20250626_142419.tar.gz`
- 结果：5 帧约 60 MB，约 30 FPS，rkaiq `/dev/media7` stream event success。
- 结论：这是 SC850SL 当前主测试输入。

## 当前未解决问题

- 实时城市道路画面中，车辆检测有时能框到汽车，有时漏检。
- 低阈值下会框到电动车、车轮、行人或非目标区域。
- 当前还没有确认在 `/dev/video71` 实时彩色输入下完整稳定输出真实车牌号并跟随车辆。
- `best_obb_finetuned_e20.pt` 转 RKNN 并与当前 `best_obb.rknn` A/B 尚未完成。
- 是否需要创建 `PR0JECT.md` 兼容用户最初拼写，仍待确认。

## 新对话第一步建议

1. 先读 `AGENTS.md` 和本文件。
2. 不要改 `alpr_topk_capture.py`。
3. 继续围绕 `rk3588_topk_capture_mipi_debug_sc850.py` 和 `/dev/video71` NV12 实时输入调。
4. 先让汽车框稳定：
   - 收窄机动车道 ROI。
   - 调高 `vehicle-conf`。
   - 排除右侧人行道/非机动车道。
   - 如果需要，增加车辆候选过滤。
5. 汽车框稳定后，再接 HyperLPR3 OCR，验证真实车牌号锁定和随车显示。
6. 每轮测试都保存 run 目录，并看 `run_summary.json`、预览图、rejected 样本和终端统计，不只看浏览器一帧。

## 不能随便改的限制

- 不要删除、覆盖或回滚用户已有工作。
- 不要把 `ocr-engine none` 或 `PLATE` 当成真实识别完成。
- 不要把 `/tmp/frame.jpg` 的旧帧当成实时运行证据。
- 不要继续把 `/dev/video44` 当成 SC850SL 主 ISP 输出。
- 不要在没有 A/B 的情况下把 deblur 接入 RK 实时主链路。
- 不要忽略 rejected 样本、summary、vote history 等诊断信息。
- 对 SC850SL 适配要改副本 `rk3588_topk_capture_mipi_debug_sc850.py`，不要污染 `rk3588_topk_capture_mipi_debug.py` 和 Windows 基准主线。

