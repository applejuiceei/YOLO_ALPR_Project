# 新对话交接文档：RK3588 + SC850SL 实时道路车辆与车牌识别

更新时间：2026-07-17（Asia/Shanghai）  
项目根目录：`D:\YOLO_ALPR_Project`  
远程板地址：`192.168.8.88`，用户 `root`  
远程板工作目录：`/root/alpr_topk_rk3588`  
远程模型包：`/root/rk3588_alpr_roadtest_bundle_20260701`

> 本文是截至 2026-07-17 的最新单文档交接，优先级高于 `NEW_CHAT_HANDOFF_20260710.md`、`PROJECT.md`、`STATUS.md`、`DECISIONS.md` 和 `HANDOFF.md` 中与 SC850SL 当前状态冲突的旧结论。旧文档仍有历史价值，但其中“sensor 未上线、`/dev/video71` 不能出帧”只代表过去某一阶段，不能再当成当前事实。

---

## 1. 新对话必须先读什么

### 1.1 必读顺序

新 AI 接手后，先完整阅读，不要一上来改代码或跑实验：

1. `AGENTS.md`
2. `NEW_CHAT_HANDOFF_20260717.md`（本文，当前状态以本文为准）
3. `rk3588_topk_capture_mipi_debug_sc850.py`
4. `RK3588_dev/run_sc850_video71_alpr_live.sh`
5. `RK3588_dev/sc850_video71_vehicle_probe_collect.sh`

### 1.2 需要了解历史时再读

6. `NEW_CHAT_HANDOFF_20260710.md`
7. `PROJECT.md`
8. `STATUS.md`
9. `DECISIONS.md`
10. `HANDOFF.md`
11. `PR0JECT_0708.md`
12. `STATUS_0708.md`
13. `DECISIONS_0708.md`
14. `HANDOFF_0708.md`
15. `NEW_CHAT_HANDOFF_20260708.md`

旧文档的用途是还原早期实验、文件来源和决策演进。遇到冲突时采用以下优先级：

1. 用户在新对话中的最新反馈；
2. 本文；
3. 当前工作区脚本和回传原始证据；
4. `NEW_CHAT_HANDOFF_20260710.md`；
5. 其余历史文档。

### 1.3 接手后的沟通要求

- 默认中文。
- 先区分“事实、推断、待确认、建议”，不能把推断写成实验事实。
- 当前用户不要求每轮都更新全部 Markdown 记忆文件；只有用户明确要求或发生重要交接时才更新。
- 当前主线是 SC850SL 真实道路识别和实时性，不要重新跑偏去单独调 Windows OCR。
- 未经确认不要自动执行会改变板端状态的命令，尤其是杀进程、改权限、重启服务、重启板子。
- 不要停止 `rkaiq_3A_server`，不要结束用户当前正在使用的 SSH/MobaXterm 会话。

---

## 2. 项目最终目标

在远程电脑连接的 RK3588 板上，使用 SC850SL MIPI 摄像头的真实道路画面，通过 `/dev/video71` 读取 3840x2160 NV12 视频，在板端完成：

1. 实时读取 SC850SL 4K 道路画面；
2. 在有效车道 ROI 内检测机动车；
3. 在车辆区域内检测车牌 OBB；
4. 使用 HyperLPR3 识别中国车牌；
5. 通过多帧一致性和严格车牌格式过滤降低误识别；
6. 在浏览器中查看带车辆框、车牌框和识别结果的实时预览；
7. 保存 Top-K、rejected、vote history、锁定证据和运行统计，支持人工核查；
8. 在保证识别质量的前提下提高处理 FPS，使正常行驶车辆在进入 ROI 后尽早被识别，而不是只有红灯减速时才容易识别。

当前优先级已经调整为：

1. 识别率和有效命中率；
2. 稳定连续运行；
3. 处理速度和预览响应；
4. 长时间跟踪和运动预测。

用户明确接受弱化甚至放弃复杂追踪。当前方案只保留识别所需的极短状态和文字去重，不再把“车牌号长期跟着车走”作为首要验收指标。

---

## 3. 项目环境和实际操作关系

### 3.1 三层环境

1. **本地 Windows 开发机**
   - 项目目录：`D:\YOLO_ALPR_Project`
   - 存放代码、文档、模型、回传压缩包、分析结果和汇报材料。

2. **远程 Windows 电脑**
   - 用户通过向日葵远程操作。
   - 远程电脑上使用 MobaXterm/SSH 连接 RK3588 板。
   - 中转目录曾使用 `E:\YOLO_ALPR`。

3. **远程 RK3588 板**
   - IP：`192.168.8.88`
   - 用户：`root`
   - 项目目录：`/root/alpr_topk_rk3588`
   - 模型包：`/root/rk3588_alpr_roadtest_bundle_20260701`
   - 摄像头节点：`/dev/video71`
   - 浏览器预览：`http://192.168.8.88:8080`
   - 预览图片：`/tmp/frame.jpg`

### 3.2 数据回传路径

通常是：

`远程 RK3588 板 -> 远程 Windows E:\YOLO_ALPR -> 本地 D:\YOLO_ALPR_Project\RK3588_dev`

压缩包文件名中的 `202506xx` 不等于真实公历时间。板端系统时间曾长期不正确，因此判断先后顺序要同时参考对话时间、文件修改时间、日志内容和包名，不能只看包名日期。

---

## 4. 当前状态总览

### 4.1 已确认事实

1. Windows 基准主流程已经跑通。
2. 本地 RK3588 + IMX585 跑内置视频已经跑通。
3. 远程 SC850SL 板跑同一内置视频也已跑通，证明板端 RKNN 模型、HyperLPR3、Top-K 和识别主流程可用。
4. SC850SL 曾经历 sensor/I2C 未上线阶段，但后来已经恢复。
5. `/dev/video71` 已确认是 SC850SL 对应的 `rkisp1-vir1 mainpath`，能输出 3840x2160 NV12。
6. 独占 `/dev/video71` 时，`v4l2-ctl` 已成功连续抓取 30 帧，约 30 FPS，每帧 12,441,600 字节，退出码 0。
7. 真实道路画面 ALPR 已经识别并保存多批锁定车牌证据，不是只对手机图片有效。
8. 原始实时识别长期运行约 2.35-2.46 FPS；balanced 配置短测稳定处理速度约 4.17 FPS，提升约 70%。
9. 用户观察到红灯、车辆减速时识别率明显更高；高速车辆更容易漏识别。
10. 当前最近一次“浏览器画面卡住”不是已证明的 sensor 掉线，而是 `/opt/MultiSensing/bin/multisense` 抢占 `/dev/video71`，改变格式并导致 ALPR 的 `v4l2-ctl` 子进程退出。
11. `rkaiq_3A_server` 打开多个 video/subdev 节点是 ISP 正常工作的一部分，不应当停止。

### 4.2 当前最关键卡点

当前第一卡点是 **`multisense` 与 ALPR 对 `/dev/video71` 的独占冲突**：

- `fuser -v /dev/video71` 多次看到 `multisense`；
- `lsof` 看到 `/opt/MultiSensing/bin/multisense` 同时打开 `/dev/video71`；
- 它运行时，`v4l2-ctl` 报 `VIDIOC_S_FMT failed: Device or resource busy`，退出 255；
- 它还曾把节点当前格式改为 1920x1080 `NM12`；
- ALPR 正常跑到约 frame 208 后捕获流结束，浏览器继续显示最后一张 `/tmp/frame.jpg`，看起来像“程序还在但画面卡死”。

当前第二卡点是 **处理速度仍不足以覆盖高速车辆**：

- 摄像头本身能 30 FPS；
- balanced ALPR 约 4.17 FPS，意味着每秒只处理约 4 张，而不是全部 30 张；
- 还需要两个严格一致 OCR 事件才能锁定；
- 高速车辆在有效 ROI 内可用的清晰帧少，运动模糊会进一步降低 OBB/OCR 成功率。

### 4.3 当前待确认

1. 是否已经成功执行过“临时移除 `/opt/MultiSensing/bin/multisense` 执行权限”的方案，当前权限是多少。
2. `multisense` 的真正启动来源。已确认它不是已加载的 systemd unit；一次已捕获实例 PPID 为 1、cgroup 为 `session-165.scope`，像是某个 root 登录会话启动并 daemonize，但具体是谁/哪个程序拉起仍待确认。
3. 当前登录会话编号是否仍为 154。历史截图显示当前 SSH 是 session 154；绝不能机械执行 `loginctl terminate-session 154`。
4. SC850SL 当前曝光、增益、自动曝光模式的确切控制项和单位。
5. balanced 配置能否在排除 `multisense` 后稳定跑满 1000 帧以上。
6. 当前真实道路识别的严格定量准确率。现有证据可人工核查，但尚无完整人工标注 ground truth，因此不能宣称“准确率达到某百分比”。

### 4.4 当前一句话结论

SC850SL sensor、ISP 和 `/dev/video71` 已经能正常输出 4K NV12，真实道路 ALPR 也已经出过多批有效锁定结果；当前先解决 `multisense` 抢占导致的卡流，再在稳定 1000 帧测试上继续优化高速车辆识别率和 4.17 FPS 的性能瓶颈。

---

## 5. 已经实现了什么

### 5.1 Windows 基准

- 车辆检测、车牌 OBB、HyperLPR3、Top-K 和多帧投票主流程已跑通。
- `alpr_topk_capture.py` 是基准主线，不能为了板端问题随意修改。
- Windows 新实验优先用 `alpr_topk_capture_demo.py`。

### 5.2 RK3588 板端内置视频

- 车辆和车牌模型已转为 RKNN 并在 RK3588 NPU 上运行。
- HyperLPR3 在板端可用。
- 内置视频至少跑过 1000 帧，识别锁定结果与 Windows 基准大体一致。
- 远程 SC850SL 板跑内置视频也成功，因此不能把真实摄像头故障误归因到 OCR 或 RKNN 主链。

### 5.3 SC850SL MIPI 实时输入

当前 Python 主脚本已经支持：

- OpenCV 和 `v4l2-ctl` 两种 MIPI 后端；当前 SC850SL 使用 `v4l2ctl`。
- NV12、UYVY、RAW10 灰度等输入解码。
- 4K 3840x2160 NV12。
- detect ROI 和 process ROI。
- ROI 切片车辆检测。
- RKNN 车辆检测和 RKNN 车牌 OBB。
- HyperLPR3 或 RKNN OCR，可用 `none` 做诊断。
- 中国车牌严格格式过滤和部分乱码修复。
- 多帧 exact-text 投票与 adaptive lock。
- Top-K、rejected candidate、vote history、run summary。
- 锁定证据目录和 `lock.json`。
- 同一车牌短窗口重复锁定事件去重。
- 浏览器 JPEG 原子更新。
- 车辆 RKNN、车牌 RKNN、HyperLPR3、预览发布的分项耗时统计。

### 5.4 当前显示和框的含义

- 品红色大框：`DETECT ROI`。
- 浅蓝/橙色大框：`PROCESS ROI`，取决于 BGR 显示颜色。
- 蓝色车辆框：当前检测到但未锁定的车辆。
- 绿色车辆框：当前真实检测帧中已经锁定车牌的车辆。
- 橙色车辆框：预测框。当前启动脚本把 locked/unlocked prediction 都设为 0，实际主线已基本关闭预测。
- 黄色多边形：车牌 OBB，不是车辆运动预测。
- `LOCK <车牌>`：通过当前锁定条件后的车牌文字。

### 5.5 当前优化取向

用户认为早期画面框太乱、远车和电动车也被框、黄色预测效果不好、FPS 太低。已经采取：

- ROI 改为左侧机动车道为主，右侧建筑、停车区和非机动车道尽量排除；
- 车辆进入锁定流程必须达到最小尺寸和面积；
- `track-max-age=2`，预测帧数设为 0；
- 关闭 locked reassociation；
- 保留短期 track state 只为凑齐识别投票；
- 增加车牌文字事件去重，避免同一车牌因 track ID 抖动重复上报；
- balanced 配置将车辆 ROI tile 从 1x2 改为 1x1；
- 预览从每处理帧发布 1920px/q75 改为每 2 帧发布 1280px/q60；
- 保留原始 4K 车牌 crop 和严格锁定条件，不用牺牲 OCR 阈值换表面命中数。

---

## 6. 当前主流程

```text
/dev/video71 (3840x2160 NV12, 30 FPS)
        |
        v
v4l2-ctl mmap 子进程 -> stdout 原始帧
        |
        v
NV12 -> BGR
        |
        v
DETECT ROI + 车辆 RKNN
        |
        v
车辆尺寸/面积/ROI 门控
        |
        v
车辆 crop -> 车牌 OBB RKNN
        |
        v
透视矫正车牌 crop -> HyperLPR3
        |
        v
严格车牌格式 + OCR 置信度 + 两帧 exact-text 一致
        |
        +--> Top-K / rejected / vote history / lock evidence
        |
        +--> /tmp/frame.jpg -> stream.py -> 浏览器 8080
```

摄像头 30 FPS 不等于识别 30 FPS。当前算法会逐帧同步执行车辆检测、车牌检测、OCR 和预览发布，balanced 短测约 4.17 FPS。

---

## 7. 当前关键脚本

### 7.1 `rk3588_topk_capture_mipi_debug_sc850.py`

本地路径：`D:\YOLO_ALPR_Project\rk3588_topk_capture_mipi_debug_sc850.py`  
远程路径：`/root/alpr_topk_rk3588/rk3588_topk_capture_mipi_debug_sc850.py`  
当前本地 SHA-256：`42DC2859ADCC2A3A47CECBD41C3EA9F59804402ACD4FAC6CEFAB6FDD0BC6CE9A`

作用：SC850SL 真实 MIPI 道路识别主程序。主体语言是 Python，不是 C++。内部调用 RKNNLite、OpenCV、NumPy 和 HyperLPR3。

重要类/模块：

- `RKNNRunner`：加载和调用 RKNN 模型。
- `V4L2CtlCapture`：启动 `v4l2-ctl` 子进程，通过 stdout 读取固定大小原始帧。
- `SimpleIoUTracker`：轻量 IoU track ID，仅保留短期识别状态。
- `LinearBoxKalman`：可选框预测；当前主启动配置基本关闭。
- `Candidate` / `RejectedCandidate`：保存 Top-K 和拒绝样本。
- `TrackState`：保存每个短期车辆状态、投票、锁定文字和车牌 anchor。

重要功能：

- NV12/UYVY/RAW10 解码；
- 车辆模型解码、NMS、ROI tile 合并；
- OBB 车牌解码与透视矫正；
- HyperLPR3/RKNN OCR；
- 严格中国车牌格式；
- exact vote/adaptive lock；
- lock evidence、Top-K、summary；
- 浏览器预览；
- 分项耗时统计；
- 相同车牌 60 processed frames 内事件去重。

当前已知代码缺口：

1. `V4L2CtlCapture` 把 `v4l2-ctl` stderr 重定向到 `DEVNULL`，出错时看不到原始原因。
2. `cap.read()` 返回 false 时主循环直接 `break`，没有设置 `camera_read_failed` 一类明确 `stop_reason`。
3. 没有读取 `v4l2-ctl` return code、最后 stderr、节点 owner 和当前格式写入 run summary。
4. 没有捕获超时/看门狗；子进程阻塞或被抢占时诊断不够直观。
5. 锁定证据从 Top-K candidate 中取图，极少数情况下第一张 exact vote 图在锁定时已不在 Top-K，导致证据目录只保存一张图，但 `lock.json` 仍有两个投票事件。

这些是下一轮值得修的可靠性问题，但应先排除 `multisense` 占用并完成稳定复测。

### 7.2 `RK3588_dev/run_sc850_video71_alpr_live.sh`

本地路径：`D:\YOLO_ALPR_Project\RK3588_dev\run_sc850_video71_alpr_live.sh`  
远程路径：`/root/alpr_topk_rk3588/run_sc850_video71_alpr_live.sh`  
当前本地 SHA-256：`CF0B8354677633F77215BAEF949ABBB3A644CD5C603A1380533CB58415507027`

作用：当前常驻/演示启动配置。它是 Shell 配置和启动器，不是另一套识别算法。最后用 `exec python3 ...` 启动上述 Python 主程序。

核心参数：

- `/dev/video71`
- 3840x2160
- NV12
- `v4l2ctl` backend
- vehicle RKNN：`/root/rk3588_alpr_roadtest_bundle_20260701/deploy/vehicle.rknn`
- plate RKNN：`/root/rk3588_alpr_roadtest_bundle_20260701/deploy/best_obb.rknn`
- OCR：HyperLPR3
- ROI：`0.02 0.18 0.57 0.95`
- vehicle/plate conf：0.25
- 最小可处理/锁定车辆：180x110、面积 20000、面积比 0.006
- `track-max-age=2`
- locked/unlocked predict：0
- locked reassociation：关闭
- plate attempt：每个 processed frame
- 最少 OCR 置信度：0.70
- 锁定：2 个 exact-text 一致事件
- 严格中国车牌格式：开启
- 相同车牌事件去重：60 processed frames

两种 profile：

| profile | ROI tiles | 预览发布 | 预览宽度 | JPEG | 用途 |
|---|---:|---:|---:|---:|---|
| `balanced`（默认） | 1x1 | 每 2 processed frames | 1280 | 60 | 当前性能优先主线 |
| `quality` | 1x2 | 每 processed frame | 1920 | 75 | 旧的较高预览质量配置 |

### 7.3 `RK3588_dev/sc850_video71_vehicle_probe_collect.sh`

作用：历史上的有界诊断和回传打包脚本。它会收集：

- v4l2 节点状态；
- media graph；
- rkaiq 信息；
- dmesg；
- 脚本哈希；
- 单帧 raw/JPEG；
- 一段有界 ALPR 运行；
- 最终打包为 `/tmp/sc850_video71_vehicle_probe_<TAG>.tar.gz`。

重要警告：该脚本默认 `MIN_PROCESS_VEHICLE_CONF=1.10`、`OCR_ENGINE=none`，目的是诊断车辆/车牌链路，不是最终实时识别配置。不能拿它的 `PLATE` 占位或 `none` 模式当作已经完成 OCR。

### 7.4 `alpr_topk_capture.py`

Windows 基准主线。除非用户明确要求，不要修改。它用于证明算法基准和对照，不负责 SC850SL MIPI 设备管理。

### 7.5 `alpr_topk_capture_demo.py`

Windows 实验版本。需要做 Windows 侧新实验时优先修改它，避免污染基准。

### 7.6 `rk3588_topk_capture.py`

通用 RK3588 板端主线，主要用于内置视频和通用板端优化。

### 7.7 `rk3588_topk_capture_mipi_debug.py`

本地 IMX585/MIPI 调试脚本，是 SC850 专用脚本的前身和对照版本。

### 7.8 `build_sc850_progress_report.py`

根据项目状态、截图和测试数据生成阶段汇报文档。对应产物位于 `汇报\SC850SL_RK3588_项目进度汇报_20260711.docx`。

---

## 8. 当前文件结构和每类文件作用

项目含虚拟环境、第三方源码、模型、数据集和成千上万生成文件，不能把 `.venv` 中每个依赖文件逐一列出。下面覆盖项目自有关键文件、主目录和全部与当前主线直接相关的文件；依赖目录和批量实验目录按类别说明。

### 8.1 根目录关键文档

| 文件 | 作用 |
|---|---|
| `AGENTS.md` | 长期协作规则、红线、阅读顺序 |
| `NEW_CHAT_HANDOFF_20260717.md` | 当前最新完整交接，状态冲突时优先 |
| `NEW_CHAT_HANDOFF_20260710.md` | sensor/推流/早期 probe 的详细历史 |
| `NEW_CHAT_HANDOFF_20260708.md` | 更早一轮交接 |
| `PROJECT.md` | 项目长期目标、模块和范围 |
| `STATUS.md` | 截至 7 月 10 日左右的阶段状态，部分摄像头结论已过时 |
| `DECISIONS.md` | 重要技术决策及理由 |
| `HANDOFF.md` | 旧阶段接手说明 |
| `PROJECT_HANDOFF.md` | 早期总交接 |
| `PROJECT_HANDOFF_20260626_legacy.md` | 旧版留档 |
| `REMOTE_CODEX_HANDOFF.md` | 远程协作相关历史说明 |
| `AGENTS_0708.md` | 7 月 8 日规则快照 |
| `PR0JECT_0708.md` | 7 月 8 日项目快照，文件名中的 0 是历史遗留 |
| `STATUS_0708.md` | 7 月 8 日状态快照 |
| `DECISIONS_0708.md` | 7 月 8 日决策快照 |
| `HANDOFF_0708.md` | 7 月 8 日交接快照 |

### 8.2 根目录主程序和辅助脚本

| 文件 | 作用 |
|---|---|
| `alpr_topk_capture.py` | Windows 基准 Top-K ALPR 主线 |
| `alpr_topk_capture_demo.py` | Windows 可修改实验线 |
| `rk3588_topk_capture.py` | 通用 RK3588 内置视频主线 |
| `rk3588_topk_capture_mipi_debug.py` | IMX585/MIPI 调试线 |
| `rk3588_topk_capture_mipi_debug_sc850.py` | 当前 SC850SL `/dev/video71` 主程序 |
| `alpr_sahi_snapshot.py` / `alpr_sahi_snapshot2.py` | 早期 SAHI 切片检测快照实验 |
| `main.py` | 早期 ALPR/流处理入口，非当前 SC850 主线 |
| `api_with_tracking.py` | 早期带追踪的 API 实验 |
| `cascade_stream.py` / `cascade_stream2.py` | 早期级联推流实验 |
| `hyperlpr3_ocr.py` | HyperLPR3 单独 OCR 调用/验证 |
| `plate_rec_ocr.py` | 车牌识别模型实验 |
| `ocr_compare_topk.py` | OCR 结果对比工具 |
| `mipi_current_frame_probe.py` | 当前 MIPI 帧快速检查 |
| `rk3588_mipi_isp_probe.py` | RK3588 MIPI/ISP 诊断 |
| `test_image.py` / `test_image2.py` | 早期单图检测/识别测试 |
| `test_deblur_image.py` | 单图去模糊实验 |
| `test_deblur_hyperlpr3.py` | 去模糊与 HyperLPR3 组合测试 |
| `prepare_deblur_dataset.py` / `prepare_deblur_dataset_v2.py` | 去模糊训练数据准备 |
| `train_deblur_colab.py` | Colab 去模糊训练 |
| `prepare_obb_finetune_dataset.py` | OBB 微调数据准备 |
| `train_obb_colab.py` | Colab OBB 训练入口 |
| `annotate_obb_review.py` | OBB 人工复核标注 |
| `export_obb_review_pack.py` | 导出 OBB 复核包 |
| `topk_report.py` | Top-K 运行结果整理/报告 |
| `build_alpr_demo_report.py` | 早期演示汇报文档生成 |
| `build_sc850_progress_report.py` | SC850SL 阶段汇报文档生成 |

### 8.3 根目录模型和模型说明

| 文件/目录 | 作用 |
|---|---|
| `best_obb.pt` | 车牌 OBB PyTorch 权重 |
| `best_obb_finetuned_e8.pt` / `best_obb_finetuned_e20.pt` | OBB 微调权重 |
| `yolo11n.pt` / `yolov8n.pt` | 通用 YOLO 车辆检测基线权重 |
| `RealESRGAN_x4plus.pth` | Real-ESRGAN 超分模型；未直接接入 RK 实时主线 |
| `ESPCN_x4.pb` | ESPCN 超分模型实验 |
| `LPDGAN.zip` / `LPDGAN` | 去模糊/车牌增强相关第三方实验 |
| `rknn-toolkit2-master.zip` | RKNN 模型转换工具源码包 |
| `rknpu2-master.zip` | RK NPU runtime/examples 源码包 |
| `blur models` | 去模糊模型和相关文件 |
| `models_run` / `My_models` | 训练/模型实验产物 |
| `COLAB_DEBLUR_V2_E20_STEPS.md` | 去模糊 Colab 操作步骤 |
| `COLAB_TRAINING_GUIDE.md` | 通用 Colab 训练说明 |
| `OBB_FINETUNE_COLAB.md` | OBB 微调说明 |

去模糊和超分曾做过探索，但没有经过足够板端实时收益验证，不能直接接入当前 RK 实时主链。

### 8.4 根目录数据、结果和工具目录

| 目录 | 作用 |
|---|---|
| `captures*` | Windows/板端历史 Top-K、A/B、去模糊、基准运行结果 |
| `captures_topk_codex_win_20260708` | 7 月 8 日 Windows 基准证据 |
| `captures_topk_codex_win_20260710` | 后续 Windows 运行证据 |
| `Dataset` | 数据集 |
| `测试图` | 人工测试图片 |
| `obb_ab_single_frames` | OBB A/B 单帧样本 |
| `python_deps` / `python_deps_ocr` | 离线 Python 依赖 |
| `.venv` | 本地 Python 虚拟环境，不是项目业务代码 |
| `Ultralytics` | Ultralytics 第三方源码/环境 |
| `LibreOffice` | 本地 LibreOffice 便携/运行文件，用于文档渲染 |
| `tools` | 项目辅助工具 |
| `report_assets_sc850_progress` | SC850 汇报使用的图片等素材 |
| `report_render*` / `_docx_render*` / `lo_profile_report*` | 汇报文档渲染和视觉检查中间产物 |
| `汇报` | 最终阶段汇报文档和演示材料 |
| `论文` | 论文/研究相关材料 |

### 8.5 `RK3588_dev` 直接相关文件

| 文件 | 作用 |
|---|---|
| `run_sc850_video71_alpr_live.sh` | 当前 SC850 实时识别启动配置 |
| `sc850_video71_vehicle_probe_collect.sh` | 历史有界诊断和打包脚本 |
| `sc850_isp_probe.sh` | ISP 专项探针 |
| `vehicle.rknn` | RKNN 车辆检测模型 |
| `plate_obb.rknn` | RKNN 车牌 OBB 模型 |
| `plate_rec.rknn` | RKNN 车牌字符识别模型实验 |
| `best_obb.onnx` | OBB ONNX 中间模型 |
| `yolo11n.onnx` | 车辆检测 ONNX 中间模型 |
| `plate_rec.onnx` / `plate_rec_sim.onnx` | 车牌识别 ONNX 模型 |
| `dict.txt` | OCR 字符表 |
| `dataset.txt` | RKNN 量化/转换数据列表 |
| `onnx_to_rknn.py` | ONNX 转 RKNN |
| `convert_obb_640.py` / `convert_obb_640_fp16.py` | OBB 转换脚本 |
| `main.cpp` | C++ 端实验/示例，不是当前生产主线 |
| `rknn_model_info.cpp` | RKNN 模型信息检查 |
| `CMakeLists.txt` / `CMakeCache.txt` | C++ 示例构建配置/缓存 |
| `mipi_*.jpg` | MIPI 颜色、低光、车牌扫描等历史样图 |
| `reassoc_*.jpg` | 追踪重关联/轨迹实验预览 |
| `sc850_alpr_performance_profile_20260714.tar.gz` | balanced 性能配置和相关证据包 |
| `sc850_recognition_feedback_20250629_033539.tar.gz` | 第一批真实道路识别反馈 |
| `sc850_recognition_batch_20250629_043039.tar.gz` | 较长批量真实道路识别证据 |
| `sc850_recognition_dedupe_20250630_000646.tar.gz` | 加入车牌文字去重后的长跑证据 |

### 8.6 `RK3588_dev` 分析目录

| 目录 | 作用 |
|---|---|
| `_analysis_sc850_recognition_feedback_20250629_033539` | 第一批反馈包解压和统计 |
| `_analysis_sc850_recognition_batch_20250629_043039` | 批量包解压、人工核查和 contact sheet |
| `_analysis_sc850_recognition_dedupe_20250630_000646` | 去重包解压、21 个锁定事件分析和 contact sheet |

可直接展示的图片：

- `RK3588_dev\_analysis_sc850_recognition_batch_20250629_043039\lock_pairs_contact_sheet.png`
- `RK3588_dev\_analysis_sc850_recognition_dedupe_20250630_000646\lock_pairs_contact_sheet.png`

### 8.7 `RK3588_dev` 主要 probe 包

以下包按用途分组；同名 `_extract` 目录是解压后的原始文件：

| 包 | 用途/结论阶段 |
|---|---|
| `mediamtx_probe_20250626_085507.tar.gz` | mediamtx 配置、脚本和状态探测 |
| `mediamtx_live_probe_20250626_090155.tar.gz` | 推流运行态探测 |
| `sc850_file_versions_20250626_092450.tar.gz` | 关键远程脚本/配置版本对比 |
| `sc850_old_behavior_short_probe_20250626_093419.tar.gz` | 回看旧脚本行为 |
| `sc850_video71_upstream_probe_20250626_094644.tar.gz` | `/dev/video71` 上游 media 链检查 |
| `sc850_dt_gpio_power_probe_20250626_095237.tar.gz` | device tree、GPIO、供电探测 |
| `sc850_deep_dt_phandle_probe_20250626_095747.tar.gz` | phandle 和 sensor 绑定深查 |
| `sc850_media_graph_probe_20250626_105135.tar.gz` | media graph 拓扑 |
| `sc850_sensor_health_probe_*.tar.gz` | sensor/I2C/驱动健康状态 |
| `sc850_video71_recover_probe_20250626_130350.tar.gz` | video71 恢复尝试 |
| `sc850_video71_rkaiq_restart_probe_20250626_132231.tar.gz` | rkaiq 重启后的状态 |
| `sc850_rkaiq_binding_probe_20250626_133404.tar.gz` | rkaiq 与 sensor/ISP 绑定 |
| `sc850_rkaiq_debug_20250626_142419.tar.gz` | rkaiq 调试和恢复证据 |
| `sc850_video71_after_reboot_probe_20250626_084815.tar.gz` | 重启后的 video71 状态 |
| `sc850_video71_vehicle_probe_*.tar.gz` | 各阶段单帧、车辆、车牌、OCR、ROI 和长跑测试 |
| `sc850_isp_probe_latest.tar(.gz)` | 大体积 ISP 原始探针包 |

### 8.8 `RK3588_dev` 历史实验目录

- `rk_debug_1000*`：RK 1000 帧调试。
- `rk_tracker_*`、`rk_reassoc_*`：追踪、重关联和轨迹实验。
- `rk_windows_equiv_*`：尝试对齐 Windows 参数。
- `rk_hyperlpr_pre_*`：车辆 crop 预 OCR 实验。
- `rk_plate_predicted_*`：预测框上跑车牌检测实验。
- `rk_adaptive_i3`：adaptive 检测间隔实验。
- `board_smoke_144_track2`：内置视频烟雾测试。
- `mipi_color_probe`、`mipi_current_probe_live`：MIPI 颜色和当前帧探测。
- `runs_codex_mipi_debug_video_20260708`：7 月 8 日 MIPI 调试运行。
- `offline_bundle`：可上传板端的离线完整包；其中有 `rk3588_alpr_roadtest_bundle_20260701`。

### 8.9 远程板目录

| 路径 | 作用 |
|---|---|
| `/root/alpr_topk_rk3588` | 当前 SC850 代码、运行日志和 `runs_*` 输出 |
| `/root/rk3588_alpr_roadtest_bundle_20260701` | 模型和离线依赖 |
| `/root/deploy/stream.py` 或板端现有 `stream.py` | 历史上用于将 `/tmp/frame.jpg` 提供给浏览器，确切启动路径应以 `ps` 为准，端口通常 8080 |
| `/tmp/frame.jpg` | 浏览器最后一次发布的预览帧，可能是旧帧 |
| `/root/mediamtx` | 独立 RTSP 推流工具目录 |
| `/opt/MultiSensing/bin/multisense` | 当前会抢占 `/dev/video71` 的另一套程序 |

ALPR、mediamtx 推流和 multisense 不应同时独占 `/dev/video71`。

### 8.10 当前 Git 工作区状态

截至本文创建时，工作区不是 clean 状态：

- `rk3588_topk_capture_mipi_debug_sc850.py`：已修改；
- `RK3588_dev/run_sc850_video71_alpr_live.sh`：已修改；
- `RK3588_dev/_analysis_sc850_recognition_dedupe_20250630_000646/`：未跟踪分析目录；
- `RK3588_dev/sc850_alpr_performance_profile_20260714.tar.gz`：未跟踪回传包；
- `RK3588_dev/sc850_recognition_dedupe_20250630_000646.tar.gz`：未跟踪回传包；
- `NEW_CHAT_HANDOFF_20260717.md`：本次新增。

这些都应视为用户当前工作，不得为了得到 clean tree 而 reset、checkout 或删除。

---

## 9. 已完成测试和结果

### 9.1 Windows 基准

代表运行：`captures_topk_codex_win_20260708\run_20260708_131529`

- 6971 帧；
- 8 个 track；
- 锁定结果包含 `冀JC5216`、`冀B6R9F9`、`鲁V0JU1Q`、`冀CH7V97` 等；
- 其中至少一个结果与肉眼字符存在差异，仍需保留人工复核，不能宣称全对。

结论：Windows 基准主链可用，是板端结果的对照，不应随意改动。

### 9.2 本地 RK3588 + IMX585 内置视频

测试视频：`/root/deploy/144.mp4`

- 至少跑到 1000 帧；
- 一次 2026-07-10 左右运行约 4.37 FPS，锁定 `冀JE5210`、`冀B6R9F9`；
- 更早配置约 10 FPS，锁定 `冀JC5210`、`冀B6R9F9`；
- 字符差异说明 OCR 仍需要证据核查，但主流程完整。

### 9.3 远程 SC850SL 板内置视频

使用同一离线 bundle 和内置视频跑通过，结果与本地 RK 大体相当。

结论：远程板的 RKNN runtime、模型、Python 依赖、HyperLPR3 和保存逻辑可用。真实摄像头问题不能直接归咎于 ALPR 主逻辑。

### 9.4 SC850SL 摄像头链路演进

历史上经历过多个节点和状态：

- `/dev/video33`：曾作为 RAW10 临时可用路径；
- `/dev/video44`：`rkisp0-vir0`，不是最终 SC850 mainpath；
- `/dev/video53`：属于另一条 sensor/ISP 链；
- `/dev/video71`：最终确认的 SC850 `rkisp1-vir1 mainpath`，NV12。

早期 sensor 掉线阶段出现过：

- I2C bus 4 没有 `0x30/UU`；
- `get remote terminal sensor failed`；
- `rkisp1-vir1 check rkisp_mainpath link or isp input`；
- 0 字节或 stream timeout。

后来重新恢复后确认：

- dmesg 出现 SC850SL driver 和 `Detected sc850sl id 009d1e`；
- mediamtx 能从 `/dev/video71` 推 4K 流；
- RTSP `rtsp://192.168.8.88:8559/video71` 可显示真实道路画面；
- 独占节点时 `v4l2-ctl` 可 3840x2160 NV12 30 FPS。

因此“SC850 sensor 当前没上线”已经是过期结论。

### 9.5 第一批真实道路识别反馈

包：`sc850_recognition_feedback_20250629_033539.tar.gz`

- 1098 processed frames；
- 447.486 秒；
- 约 2.45 FPS；
- vehicle raw detections：3134；
- vehicles ready：321；
- plate attempts：321；
- OBB candidates：268；
- HyperLPR calls/有效返回：105；
- accepted candidates：105；
- 保留下来的锁定 track 包含 `苏E51PK6`，frame 1075；
- stop reason：`keyboard_interrupt`。

意义：证明真实道路流已经走完整的“车辆 -> OBB -> HyperLPR3 -> 锁定 -> 保存证据”链路。

### 9.6 批量真实道路识别

包：`sc850_recognition_batch_20250629_043039.tar.gz`

- 2155 processed frames；
- 915.234 秒；
- 约 2.35 FPS；
- vehicle raw：5933；
- vehicles ready：808；
- plate attempts：808；
- OBB candidates：970；
- OCR/HyperLPR 有效：258；
- accepted：258；
- 20 个 lock evidence group；
- 人工查看 contact sheet 后，19 个唯一文字，其中一个车牌重复锁定；
- 画面和锁定文字总体有视觉一致性，但没有完整 ground truth，不能换算正式准确率；
- stop reason：`keyboard_interrupt`。

可展示：`RK3588_dev\_analysis_sc850_recognition_batch_20250629_043039\lock_pairs_contact_sheet.png`。

### 9.7 加入文字去重后的长跑

包：`sc850_recognition_dedupe_20250630_000646.tar.gz`

- 3392 processed frames；
- 1379.518 秒；
- 约 2.46 FPS；
- vehicle raw：4734；
- vehicles ready：1113；
- plate attempts：1113；
- OBB candidates：695；
- OCR/HyperLPR 有效：374；
- accepted：374；
- lock events emitted：21；
- lock evidence：21；
- duplicate events suppressed：2。

去重实例：

- `苏E997AZ` 在 frame 708/720 重复，后一次被抑制；
- `苏E6X667` 在 frame 2119/2128 重复，后一次被抑制。

21 个已发出文字：

`苏EL9035`、`湘A270LD`、`苏U761PJ`、`苏BDG8070`、`苏E997AZ`、`苏UK103H`、`苏UJ709U`、`苏E59F2V`、`苏E51LW3`、`苏E3S16Z`、`苏U377MR`、`苏EDZ6922`、`苏E52385`、`粤ED92899`、`苏E6X667`、`沪EC5F2Y`、`苏E3X068`、`苏C3046U`、`苏UDU447`、`粤EA74777`、`沪EC99391`。

证据完整性：

- 19 个 lock group 保存了两张 exact-vote 图；
- `沪EC5F2Y`、`沪EC99391` 只保存了一张图；
- 两者的 `lock.json` 内仍有两个独立 OBB/OCR 投票帧，所以锁定条件确实满足，但图片保存逻辑需要加强。

锁定候选统计：

- plate width：min 43.6、mean 58.4、max 70.8 px；
- plate height：min 14.1、mean 20.0、max 24 px；
- OCR confidence：min 0.781、mean 0.928、max 1.000；
- OBB confidence：min 0.648、mean 0.898、max 0.961。

结束日志：

- summary 写了 `vehicle: empty RKNN output`；
- 日志前后紧邻 KeyboardInterrupt；
- 目前只能说“停止时出现 empty output”，不能在没有复现前定性为 NPU 故障。

dmesg：未见该次运行相关的 SC850/I2C/ISP/OOM 错误；有一些无关的 Wi-Fi/蓝牙固件信息。

可展示：`RK3588_dev\_analysis_sc850_recognition_dedupe_20250630_000646\lock_pairs_contact_sheet.png`。

### 9.8 balanced 性能短测

当前性能包：`RK3588_dev\sc850_alpr_performance_profile_20260714.tar.gz`  
SHA-256：`8D87F90D47676AE8EAA19943CAB3E3D318BA2DAC65ECCF1E3DA1E47480A87EEB`

板端截图/日志确认：

- 运行 profile：balanced；
- 处理到 frame 208；
- 正常推进阶段进度日志约 3.86-4.50 FPS；
- frame 200 附近约 4.17 FPS；
- 相比旧长跑约 2.46 FPS，稳态提升约 70%；
- 期间有 2 个 lock event 和 evidence；
- 终端中文在截图里有乱码，不能据乱码字符判断 OCR 错误。

分项耗时：

| 项目 | 总耗时 | 每 processed frame |
|---|---:|---:|
| vehicle RKNN | 14.923 s | 71.747 ms |
| plate RKNN | 2.598 s | 12.493 ms |
| HyperLPR3 | 2.541 s | 12.216 ms |
| preview publish | 3.986 s | 19.165 ms |

run summary 的 elapsed 约 370.41 秒，是因为正常处理后又发生长时间停顿，不能用 `208/370` 代表稳态 FPS。应以进度日志正常推进区间的约 4.17 FPS 为当前性能基线。

### 9.9 最新卡流和 30 FPS 直采验证

卡流时观察到：

- 浏览器停在旧画面；
- `/tmp/frame.jpg` 修改时间不再变化；
- ALPR 进程已经退出，只剩 `stream.py`；
- dmesg 出现 RGA/DMA buffer 错误，期望约 3,110,400 字节 RGBA，实际拿到 77,824 或 2,088,960 字节；
- `/dev/video71` 被 `multisense` 打开；
- `v4l2-ctl` 设置格式返回 `Device or resource busy`。

清掉 `multisense` 占用后，执行 30 帧测试：

- 成功设置 3840x2160 NV12；
- 1 plane；
- `Size Image: 12441600`；
- 30 帧连续输出；
- 约 29.99-30.00 FPS；
- `capture_test_exit=0`。

结论：当前 sensor/ISP/video71 能正常工作。卡流的直接冲突对象是 `multisense`，不是已经证明的 sensor 物理故障。

---

## 10. 我们做过的主要尝试

### 10.1 算法和模型

1. Windows YOLO/OBB/HyperLPR3 基线。
2. Top-K 候选保存和多帧投票。
3. rejected candidate、summary、vote history 诊断。
4. OBB 模型微调和 ONNX/RKNN 转换。
5. RKNN 车辆和车牌模型上板。
6. HyperLPR3 与 RKNN OCR 比较。
7. OCR `none` 诊断模式，隔离 OCR 与检测链路。
8. 严格中国车牌格式过滤。
9. OCR 乱码修复。
10. 两次 exact-text 一致锁定。
11. 相同车牌文字窗口去重。
12. HyperLPR 预识别、预测框识别、adaptive 检测间隔等实验。

### 10.2 追踪相关

1. Simple IoU tracker。
2. tracker max age 调整。
3. 速度外推和 Kalman box prediction。
4. locked track 重关联。
5. 预测帧上继续 plate/OCR。
6. 轨迹和 anchor 保存。

实际效果：画面框太乱，远处目标和电动车也参与，预测框与真实车位置偏差会污染识别，且增加复杂度。用户后来明确把识别率放在追踪之前，因此当前关闭大部分预测/重关联，只保留短期状态。

### 10.3 ROI 和过滤

1. 全画面检测。
2. 多种道路 ROI。
3. ROI 右边界扩大到画面边缘的讨论和测试。
4. 最终根据实际道路把 ROI 收到左侧机动车道，排除右侧楼体和非机动车道。
5. 车辆置信度、宽高、面积和面积比门控。
6. 远车过滤和锁定门槛。
7. 车辆 ROI 1x2 tiles 与 1x1 比较。

当前 ROI 不是永久真理。如果摄像头角度变化，应基于新画面重新标定，但不能为了“框更多”盲目扩到无效区域。

### 10.4 MIPI、ISP 和节点定位

1. `/dev/video33` RAW10 临时路径。
2. `/dev/video44`、`/dev/video53`、`/dev/video71` 格式和 media graph 比较。
3. OpenCV V4L2 与 `v4l2-ctl` mmap 后端比较。
4. UYVY、NV12、RAW10 颜色/灰度解码。
5. gray-world、低光增强和颜色探针。
6. media-ctl topology。
7. rkaiq 绑定和重启探针。
8. I2C bus 4、0x30、GPIO、regulator、device tree/phandle 检查。
9. sensor 重插、重启和旧文件回滚检查。
10. mediamtx RTSP 推流验证。
11. `v4l2-ctl` 4K NV12 30 帧独占直采。

### 10.5 性能优化

1. 从 OpenCV capture 切到 `v4l2-ctl` mmap。
2. 减少 ROI tile：1x2 -> 1x1。
3. 预览从 1920/q75/每帧改成 1280/q60/每两帧。
4. 保留 4K 车牌 crop，不降低原始识别输入质量。
5. 增加车辆、车牌、OCR、预览分项 timing。
6. balanced/quality profile 可切换。

效果：约 2.46 -> 4.17 FPS，但仍达不到高速车辆理想需求。

### 10.6 证据收集和人工核查

1. 多次 probe tar.gz 回传。
2. 单帧 raw/JPEG、v4l2、media graph、dmesg 同包保存。
3. 长时间真实道路识别批次。
4. 逐 lock group 查看 full frame、vehicle crop、plate crop、lock.json。
5. 生成 contact sheet。
6. 分析重复锁定并实现文字事件去重。
7. 分析只有一张 evidence 图的异常。

### 10.7 去模糊和超分

做过数据准备、模型和 HyperLPR3 A/B 探索。当前没有证据证明在 RK3588 实时链路中收益大于性能成本，因此没有接入 SC850 实时主线。下一步应优先调曝光、提高采样处理 FPS，而不是直接加重型 deblur。

---

## 11. 不能随便推翻的结论和红线

1. `alpr_topk_capture.py` 是 Windows 基准，不要随意修改。
2. `ocr-engine none` 和 `PLATE` 只是诊断，不是最终 OCR 成果。
3. 远程板跑内置视频已证明 ALPR 主流程可用。
4. 真实 SC850 道路流已经产生过多批真实锁定证据。
5. `/dev/video71` 已经证明能 4K NV12 30 FPS，不能因为一次卡流又直接断言 sensor 没上线。
6. 当前卡流证据首先指向 `multisense` 占用。
7. 浏览器显示 `/tmp/frame.jpg`，旧画面不代表 Python 仍运行。
8. `Ctrl+C` 如果是在 `tail -f` 窗口，只会停止 tail；后台 ALPR 仍可能运行。
9. 不能让 ALPR、mediamtx 和 multisense 同时抢 `/dev/video71`。
10. 不要停止 `rkaiq_3A_server`。
11. 不要误杀当前 SSH/MobaXterm 会话。
12. 不能只看前 200 帧下最终结论；稳定测试至少 1000 processed frames。
13. 不要只看 accepted/lock 数量，不看 rejected、summary、vote history 和图像证据。
14. 不要为了增加命中数直接降低 OCR 置信度或单帧就锁定。
15. 没有完整 ground truth 前，不要宣称正式准确率。
16. 未验证的去模糊收益不能直接接入 RK 实时主链。
17. 当前工作区有用户未提交改动和分析目录，不得 reset、checkout 或覆盖。

---

## 12. 最新故障：`multisense` 抢占 `/dev/video71`

### 12.1 已抓到的进程事实

历史实例 PID 包括 10342、69536、74615、92464。PID 会变化，不要写死。

一次完整抓取：

- executable：`/opt/MultiSensing/bin/multisense`
- cmdline：`./multisense`
- PPID：1
- cgroup：`0::/user.slice/user-0.slice/session-165.scope`
- 不是已加载 systemd unit；标准 systemd/init/rc 路径没有找到对应配置。

MobaXterm Remote monitoring 的 `bash -c ... sleep 1` 监控循环与此无关。

同一个 PID 每秒被 `pgrep` 打印一次，只是监控循环重复显示，并不代表它每秒重启。

### 12.2 当前临时方案

上次建议是临时保存权限、终止进程、移除 executable 的执行位，避免它重新启动：

```bash
stat -c '%a' /opt/MultiSensing/bin/multisense \
  > /root/alpr_topk_rk3588/multisense_mode_before_alpr.txt
pkill -TERM -x multisense
sleep 2
chmod a-x /opt/MultiSensing/bin/multisense
```

该方案是否已经成功执行：**待确认**。新对话必须先检查，不能假设已经做过。

恢复时：

```bash
MODE=$(cat /root/alpr_topk_rk3588/multisense_mode_before_alpr.txt)
chmod "$MODE" /opt/MultiSensing/bin/multisense
stat -c '%a %A %n' /opt/MultiSensing/bin/multisense
```

注意：只有确认 mode 文件存在且内容是正常三位/四位权限数字时才恢复。

---

## 13. 新对话接手后的第一步

### 13.1 第一条建议命令：只检查，不改变状态

```bash
date
pgrep -af multisense || true
fuser -v /dev/video71 || true
stat -c '%a %A %n' /opt/MultiSensing/bin/multisense
cat /root/alpr_topk_rk3588/multisense_mode_before_alpr.txt 2>/dev/null || true
```

预期判断：

- 如果 `multisense` 仍存在或 `fuser` 显示它占用 video71，不要启动 ALPR。
- 如果 executable 已经没有执行位，要确认这是临时禁用方案的结果，不要重复乱改。
- 如果节点没有业务进程占用，再做 30 帧直采。

### 13.2 不要先执行的操作

- 不要先重启板子；
- 不要先调 OCR；
- 不要先重装模型；
- 不要杀 `rkaiq_3A_server`；
- 不要 `kill -9` 一串 video owner；
- 不要 `loginctl terminate-session 154`；
- 不要同时启动 mediamtx。

---

## 14. 推荐板端操作命令

以下命令供新对话在用户确认后逐步执行。

### 14.1 检查代码和语法

```bash
cd /root/alpr_topk_rk3588
python3 -m py_compile rk3588_topk_capture_mipi_debug_sc850.py
bash -n run_sc850_video71_alpr_live.sh
sha256sum rk3588_topk_capture_mipi_debug_sc850.py run_sc850_video71_alpr_live.sh
```

期望 SHA-256 与本文第 7 节一致。若不同，先做 diff/备份，不要覆盖远程文件。

### 14.2 确保没有冲突占用

```bash
pgrep -af 'multisense|mediamtx|gst-launch|rk3588_topk_capture_mipi_debug_sc850.py'
fuser -v /dev/video71
```

`rkaiq_3A_server` 可能打开 ISP 相关节点，不能因此停止它。

### 14.3 经用户确认后临时禁用 multisense

```bash
cd /root/alpr_topk_rk3588
if [ ! -s multisense_mode_before_alpr.txt ]; then
  stat -c '%a' /opt/MultiSensing/bin/multisense > multisense_mode_before_alpr.txt
fi
pkill -TERM -x multisense || true
sleep 2
chmod a-x /opt/MultiSensing/bin/multisense
pgrep -af multisense || true
fuser -v /dev/video71 || true
stat -c '%a %A %n' /opt/MultiSensing/bin/multisense
```

如果仍自动出现，不要反复 kill。继续定位父进程、cgroup、登录会话和启动者。

### 14.4 4K NV12 30 帧直采

```bash
timeout 15 v4l2-ctl \
  -d /dev/video71 \
  --set-fmt-video=width=3840,height=2160,pixelformat=NV12 \
  --stream-mmap=4 \
  --stream-count=30 \
  --stream-to=/dev/null \
  --verbose
echo "capture_test_exit=$?"
```

成功标准：

- `VIDIOC_S_FMT: ok`；
- `VIDIOC_REQBUFS returned 0`；
- 连续输出 seq 0-29；
- 约 30 FPS；
- `capture_test_exit=0`。

### 14.5 启动 balanced ALPR

```bash
cd /root/alpr_topk_rk3588
LOG_NAME="sc850_balanced_restart_$(date +%Y%m%d_%H%M%S).log"
nohup env ALPR_PROFILE=balanced ./run_sc850_video71_alpr_live.sh \
  > "$LOG_NAME" 2>&1 &
echo $! > sc850_balanced.pid
echo "pid=$(cat sc850_balanced.pid) log=$LOG_NAME"
tail -f "$LOG_NAME"
```

浏览器：`http://192.168.8.88:8080`

注意：在 `tail -f` 上按 `Ctrl+C` 只停止日志跟随，不停止后台 ALPR。

### 14.6 确认实时运行

另开一个 SSH 标签页：

```bash
cd /root/alpr_topk_rk3588
PID=$(cat sc850_balanced.pid)
ps -fp "$PID"
fuser -v /dev/video71
stat /tmp/frame.jpg
sleep 3
stat /tmp/frame.jpg
```

判断：

- Python/脚本进程存在；
- video71 owner 是当前 ALPR/v4l2-ctl 链；
- `/tmp/frame.jpg` 时间和大小持续变化；
- 日志 processed frame 持续增加。

### 14.7 正确停止并保存结果

```bash
cd /root/alpr_topk_rk3588
PID=$(cat sc850_balanced.pid)
kill -INT "$PID"
for _ in $(seq 1 30); do
  kill -0 "$PID" 2>/dev/null || break
  sleep 1
done
if kill -0 "$PID" 2>/dev/null; then
  echo "ALPR still exists after 30 seconds; inspect before using stronger signals" >&2
else
  echo "ALPR stopped and final summary should be saved"
fi
```

如果 shell script 已 `exec python3`，pid 文件中的 PID 就是 Python PID。优先 SIGINT，让程序进入 finally 保存 summary；不要先用 `kill -9`。

### 14.8 恢复 multisense 权限

只在 ALPR 测试结束、确实需要恢复原系统功能时执行：

```bash
cd /root/alpr_topk_rk3588
MODE=$(cat multisense_mode_before_alpr.txt)
case "$MODE" in
  [0-7][0-7][0-7]|[0-7][0-7][0-7][0-7])
    chmod "$MODE" /opt/MultiSensing/bin/multisense
    ;;
  *)
    echo "invalid saved mode: $MODE" >&2
    exit 1
    ;;
esac
stat -c '%a %A %n' /opt/MultiSensing/bin/multisense
```

---

## 15. 如何积累并打包本次测试

建议先跑满至少 1000 processed frames，并覆盖：

- 红灯慢车；
- 正常速度车辆；
- 较快车辆；
- 白天逆光/阴影；
- 公交、货车、轿车；
- 可能误检的电动车和路边静态车。

停止后执行：

```bash
cd /root/alpr_topk_rk3588
TAG=$(date +%Y%m%d_%H%M%S)
OUT="/tmp/sc850_balanced_feedback_${TAG}"
mkdir -p "$OUT"

cp -a rk3588_topk_capture_mipi_debug_sc850.py "$OUT/"
cp -a run_sc850_video71_alpr_live.sh "$OUT/"
cp -a sc850_balanced_restart_*.log "$OUT/" 2>/dev/null || true
cp -a /tmp/frame.jpg "$OUT/final_frame.jpg" 2>/dev/null || true

LATEST_RUN=$(find /root/alpr_topk_rk3588 -maxdepth 2 -type d \
  -path '*/runs_sc850_video71_live/run_*' -printf '%T@ %p\n' 2>/dev/null \
  | sort -nr | head -n1 | cut -d' ' -f2-)
if [ -n "$LATEST_RUN" ]; then
  cp -a "$LATEST_RUN" "$OUT/run"
fi

v4l2-ctl -d /dev/video71 --all > "$OUT/video71_all.txt" 2>&1 || true
v4l2-ctl -d /dev/video71 --list-ctrls-menus > "$OUT/video71_ctrls.txt" 2>&1 || true
fuser -v /dev/video71 > "$OUT/video71_owner.txt" 2>&1 || true
pgrep -af 'multisense|mediamtx|gst-launch|rk3588_topk' > "$OUT/processes.txt" 2>&1 || true
dmesg -T | tail -n 300 > "$OUT/dmesg_tail.txt"
sha256sum rk3588_topk_capture_mipi_debug_sc850.py \
  run_sc850_video71_alpr_live.sh > "$OUT/sha256.txt"

tar -C /tmp -czf "/tmp/sc850_balanced_feedback_${TAG}.tar.gz" \
  "sc850_balanced_feedback_${TAG}"
ls -lh "/tmp/sc850_balanced_feedback_${TAG}.tar.gz"
```

然后按既有路径传回：

`/tmp/sc850_balanced_feedback_<TAG>.tar.gz -> E:\YOLO_ALPR -> D:\YOLO_ALPR_Project\RK3588_dev`

人工核查时至少看：

1. `run_summary.json`；
2. 主日志；
3. 每个 `locks/lock_*` 的 full frame、vehicle crop、plate crop；
4. `lock.json` 两个 exact vote frame；
5. rejected 原因；
6. FPS 正常区间，不要把停止后的等待算进稳态；
7. dmesg 是否有 sensor/I2C/ISP/RGA/OOM；
8. 测试结束时谁占用 video71。

---

## 16. 下一步优化路线

### P0：先保证摄像头独占和长跑稳定

1. 确认 multisense 临时禁用状态。
2. 30 帧 4K NV12 直采。
3. balanced 跑至少 1000 processed frames。
4. 观察是否再次卡在固定帧或被抢占。
5. 保存完整包。

### P1：增强捕获故障可诊断性

在 Python 中小范围修改：

1. 捕获 `v4l2-ctl` stderr 到文件或 ring buffer；
2. `read()` 失败时记录 return code；
3. 设置 `stop_reason=camera_read_failed`；
4. summary 写入当前 pixel format、owner、最后 stderr；
5. 视风险加入读取超时和一次受控重启，而不是无限重启；
6. 浏览器叠加“最后帧时间/输入中断”状态，避免旧帧误导。

### P1：保证锁定证据完整

投票发生时单独保存 exact-vote candidate，锁定时直接复制两个真实投票帧，不依赖候选是否仍在 Top-K。

### P1：降低运动模糊

先收集：

```bash
v4l2-ctl -d /dev/video71 --list-ctrls-menus
v4l2-ctl -d /dev/video71 --all
```

当前历史包曾看到 exposure=3、analogue_gain=75，但单位和自动模式未确认。只有弄清控制项含义后，才尝试更短曝光和相应增益补偿。目标是让高速车牌字符边缘更清晰；代价是噪声上升，必须 A/B。

### P1：继续提高处理 FPS

从已有 timing 看：

- vehicle RKNN 是已记录的大项；
- preview 仍约 19 ms/processed frame；
- plate/OCR 平均开销相对可控；
- 4K NV12 转 BGR、resize、Python/OpenCV 内存复制没有被当前 timing 完整覆盖，可能占据大量剩余时间。

建议：

1. 增加 capture read、NV12 转换、ROI resize、tracker/绘制、save 的完整分项 timing；
2. 减少 4K 全帧复制；
3. 评估只转换有效 ROI 或使用 RGA 的可行性，但先解决当前 RGA buffer 冲突来源；
4. 保持 4K 原图用于 plate crop，车辆检测可在低分辨率 ROI 上进行；
5. 评估预览发布每 3 帧或进一步缩小，但不影响识别主链；
6. 只有在确认 NPU/runtime 支持和线程安全后再考虑模型流水并行。

### P2：建立正式准确率评估

1. 从视频中按固定时间抽帧；
2. 人工标注“可见机动车数、可读车牌、真实字符”；
3. 统计 vehicle recall、plate OBB recall、OCR exact match、最终 lock recall、误锁率和首次锁定延迟；
4. 区分慢车、快车、公交、轿车、逆光和阴影；
5. 再根据数据决定 ROI、曝光、阈值和模型优化。

---

## 17. 可能被问到的问题

### 17.1 项目主要用什么语言？

当前主线主要是 Python；Shell 负责板端启动和参数配置；底层 RKNN runtime、V4L2、ISP/RGA 驱动是 C/C++ 实现但由 Python 调用。`RK3588_dev/main.cpp` 是实验/示例，不是当前实时主程序。

### 17.2 为什么不用 C++ 全部重写？

C++ 可能减少 Python 调度、内存复制和部署开销，但当前主要瓶颈还包括 4K 图像转换、模型推理、摄像头独占和 ISP。直接重写成本大、容易丢掉 Top-K、证据和 OCR 逻辑。先用 timing 找出真实瓶颈，再决定是否把 capture/颜色转换/推理热点下沉到 C++。

### 17.3 为什么以前不能推流，现在又可以？

以前处于 sensor/I2C/ISP 链未正确上线阶段，video71 上游不完整。后来 sensor 被驱动识别，mediamtx 脚本按正确节点和格式启动，推流成功。现在偶发卡住的主要新问题是 multisense 与 ALPR 抢同一节点，不等于又回到旧的 sensor 物理故障。

### 17.4 为什么摄像头 30 FPS，识别只有 4 FPS？

30 FPS 是采集能力。每个 processed frame 还要做 4K NV12 转换、车辆 RKNN、plate RKNN、HyperLPR3、绘制、JPEG 编码和 Python 数据处理，因此处理吞吐低得多。

### 17.5 为什么红灯慢车更容易识别？

慢车在 ROI 停留更久、运动模糊更小，在 4 FPS 采样下能提供更多清晰帧，更容易获得两个一致 OCR 事件。高速车可能只留下少量可用帧。

### 17.6 为什么不能直接单帧锁定或降低阈值？

这样会提高表面命中数，也会显著增加误锁。当前两帧 exact-text 和严格格式是已有真实证据支持的重要质量门槛。应先提高有效帧率和图像清晰度。

### 17.7 为什么浏览器还显示画面，程序却已经停了？

`stream.py` 只持续提供 `/tmp/frame.jpg`。如果 ALPR 停止更新，浏览器仍会看到最后一张旧图。必须同时看进程、日志和文件修改时间。

### 17.8 为什么按 Ctrl+C 浏览器识别没停？

如果 ALPR 用 `nohup ... &` 后台启动，终端前台只是 `tail -f`。Ctrl+C 停的是 tail。应读取 pid 文件并向 ALPR PID 发 SIGINT。

### 17.9 黄色框是不是运动预测？

车牌周围的黄色多边形通常是 OBB 检测框。运动预测车辆框在代码中是橙色并标 `PRED`；当前启动配置已把预测设为 0。

### 17.10 当前识别率是多少？

目前没有正式 ground truth，不能给出可信百分比。现有多批 lock evidence 人工看起来大体合理，且去重批次有 21 个已发出锁定事件；但这不能替代召回率、误锁率和 exact OCR 的标注统计。

### 17.11 ISP 画面是否需要优化？

需要，尤其是高速运动模糊和部分过曝/偏灰。但应先读取真实 exposure/gain/AE 控制项，做短曝光 A/B，不应凭感觉写死未知单位参数。

### 17.12 追踪是不是已经完全删除？

没有从代码删除。当前配置只把 max age 和预测降到很低，保留短期 track ID 让同一车辆的两次 OCR 可以投票。长期跟随不是当前目标。

---

## 18. 新 AI 最容易犯的错误

1. 只读旧文档，然后仍断言 sensor 未上线。
2. 一上来继续调 OCR，而忽略 multisense 抢占。
3. 把 30 FPS 采集和 4 FPS 识别混为一谈。
4. 把浏览器旧帧当成程序仍运行。
5. 把黄色 OBB 框当预测框。
6. 把 `none`/`PLATE` 当 OCR 成功。
7. 看到 rkaiq 占节点就停止 `rkaiq_3A_server`。
8. 误结束当前 SSH session。
9. 只跑 200 帧就下稳定性结论。
10. 为提高 hit 数量随意降阈值。
11. 不看 lock evidence 和 rejected 就宣称准确。
12. 覆盖用户当前两份未提交主线文件。
13. 每轮都机械更新一堆 Markdown 文件。
14. 直接用 C++ 重写全部流程，未先测出真实热点。

---

## 19. 新对话建议发送的完整提示词

```text
请先完整阅读以下文件，不要先改代码、不要先跑实验：

1. AGENTS.md
2. NEW_CHAT_HANDOFF_20260717.md
3. rk3588_topk_capture_mipi_debug_sc850.py
4. RK3588_dev/run_sc850_video71_alpr_live.sh
5. RK3588_dev/sc850_video71_vehicle_probe_collect.sh

如需追溯旧实验，再读：

6. NEW_CHAT_HANDOFF_20260710.md
7. PROJECT.md
8. STATUS.md
9. DECISIONS.md
10. HANDOFF.md

当前目标是在远程电脑连接的 RK3588 板上，用 SC850SL 摄像头的 /dev/video71 3840x2160 NV12 真实道路流，实现车辆和中国车牌实时识别。识别率和稳定性优先，复杂追踪可以弱化。

请注意最新事实：SC850SL sensor/ISP/video71 已经恢复并验证过 4K NV12 30 FPS；真实道路 ALPR 已经回传过多批锁定证据。最近画面卡住的直接证据是 /opt/MultiSensing/bin/multisense 抢占 /dev/video71，并让 v4l2-ctl 报 Device or resource busy。不能再沿用“当前 sensor 没上线”的旧结论。

balanced 配置短测正常推进约 4.17 FPS，相比旧的约 2.46 FPS 提升约 70%，但仍不足以覆盖高速车辆。当前还需要排除 multisense 后跑满至少 1000 processed frames，并收集完整反馈包。

先只回答以下问题，等我确认后再继续：

1. 你理解的最终目标是什么？
2. 当前已经实现了什么？
3. 当前最关键卡点是什么？
4. 哪些旧结论已经过期？
5. 哪些结论和红线不能随便推翻？
6. 当前两份主线脚本分别是什么作用？
7. 你建议我在远程板上执行的第一组只读检查命令是什么？

额外要求：

- 默认中文；
- 区分事实、推断、待确认和建议；
- 不要停止 rkaiq_3A_server；
- 不要结束当前 SSH/MobaXterm 会话；
- 不要覆盖本地或远程现有脚本；
- 不需要每次对话都更新所有 md 文件。
```

---

## 20. 最短接手口径

项目不是卡在 OCR，也不是当前仍卡在 sensor 未上线。当前 SC850SL `/dev/video71` 能出 4K NV12 30 FPS，真实道路识别已完成多批证据；现在先解决 `multisense` 抢占导致的卡流，让 balanced 配置稳定跑满 1000 帧，再围绕运动模糊和 4.17 FPS 提高高速车辆车牌识别率。
