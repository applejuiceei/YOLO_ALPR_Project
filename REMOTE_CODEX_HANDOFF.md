# 远程 Codex 接手交接说明

更新时间：2026-07-05

适用对象：即将在远程 Windows 电脑上安装并运行的新 Codex。

目标：让新 Codex 快速理解 YOLO_ALPR 项目的目标、当前结论、关键脚本、文件结构、已做尝试、不要重复踩的坑，以及下一步应该怎么继续。

## 1. 先给新 Codex 的话

请先阅读本文件，然后按以下顺序阅读项目根目录文档：

1. `AGENTS.md`
2. `PROJECT.md`
3. `STATUS.md`
4. `DECISIONS.md`
5. `HANDOFF.md`
6. `PROJECT_HANDOFF.md`
7. 只读当前任务相关脚本源码，不要一上来全局乱改。

本项目是长期项目，任何不确定信息必须标注“待确认”，不要自行补全。

重要规则：

- 默认用中文沟通。
- 不要直接修改 `rk3588_topk_capture_mipi_debug.py`，它是用户自有 IMX585 板上可工作的 MIPI 调试参考脚本。
- 远程 SC850SL 板子的适配工作放在副本 `rk3588_topk_capture_mipi_debug_sc850.py`。
- 不要把 `ocr-engine none`、`PLATE`、`mipi_plate_scan_only` 这类诊断模式当成最终结果。
- 最终目标是：真实车牌号显示在对应车辆上方，并跟随该车辆，直到 YOLO 或预测跟踪都无法继续框住它。
- 每完成重要工作，要同步更新 `PROJECT.md`、`STATUS.md`、`DECISIONS.md`、`HANDOFF.md`。
- 只有工作规则变化时才更新 `AGENTS.md`。

## 2. 应该传到远程 Windows 的文件

建议在远程 Windows 上保持同样根目录：

```text
D:\YOLO_ALPR_Project
```

### 2.1 必传文件

这些文件用于让新 Codex 理解规则、目标、状态和决策：

```text
D:\YOLO_ALPR_Project\AGENTS.md
D:\YOLO_ALPR_Project\PROJECT.md
D:\YOLO_ALPR_Project\STATUS.md
D:\YOLO_ALPR_Project\DECISIONS.md
D:\YOLO_ALPR_Project\HANDOFF.md
D:\YOLO_ALPR_Project\PROJECT_HANDOFF.md
D:\YOLO_ALPR_Project\REMOTE_CODEX_HANDOFF.md
```

这些文件是当前关键代码：

```text
D:\YOLO_ALPR_Project\rk3588_topk_capture_mipi_debug_sc850.py
D:\YOLO_ALPR_Project\rk3588_topk_capture_mipi_debug.py
D:\YOLO_ALPR_Project\rk3588_topk_capture.py
D:\YOLO_ALPR_Project\alpr_topk_capture.py
D:\YOLO_ALPR_Project\alpr_topk_capture_demo.py
D:\YOLO_ALPR_Project\mipi_current_frame_probe.py
D:\YOLO_ALPR_Project\rk3588_mipi_isp_probe.py
```

这些是离线部署包和操作说明：

```text
D:\YOLO_ALPR_Project\RK3588_dev\offline_bundle\README_ROAD_TEST.md
D:\YOLO_ALPR_Project\RK3588_dev\offline_bundle\ROAD_TEST_OPERATOR_GUIDE.md
D:\YOLO_ALPR_Project\RK3588_dev\offline_bundle\rk3588_alpr_roadtest_bundle_20260701.tar.gz
```

这些是模型/转换相关文件，按空间情况选择传：

```text
D:\YOLO_ALPR_Project\best_obb.pt
D:\YOLO_ALPR_Project\best_obb_finetuned_e20.pt
D:\YOLO_ALPR_Project\best_obb_finetuned_e8.pt
D:\YOLO_ALPR_Project\RK3588_dev\vehicle.rknn
D:\YOLO_ALPR_Project\RK3588_dev\plate_obb.rknn
D:\YOLO_ALPR_Project\RK3588_dev\plate_rec.rknn
D:\YOLO_ALPR_Project\RK3588_dev\dict.txt
```

### 2.2 可选但有帮助的目录

这些目录含历史测试结果、预览图和 run summary，新 Codex 需要追溯时有用：

```text
D:\YOLO_ALPR_Project\RK3588_dev\
D:\YOLO_ALPR_Project\captures_topk\
D:\YOLO_ALPR_Project\captures_topk_ab\
D:\YOLO_ALPR_Project\captures_deblur_ab_full\
D:\YOLO_ALPR_Project\captures_deblur_bg_vote_full\
D:\YOLO_ALPR_Project\测试图\
```

如果空间有限，至少传：

```text
D:\YOLO_ALPR_Project\RK3588_dev\mipi_current_probe_live\
D:\YOLO_ALPR_Project\RK3588_dev\run_20260626_074232\
D:\YOLO_ALPR_Project\测试图\14.mp4
```

### 2.3 不建议优先传的大文件

这些文件很大，除非远程 Codex 要做 RKNN 工具链或源码级编译，否则暂时不用传：

```text
D:\YOLO_ALPR_Project\rknn-toolkit2-master.zip
D:\YOLO_ALPR_Project\rknpu2-master.zip
D:\YOLO_ALPR_Project\RealESRGAN_x4plus.pth
```

## 3. 远程板和场景信息

远程 Windows 电脑通过向日葵控制，连接一块 RK3588 板。

当前远程板信息：

```text
IP: 192.168.8.88
hostname: linaro-alip
Linux: 5.10.209 aarch64
摄像头模组: SC850SL / SC850SL
```

用户自有板信息：

```text
同款 RK3588 板
摄像头模组: IMX585
rk3588_topk_capture_mipi_debug.py 在用户自有 IMX585 板上摄像头可正常识别
```

关键区别：

- 用户自有板是 IMX585。
- 远程板是 SC850SL。
- 所以不能把 IMX585 经验直接套到远程板。
- SC850SL 适配必须使用副本 `rk3588_topk_capture_mipi_debug_sc850.py`。

## 4. 当前项目最终目标

最终不是只识别一张车牌，也不是只框出 `PLATE`。

最终目标是道路固定摄像头 ALPR：

1. 从视频流或 MIPI 摄像头画面中检测车辆。
2. 在车辆区域内检测车牌 OBB。
3. 拉正车牌 crop。
4. 用 OCR 识别真实车牌号。
5. 对同一辆车多帧 OCR 结果投票。
6. 投票锁定后，不再重复对该 track 做 OBB/OCR。
7. 继续跟踪车辆，并把真实车牌号显示在该车辆上方。
8. 车辆消失后或 YOLO/预测都无法继续框住后，停止跟随。

一句话：

```text
锁定前识别，锁定后不再识别，只跟踪车辆并持续显示已锁定真实车牌号。
```

## 5. 当前已实现的能力

### 5.1 Windows 主线

主脚本：

```text
D:\YOLO_ALPR_Project\alpr_topk_capture.py
```

作用：

- Windows 端行为基准。
- 使用视频文件输入。
- 车辆检测。
- 车牌 OBB。
- Top-K 候选保存。
- HyperLPR3 OCR。
- OCR 投票与锁定。
- 输出 summary、candidate crops、rejected 样本、投票历史。

注意：

- 这个脚本是 Windows 基准，不要随意改。
- 实验优先用 `alpr_topk_capture_demo.py`。

### 5.2 RK3588 视频文件链路

主脚本：

```text
D:\YOLO_ALPR_Project\rk3588_topk_capture.py
```

板端目录：

```bash
/root/alpr_topk_rk3588
/root/deploy
```

已确认：

- RKNN vehicle 模型可加载运行。
- RKNN plate OBB 模型可加载运行。
- HyperLPR3 可导入运行。
- `/root/deploy/144.mp4` 视频自测已跑通。
- 曾锁定 `冀JC5210`。

### 5.3 离线部署包

Windows 端包位置：

```text
D:\YOLO_ALPR_Project\RK3588_dev\offline_bundle\rk3588_alpr_roadtest_bundle_20260701.tar.gz
```

包内包含：

- `/root/alpr_topk_rk3588/rk3588_topk_capture.py`
- `/root/alpr_topk_rk3588/rk3588_topk_capture_mipi_debug.py`
- `/root/alpr_topk_rk3588/mipi_current_frame_probe.py`
- `/root/alpr_topk_rk3588/run_mipi_road.sh`
- `/root/deploy/stream.py`
- `/root/deploy/run_stream.sh`
- `/root/deploy/vehicle.rknn`
- `/root/deploy/best_obb.rknn`
- `/root/deploy/144.mp4`
- Python 依赖快照和检查/恢复脚本。

注意：

- 这个包是在用户自有 IMX585 板上测试后打包的。
- 后来新增的 SC850SL 适配脚本 `rk3588_topk_capture_mipi_debug_sc850.py` 不在这个包内，需要单独传。

### 5.4 浏览器实时预览

包里有流媒体服务：

```bash
/root/deploy/run_stream.sh
/root/deploy/stream.py
```

作用：

- 只负责读取 `/tmp/frame.jpg` 并通过 HTTP/MJPEG 显示。
- 不负责采集。
- 不负责识别。

浏览器地址：

```text
http://192.168.8.88:8080
```

重要提醒：

- `/tmp/frame.jpg` 可能是旧帧。
- 如果左上角 `frame:` 数字不变，或文件修改时间/MD5 不变，说明采集程序已经停了。
- 不能拿旧 `/tmp/frame.jpg` 判断曝光和识别效果。

## 6. 远程 SC850SL 摄像头链路结论

### 6.1 错误路径：IMX585 / `/dev/video53`

最早测试了 `/dev/video53`，显示是 IMX585 路径：

```text
Driver name: rkisp_v6
Card type: rkisp_mainpath
Bus info: platform:rkisp0-vir2
Format: 3840x2160 UYVY/NV12
```

但取流失败：

```text
imx585 2-0010: start stream failed while write regs
rkisp0-vir2: rkisp_stream_stop id:0 timeout
```

结论：

- `/dev/video53` 不是远程 SC850SL 当前正确路径。
- 不要继续围绕 `/dev/video53` 调试 SC850SL。

### 6.2 正确前级路径：SC850SL RAW10 / `/dev/video33`

确认远程板设备树和驱动中存在：

```text
sc850sl-1@30
sc850sl-2@30
sc850sl-4@30
/sys/bus/i2c/drivers/sc850sl
/sys/bus/i2c/drivers/sc850sl_2L
/etc/iqfiles/sc850sl_GC_12MM.json
/etc/iqfiles/sc850sl_2L_GC_12MM.json
```

确认 `/dev/video33` 可输出：

```text
SC850SL BG10 RAW10
3840x2160
Pixel Format: BG10
bytesperline: 4864
5 frames about 51 MB
about 30 FPS at V4L2 raw capture level
```

这说明：

- SC850SL 传感器可用。
- 驱动可用。
- MIPI/CSI/DPHY/CIF 前级可用。
- 不是硬件完全不通。

### 6.3 未修通路径：RKISP `/dev/video44`

尝试 `/dev/video44` 输出 UYVY/NV12：

```text
VIDIOC_STREAMON returned -1 (Operation not permitted)
rkisp0-vir0: check rkisp_mainpath link or isp input
```

结论：

- RKISP mainpath 输出链路未通。
- 当前短期策略：先用 `/dev/video33` RAW10 灰度跑通流程。
- 长期仍需修 `/dev/video44` 或 RKISP UYVY/NV12 输出链路。

## 7. SC850SL 灰度 RAW10 当前处理方式

当前适配脚本：

```text
D:\YOLO_ALPR_Project\rk3588_topk_capture_mipi_debug_sc850.py
```

新增能力：

- `--mipi-fourcc BG10`
- `--mipi-color-mode raw10-gray`
- `--raw10-stride 4864`
- RAW10 unpack
- 灰度转 BGR 以复用现有 RKNN/OBB/OCR 管线
- `--detect-roi`
- `--draw-detect-roi`
- `--detect-roi-tiles`
- `--detect-roi-overlap`
- `--vehicle-source rknn|motion|hybrid`

RAW10 说明：

- SC850SL 输出 BG10 RAW10。
- 彩色 demosaic 曾试过 BG/GB/RG/GR，颜色都不可靠。
- 当前最稳定的是灰度。
- 灰度图可以先跑识别流程，但对 vehicle/plate 模型存在明显域偏移。

## 8. 曝光结论

### 8.1 夜间

夜间曾用：

```bash
v4l2-ctl -d /dev/v4l-subdev7 --set-ctrl=analogue_gain=64
v4l2-ctl -d /dev/v4l-subdev7 --set-ctrl=exposure=1200
```

结果：

- 夜间画面可见道路和车辆。
- 灰度图能看出结构。

### 8.2 白天

白天沿用夜间曝光会严重过曝。

已确认：

```bash
exposure=380
analogue_gain=64
```

白天画面已恢复道路、车身和车道线层次。

仍存在：

- 右侧和白色高亮区域有溢出。
- 更优日间曝光可在 `320/350/380` 附近微调，待确认。

重要坑：

- 第一次曝光扫描复制了同一张旧 `/tmp/frame.jpg`，左上角均显示 `frame:500`。
- 曝光扫描必须保证采集程序正在运行。
- 判断是否刷新：

```bash
ls -lh --time-style=full-iso /tmp/frame.jpg
md5sum /tmp/frame.jpg
sleep 3
ls -lh --time-style=full-iso /tmp/frame.jpg
md5sum /tmp/frame.jpg
```

## 9. 已做过的主要尝试

### 9.1 MIPI 设备枚举

做过：

- `ls -l /dev/video* /dev/media*`
- `media-ctl -p`
- `v4l2-ctl -d /dev/video53 --all`
- 遍历 `/dev/media*` 找 SC850SL/IMX585 链路。
- 查 `/proc/device-tree`。
- 查 `/sys/bus/i2c/devices`。
- 查 `/sys/bus/i2c/drivers`。

结论：

- 远程板同时有 IMX585 和 SC850SL 相关节点。
- 真正接入的是 SC850SL。
- `/dev/video33` 是当前可用 RAW10 节点。

### 9.2 `/dev/video53` 取流

尝试：

```bash
timeout 8 v4l2-ctl -d /dev/video53 \
  --set-fmt-video=width=3840,height=2160,pixelformat=UYVY \
  --stream-mmap=4 \
  --stream-count=5 \
  --stream-to=/tmp/video53_test.raw \
  --verbose
```

也试过 1280x720 NV12。

结果：

- raw 文件 0 字节。
- dmesg 显示 IMX585 写寄存器失败。

结论：

- 远程 SC850SL 不走这条链路。

### 9.3 `/dev/video44` ISP 输出

尝试：

```bash
v4l2-ctl -d /dev/video44 ...
```

结果：

```text
VIDIOC_STREAMON returned -1 (Operation not permitted)
rkisp0-vir0: check rkisp_mainpath link or isp input
```

结论：

- RKISP 输出链路未通，待后续单独修。

### 9.4 `/dev/video33` SC850SL RAW10

尝试：

```bash
for v in /dev/video33 /dev/video34 /dev/video35 /dev/video36; do
  timeout 8 v4l2-ctl -d $v \
    --set-fmt-video=width=3840,height=2160,pixelformat=BG10 \
    --stream-mmap=4 \
    --stream-count=5 \
    --stream-to=/tmp/$(basename $v)_sc850_bg10.raw \
    --verbose
done
```

结果：

- `/dev/video33` 成功出 RAW10。
- 可以生成灰度预览。

### 9.5 彩色 demosaic

尝试：

- BG
- GB
- RG
- GR

结果：

- 都出现明显伪彩/颜色异常。
- 灰度更稳定。

结论：

- 先用灰度跑通流程。
- 长期修 ISP 输出后再回到 UYVY/NV12 彩色或正常灰度。

### 9.6 灰度整图 vehicle 测试

命令中使用：

```bash
--mipi-fourcc BG10
--mipi-color-mode raw10-gray
--raw10-stride 4864
```

结果：

- 整幅 3840x2160 缩放到 640 后车辆太小。
- `tracks=0`

结论：

- 需要检测前 ROI 裁剪。

### 9.7 单块 `--detect-roi`

结果：

- 1000 帧仍为：

```text
tracks=0
new_hits=0
total_hits=0
```

结论：

- 单块 ROI 仍不足。

### 9.8 分块 ROI

增加：

```bash
--detect-roi-tiles 1 3
--detect-roi-overlap 0.20
```

结果：

```text
vehicle_detections_raw=79
vehicle_detections_nms=79
vehicles_ready=79
plate_attempts=79
```

但画面观察：

- 多数框在广告牌/灯箱/路边结构上。
- 不是车辆。
- `PLATE` 锁定是低阈值诊断模式假阳性。

结论：

- 分块让模型有输出，但主要是假阳性。
- 不能视为有效车辆识别。

### 9.9 日间曝光后真实车辆仍 `veh:0`

白天 `exposure=380` 后，画面中明显有运动真车。

但当前 RKNN vehicle 仍：

```text
veh:0
```

结论：

- 当前 `vehicle.rknn` 对 SC850SL 灰度高位视角不可靠。
- 继续调 YOLO 阈值意义不大。
- 固定机位应先尝试运动目标 fallback。

### 9.10 新增 `--vehicle-source motion|hybrid`

已在 `rk3588_topk_capture_mipi_debug_sc850.py` 增加：

```text
--vehicle-source rknn
--vehicle-source motion
--vehicle-source hybrid
```

作用：

- `rknn`: 原 vehicle RKNN 检测。
- `motion`: 背景差分生成运动目标框，绕过 vehicle RKNN。
- `hybrid`: 合并 RKNN 和 motion 候选。

目的：

- 固定机位先让运动真车能被框住。
- 过滤静态广告牌/灯箱。
- 真实车辆框稳定后，再接 plate OBB/OCR。

语法检查已通过：

```powershell
python -m py_compile .\rk3588_topk_capture_mipi_debug_sc850.py
```

## 10. 当前推荐下一步

### 10.1 先重新传 SC850SL 副本

在远程 Windows PowerShell：

```powershell
scp D:\YOLO_ALPR_Project\rk3588_topk_capture_mipi_debug_sc850.py root@192.168.8.88:/root/alpr_topk_rk3588/
```

### 10.2 固定日间曝光

在板子：

```bash
v4l2-ctl -d /dev/v4l-subdev7 --set-ctrl=analogue_gain=64
v4l2-ctl -d /dev/v4l-subdev7 --set-ctrl=exposure=380
```

### 10.3 开浏览器流服务

一个终端：

```bash
cd /root/deploy
./run_stream.sh
```

浏览器：

```text
http://192.168.8.88:8080
```

### 10.4 跑 motion 车辆框测试

另一个终端：

```bash
cd /root/alpr_topk_rk3588

python3 rk3588_topk_capture_mipi_debug_sc850.py \
  --video mipi \
  --camera-device /dev/video33 \
  --camera-width 3840 \
  --camera-height 2160 \
  --mipi-backend v4l2ctl \
  --mipi-fourcc BG10 \
  --mipi-color-mode raw10-gray \
  --raw10-stride 4864 \
  --vehicle-source motion \
  --vehicle-model /root/deploy/vehicle.rknn \
  --plate-model /root/deploy/best_obb.rknn \
  --ocr-engine none \
  --output /root/alpr_topk_rk3588/runs_sc850_motion_vehicle \
  --detect-roi 0.05 0.58 0.95 0.95 \
  --draw-detect-roi \
  --process-roi 0.05 0.58 0.95 0.95 \
  --draw-process-roi \
  --vehicle-detect-interval 1 \
  --vehicle-conf 0.10 \
  --motion-min-width 45 \
  --motion-min-height 30 \
  --motion-min-area 2500 \
  --motion-dilate 3 \
  --min-process-vehicle-conf 1.10 \
  --publish-frame /tmp/frame.jpg \
  --publish-interval 1 \
  --progress-interval 20 \
  --max-frames 0
```

观察：

- 前几十帧背景模型学习，可能没有框。
- 有车经过时，看蓝框是否跟随运动目标。
- 先不要关心车牌，只看运动真车是否被框住。

如果框太碎：

```bash
--motion-min-area 5000
--motion-dilate 4
```

如果还是没框：

```bash
--motion-threshold 120
--motion-min-area 1200
```

### 10.5 motion 框稳定后，再接 plate

只有当运动真车框稳定后，才继续：

- 恢复合理 `--min-process-vehicle-conf`
- 让 plate OBB 跑在 motion vehicle crop 内。
- 再接 HyperLPR3 OCR。
- 再做投票锁定和随车显示。

## 11. 当前文件结构说明

### 11.1 根目录核心文档

```text
AGENTS.md
```

AI 员工手册。记录沟通方式、工作流程、长期规则和红线。只有规则变化时更新。

```text
PROJECT.md
```

项目目标、当前需求、验收标准、不能随便改的内容。

```text
STATUS.md
```

已完成、正在进行、当前卡点、下一步、待确认。

```text
DECISIONS.md
```

重要决定及原因。例如为什么先用 RAW10 灰度、为什么新增分块 ROI、为什么新增 motion fallback。

```text
HANDOFF.md
```

新 AI 接手阅读顺序、当前状态、第一步、常用路径和注意事项。

```text
PROJECT_HANDOFF.md
```

更早、更长的历史交接背景。除非用户要求，不作为日常状态文件改写。

```text
REMOTE_CODEX_HANDOFF.md
```

本文件。专门给远程电脑新 Codex 接手使用。

### 11.2 Windows 主线和实验脚本

```text
alpr_topk_capture.py
```

Windows 基准主线。不要随意改。

```text
alpr_topk_capture_demo.py
```

Windows 实验副本，用于 deblur、A/B、弹窗显示等尝试。

```text
ocr_compare_topk.py
```

OCR 对比工具。

```text
test_deblur_hyperlpr3.py
test_deblur_image.py
prepare_deblur_dataset.py
prepare_deblur_dataset_v2.py
train_deblur_colab.py
```

deblur 相关实验/训练/评估文件。当前 deblur 不进入 RK 实时主链路。

### 11.3 RK / MIPI 脚本

```text
rk3588_topk_capture.py
```

RK3588 板端主脚本。已支持视频文件、MIPI、RKNN vehicle/plate、HyperLPR3、Top-K、投票、发布 `/tmp/frame.jpg` 等。

```text
rk3588_topk_capture_mipi_debug.py
```

更新的 MIPI 摄像头调试参考脚本。用户自有 IMX585 板可用。不要直接改。

```text
rk3588_topk_capture_mipi_debug_sc850.py
```

SC850SL 远程板适配副本。当前最重要脚本。

已有新增能力：

- SC850SL BG10 RAW10 灰度解析。
- `--raw10-stride 4864`
- `--detect-roi`
- `--detect-roi-tiles`
- `--vehicle-source motion|hybrid`
- 实时发布 `/tmp/frame.jpg`

```text
mipi_current_frame_probe.py
```

读取当前 `/tmp/frame.jpg` 并做离线探针的脚本。

```text
rk3588_mipi_isp_probe.py
```

MIPI/ISP 探测脚本。

### 11.4 RK3588_dev 目录

```text
RK3588_dev\offline_bundle\
```

离线部署包和说明。

```text
RK3588_dev\vehicle.rknn
RK3588_dev\plate_obb.rknn
RK3588_dev\plate_rec.rknn
RK3588_dev\dict.txt
```

RK 模型和 OCR 字典。

```text
RK3588_dev\mipi_current_probe_live\
```

历史 MIPI 当前帧探针结果。

```text
RK3588_dev\run_20260626_074232\
```

一个较完整的 RK 输出 run，包括多个 track、plate_rank、vehicle_rank、summary。

```text
RK3588_dev\rk_*\
```

一系列历史 RK A/B 测试输出目录，例如 tracker、reassociate、windows_equiv、adaptive 等。

### 11.5 模型文件

```text
best_obb.pt
best_obb_finetuned_e8.pt
best_obb_finetuned_e20.pt
```

车牌 OBB PyTorch 模型。`best_obb_finetuned_e20.pt` 待后续转 RKNN 并做 A/B。

```text
yolo11n.pt
yolov8n.pt
```

YOLO 基础模型文件。

### 11.6 测试数据/输出

```text
测试图\14.mp4
```

Windows 测试视频。

```text
captures_topk*
captures_deblur*
```

Windows 端 Top-K、deblur、OCR A/B 输出。

## 12. 常见误判和不要重复踩的坑

1. 不要把 `/dev/video53` 当成 SC850SL 正确节点。
2. 不要把 `/dev/video44` 的失败归因于 ALPR 主代码，它是 RKISP 链路问题。
3. 不要拿旧 `/tmp/frame.jpg` 判断曝光或识别，先看 `frame:` 是否变化。
4. 不要把低阈值 `PLATE` 锁定当成有效识别。
5. 不要直接改 `rk3588_topk_capture_mipi_debug.py`。
6. 不要在 vehicle RKNN 明显不适配时继续无限调阈值。
7. 不要过早调 OCR。当前核心卡点是“真车框不稳”。
8. 不要把广告牌/灯箱框当作车辆框。
9. 不要在白天用夜间曝光 `1200`。
10. 不要忘了远程板是 SC850SL，不是用户自有板的 IMX585。

## 13. 给远程 Codex 的第一条消息建议

可以把下面这段直接发给远程 Codex：

```text
你正在接手一个 RK3588 中文车牌识别项目。请先阅读 D:\YOLO_ALPR_Project\REMOTE_CODEX_HANDOFF.md，然后按顺序阅读 AGENTS.md、PROJECT.md、STATUS.md、DECISIONS.md、HANDOFF.md、PROJECT_HANDOFF.md。

请注意：
1. 默认用中文。
2. 不确定的信息标“待确认”，不要脑补。
3. 不要直接修改 rk3588_topk_capture_mipi_debug.py，它是用户自有 IMX585 板上的可用参考。
4. 远程板摄像头是 SC850SL，适配脚本是 rk3588_topk_capture_mipi_debug_sc850.py。
5. 当前 /dev/video33 的 SC850SL BG10 RAW10 灰度出图已通；/dev/video44 RKISP 输出未通。
6. 白天曝光候选值是 exposure=380、analogue_gain=64。
7. 当前 RKNN vehicle 在 SC850SL 灰度高位视角下框不住运动真车，因此最新方向是测试 --vehicle-source motion 背景差分固定机位 fallback。
8. 最终目标不是 PLATE 诊断标签，而是真实车牌号显示在对应车辆上方并跟随车辆。

你的第一步：确认 rk3588_topk_capture_mipi_debug_sc850.py 已在 /root/alpr_topk_rk3588/，然后在板子 192.168.8.88 上用 REMOTE_CODEX_HANDOFF.md 第 10 节的 motion 命令测试运动真车是否能被稳定框住。不要先调 OCR。
```

## 14. 当前最短行动清单

1. 远程 Windows 安装 Codex。
2. 把本文件和核心文档/脚本复制到 `D:\YOLO_ALPR_Project`。
3. 新 Codex 先读 `REMOTE_CODEX_HANDOFF.md`。
4. 重新传 `rk3588_topk_capture_mipi_debug_sc850.py` 到板子。
5. 板子设置：

```bash
v4l2-ctl -d /dev/v4l-subdev7 --set-ctrl=analogue_gain=64
v4l2-ctl -d /dev/v4l-subdev7 --set-ctrl=exposure=380
```

6. 启动 `/root/deploy/run_stream.sh`。
7. 跑 `--vehicle-source motion` 测试。
8. 只看运动真车是否被框住。
9. 框住后再接 plate OBB。
10. plate 稳定后再接 HyperLPR3 OCR 和随车显示。

