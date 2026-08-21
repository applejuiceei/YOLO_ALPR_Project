# 重要决定记录

更新时间：2026-08-14

## 决定 1：Windows 基准主线不随意修改

决定：

- `alpr_topk_capture.py` 作为 Windows 行为基准脚本，不随意修改。
- Windows 实验优先使用 `alpr_topk_capture_demo.py`。

原因：

- Windows 主线已经包含车辆检测、车牌 OBB、Top-K、HyperLPR3、OCR 投票、锁定跳过和诊断输出。
- 基准脚本稳定性比短期实验更重要。

## 决定 2：RK 端不机械复刻 Windows

决定：

- RK3588 使用专门设计的 `rk3588_topk_capture.py`。
- RK 端允许车辆检测降频、ROI、predicted display、锁定后跳过 OBB/OCR 等策略。

原因：

- RK 端依赖 RKNNLite、OpenCV、NumPy，算力和运行环境与 Windows/PyTorch 不同。
- MIPI、ISP、发布 `/tmp/frame.jpg` 和实时性要求会显著影响 FPS。

## 决定 3：当前 OCR 主推 HyperLPR3

决定：

- 当前中文车牌 OCR 主推 HyperLPR3。

原因：

- PaddleOCR 对小而模糊的中文车牌不稳定且速度慢。
- plate-rec 系列曾出现较多泛中文乱码。
- HyperLPR3 当前在项目样本中表现相对最好。

## 决定 4：MIPI 0 字节出帧问题优先按硬件/驱动链路排查

决定：

- 新板 MIPI 不出帧暂不归因于 ALPR 主代码。
- 优先排查硬件连接、sensor、设备树、驱动、供电、接口、IQ/ISP。

原因：

- V4L2/GStreamer 均无法得到非 0 字节图像。
- 内核报 `imx585 2-0010: start stream failed while write regs`。
- 视频文件识别链路在新板上已可运行。

## 决定 5：deblur 暂不直接进入 RK 实时主链路

决定：

- deblur 先在 Windows demo 和离线 Top-K crop 中验证。
- 只有 OCR A/B 收益明确后，才考虑作为 RK 后台补票层。

原因：

- deblur 会占用算力。
- 当前观察为视觉改善部分 crop，但 OCR 增益不稳定。
- RK 实时链路需要优先保证 FPS 和稳定性。

## 决定 6：建立长期项目记忆文件

决定：

- 根目录建立 `AGENTS.md`、`PROJECT.md`、`STATUS.md`、`DECISIONS.md`、`HANDOFF.md`。
- 每完成重要工作，同步更新 `PROJECT.md`、`STATUS.md`、`DECISIONS.md` 和 `HANDOFF.md`。
- 只有工作规则变化时更新 `AGENTS.md`。

原因：

- 项目周期长，涉及 Windows、RK3588、MIPI、OCR、OBB、deblur 和部署包多条线。
- 后续 AI 或人员接手需要稳定的阅读顺序和状态来源。

## 决定 7：先用 SC850SL RAW10 灰度跑通 ALPR 流程

决定：

- 在 RKISP mainpath 输出修复前，先使用 `/dev/video33` 的 SC850SL `BG10` RAW10 原始帧。
- 在 `rk3588_topk_capture.py` 中加入 `--mipi-fourcc BG10`、`--mipi-color-mode raw10-gray`、`--raw10-stride` 支持。
- 灰度帧转 BGR 后复用现有 vehicle RKNN、plate OBB、HyperLPR3、投票和锁定逻辑。

原因：

- `/dev/video33` 已验证可以输出非 0 字节 RAW10 帧，约 30 FPS。
- `/dev/video44` RKISP mainpath 仍报 `check rkisp_mainpath link or isp input`。
- 先跑通识别闭环能尽快验证现场视角、ROI、曝光和模型效果；ISP 链路可作为后续独立问题继续修。

## 决定 8：增加检测前 ROI 裁剪放大

决定：

- 在 `rk3588_topk_capture.py` 中增加 `--detect-roi` 和 `--draw-detect-roi`。
- `--detect-roi` 在 vehicle RKNN 前裁剪远景道路区域，检测框再映射回原始全图坐标。
- `--process-roi` 继续作为检测后的处理过滤，不替代 `--detect-roi`。

原因：

- SC850SL 灰度全图输入已经跑通，但整幅 3840x2160 缩放到 vehicle 模型输入后，车辆太小，低阈值仍 `tracks=0`。
- 检测前裁剪道路区域可以提高车辆在模型输入中的像素占比，同时保留后续全图显示、plate/OCR 和锁定逻辑。

## 决定 9：SC850SL 适配基于 MIPI debug 副本

决定：

- 不直接修改 `rk3588_topk_capture_mipi_debug.py`。
- 复制出 `rk3588_topk_capture_mipi_debug_sc850.py` 作为远程 SC850SL 板子的适配脚本。
- 保留 debug 版已有的 MIPI 低光增强和 plate scan 诊断能力，但最终道路目标仍是车辆 track 绑定。

原因：

- 用户确认 `rk3588_topk_capture_mipi_debug.py` 是更新代码，并且在用户自有 IMX585 板上摄像头可正常识别。
- 远程板与用户板同款，但摄像头模组为 SC850SL，需要独立适配，避免污染 IMX585 可用基线。
- `mipi_plate_scan_*` 来源于早期手机图片测试条件，不代表最终道路识别闭环。

## 决定 10：最终显示目标是车牌跟随车辆

决定：

- 最终输出必须将真实车牌号显示在对应车辆上方。
- 车牌号锁定后应跟随车辆 track，直到 YOLO 检测或预测跟踪都无法继续框住该车辆。
- 直接 plate scan 可作为诊断，但不能替代最终车辆绑定显示目标。

原因：

- 项目目标是道路车辆 ALPR，不是单帧车牌截图识别。
- 板端浏览器画面需要展示“车辆框 + 已锁定车牌号”的连续跟随效果。

## 决定 11：SC850SL 远景灰度先增加检测前分块

决定：

- 在 `rk3588_topk_capture_mipi_debug_sc850.py` 中增加 `--detect-roi-tiles` 和 `--detect-roi-overlap`。
- 默认仍保持单 ROI 行为，只有显式传参时才把检测 ROI 分块后分别送入 vehicle RKNN。
- 日志和预览叠字增加 `vehicle_boxes`，用于判断 vehicle 模型是否真正框到车。

原因：

- 远程实时画面已通，但 1000 帧测试仍为 `tracks=0`、`new_hits=0`。
- 当前问题发生在第一层 vehicle 检测，不是车牌 OBB 或 OCR。
- 单块 4K 远景灰度 ROI 缩放到 640 后车辆仍可能过小；分块能提高车辆在模型输入中的像素占比。

## 决定 12：为 SC850SL 固定机位加入运动目标 fallback

决定：

- 在 `rk3588_topk_capture_mipi_debug_sc850.py` 增加 `--vehicle-source motion|hybrid`。
- `motion` 使用背景差分生成运动车辆候选框，绕过当前不适配 SC850SL 灰度高位视角的 vehicle RKNN。
- 该模式先用于验证运动真车跟踪，真实车辆框稳定后再接 plate OBB/OCR。

原因：

- 白天曝光调到可用后，画面中运动车辆仍显示 `veh:0`，说明当前 `vehicle.rknn` 对该灰度高位视角不可靠。
- 固定摄像头场景下，运动目标检测可以天然过滤静态广告牌/灯箱误检。
- 最终目标是车牌随车显示；只要运动目标框稳定，后续仍可复用现有 plate/OCR/track 逻辑。

## 决定 13：motion 只作为候选源，必须加车辆过滤

决定：

- `--vehicle-source motion` 不视为车辆分类器，只视为固定机位运动候选源。
- 在 `rk3588_topk_capture_mipi_debug_sc850.py` 中增加 `--motion-min-aspect`、`--motion-min-fill-ratio`、`--motion-accept-roi`。
- 远程 SC850SL 测试应先过滤电动车、车轮、行人和非车道运动框，再把候选送入 plate OBB/OCR。

原因：

- 远程实时画面已验证 motion 能框住真实汽车，方向成立。
- 用户观察到 motion 也会框住电动车和车轮，这是背景差分的正常副作用。
- 最终目标是汽车车牌随车显示，不能把所有运动物体都作为车辆 track 进入后续识别。

## 决定 14：以内置场地视频作为板端回归基准

决定：

- 本地 IMX585 RK3588 板继续使用 `/root/deploy/144.mp4` 作为板端视频回归基准。
- 摄像头/MIPI 适配问题和 ALPR 主流程问题分开验证：本地板用内置视频验证主流程，远程 SC850SL 板验证摄像头与灰度实时输入。

原因：

- 用户当前本地环境暂时无法对着马路实测，但已能连接本地 RK3588 板。
- `/root/deploy/144.mp4` 是最终摄像头实测场地的内置视频样本，能验证 vehicle/plate/OCR/投票/锁定/跟随主流程。
- 2026-07-06 回归结果显示 1000 帧约 10 FPS，并锁定 `冀JC5210` 与 `冀B6R9F9`。

## 决定 15：SC850SL 板端主流程已由内置视频排除故障

决定：

- 将“ALPR 主流程是否能在 SC850SL 板上工作”和“SC850SL 实时摄像头输入是否适配”分开判断。
- 远程 SC850SL 板运行同一内置场地视频时表现与本地 IMX585 板一致，说明模型、OCR、投票锁定、叠框显示和浏览器发布链路不是当前主要故障点。
- 后续不要再把实时摄像头下无法稳定框车归因于 SC850SL 板端主流程损坏；应优先排查实时摄像头输入链路、图像域、曝光、ROI 和 RKISP 输出。

原因：

- 用户截图显示 SC850SL 板内置视频测试可正常显示彩色视频，并锁定 `冀JC5210`，表现与 IMX585 内置视频回归一致。
- 同一板端流程在视频文件输入下能锁定车牌，说明失败集中在 `/dev/video33` RAW10 灰度实时输入或 `/dev/video44` ISP 输出未通，而不是 ALPR 核心逻辑。
- 灰度 RAW10 只能作为临时调试通道；最终道路实测更应争取正常 ISP 彩色/YUV 输出，或明确进行面向 SC850SL 灰度域的模型适配。

## 决定 16：SC850SL ISP 输出优先验证 `/dev/video71`

决定：

- 后续 SC850SL ISP 标准输出调试优先测试 `/dev/video71`，而不是继续围绕 `/dev/video44`。
- `/dev/video44` 的失败暂不再作为 SC850SL 4K ISP 链路失败的直接证据。
- `/dev/video53` 虽然也是 ISP mainpath，但在当前证据包中不属于 SC850SL 这条链，只作为对照节点，不作为 SC850SL 主测试节点。
- `RK3588_dev/sc850_isp_probe.sh` 已补充 `/dev/video53`、`/dev/video71` 和 `/dev/video72` 的标准 YUV 短流测试。

原因：

- 用户传回的 `sc850_isp_probe_20250626_124614` 证据包显示，`/dev/video44` 属于 `rkisp0-vir0`，默认/能力仅显示 `800x600`，与 SC850SL 4K 主链路不匹配。
- 同一证据包显示 `/dev/video71` 属于 `rkisp1-vir1` 的 `rkisp_mainpath`，支持 `NV12/UYVY` 等标准 YUV，最高 `3840x2160`。
- media graph 显示 SC850SL 链路为 `m01_b_sc850sl 4-0030` -> `rockchip-csi2-dphy3` -> `rockchip-mipi-csi2` -> `rkcif-mipi-lvds4` -> `rkisp1-vir1` -> `/dev/video71`。
- `/dev/video-camera0 -> video71`，进一步说明系统默认 camera 别名指向 `/dev/video71`。
- `/dev/video53` 的 media graph 为 `rkcif-mipi-lvds2/SRGGB12_1X12` -> `rkisp0-vir2` -> `/dev/video53`，与 SC850SL 的 `rkcif-mipi-lvds4/SBGGR10_1X10` 不一致。

## 决定 17：`/dev/video71` 无帧优先按 rkaiq/IQ 参数问题排查

决定：

- `/dev/video71` 的下一步排查重点从 media node 选择切换到 `rkaiq`/`aiq` 服务、IQ 文件和 ISP 参数注入。
- 在未解决 `first iq setting` 前，不把 `/dev/video71` 的 0 字节结果归因于 ALPR 代码或 vehicle 模型。

原因：

- 用户手动测试 `/dev/video71` 4K `NV12` 时，V4L2 已显示 `VIDIOC_STREAMON returned 0 (Success)`。
- 输出 raw 仍为 0 字节，dmesg 明确报 `rkisp1-vir1: waiting on params stream event timeout` 与 `rkisp1-vir1: can not get first iq setting in stream on`。
- 这类错误指向 ISP 需要的 3A/IQ 参数未及时注入，常见原因是 `rkaiq`/`aiq` 服务未运行、未绑定正确 camera，或 SC850SL IQ 文件未被正确匹配。

## 决定 18：先查 rkaiq media 绑定，再改 ALPR 摄像头代码

决定：

- 当前不继续围绕 ALPR 主脚本修改来解决 `/dev/video71` 0 字节问题。
- 下一步优先检查 `/etc/init.d/rkaiq_3A.sh`、`rkaiq_3A.service` 和 `rkaiq_3A_server` 启动参数，确认 rkaiq 是否绑定到 `/dev/media5` 而不是 SC850SL 所在的 `/dev/media7`。

原因：

- 最新截图确认 `rkaiq_3A.service` 已 active/running，`/usr/bin/rkaiq_3A_server` 进程存在。
- `/etc/iqfiles` 中已存在 `sc850sl_GC_12MM.json` 和 `sc850sl_2L_GC_12MM.json`，因此不能简单判断为 rkaiq 未启动或 IQ 文件缺失。
- service 日志显示 `/dev/media5: wait stream start event...`；而探针包确认 SC850SL 的 ISP mainpath 是 `/dev/media7 -> /dev/video71`。这与 `/dev/video71` 报 `can not get first iq setting` 能互相解释。
- 最新检查显示脚本没有显式指定 `/dev/media5`，而是无参数启动 `rkaiq_3A_server`；同时 fd 中出现 `/dev/v4l-subdev7` 和 `/dev/v4l-subdev8`。因此当前判断从“脚本写死错误 media”修正为“rkaiq 自扫描/多路打开后，实际 stream event 或 first IQ 注入没有落到 `/dev/media7`/`rkisp1-vir1`”，细节待确认。

## 决定 19：SC850SL 实时主输入切换到 `/dev/video71` NV12

决定：

- SC850SL 实时道路测试主输入从 `/dev/video33` RAW10 灰度切换到 `/dev/video71` 标准 ISP `NV12`。
- `/dev/video33` RAW10 灰度保留为临时对照/救生绳，不再作为主路线。

原因：

- `sc850_rkaiq_debug_20250626_142419` 日志包显示 `/dev/video71` 4K `NV12` 取流成功，5 帧约 60 MB，约 30 FPS。
- rkaiq 日志确认 `/dev/media7` stream start/stop event success，dmesg 出现 `rkisp1-vir1: first params buf queue`。
- `/dev/video71` 是 `rkisp1-vir1` 的 `rkisp_mainpath`，比 `/dev/video33` 灰度 RAW10 更接近最终道路实测所需的标准 ISP 输出。

## 决定 20：新对话优先使用完整交接总览

决定：

- 新增 `NEW_CHAT_HANDOFF_20260708.md` 作为新开对话的完整交接总览。
- 新 AI 接手时先读 `AGENTS.md`，再读 `NEW_CHAT_HANDOFF_20260708.md`，然后按需读 `PROJECT.md`、`STATUS.md`、`DECISIONS.md`、`HANDOFF.md` 和相关源码。

原因：

- 本项目已经跨越 Windows 主线、RK3588 视频回归、SC850SL RAW10 灰度、SC850SL ISP `NV12`、实时浏览器发布、vehicle/plate/OCR/跟踪等多条线。
- 单靠聊天记录接手成本太高，且容易重复排查已确认的 `/dev/video71`、`/dev/video44`、`/dev/video53` 结论。
- 完整交接总览能让新对话直接从当前车辆候选质量问题继续推进。

## 待确认

- 用户首次写的 `PR0JECT.md` 是否只是 `PROJECT.md` 的拼写误差。
## 2026-07-10 新对话交接文档

- 决定：新增 `NEW_CHAT_HANDOFF_20260710.md` 作为当前最完整的新对话交接入口。
- 原因：当前任务跨越 Windows 基准、RK 内置视频、远程 SC850SL 实拍、MIPI/ISP/sensor 多轮 probe，仅靠截图或旧 handoff 容易丢失关键判断。
- 限制：该文档是状态总结，不改变既有主线决定；`/dev/video71` 仍是 SC850SL ISP 后处理主端口，当前优先验证 sensor/I2C/出帧恢复。

## 2026-07-10 mediamtx 推流成功后先停流再跑 ALPR

- 决定：当 `/root/mediamtx/start_4_stream.sh` 已经从 `/dev/video71` 成功推出 RTSP 实时道路画面时，不再继续沿“SC850SL 一定离线”旧判断推进；下一步应验证 ALPR 直接采集 `/dev/video71`。
- 决定：运行 `rk3588_topk_capture_mipi_debug_sc850.py` 前，先停止 mediamtx/GStreamer 推流，避免 `/dev/video71` 被占用或时序互相影响。
- 原因：用户截图显示 VLC 已能打开 `rtsp://192.168.8.88:8559/video71`，且 dmesg 出现 `Detected sc850sl id 009d1e`；这证明 sensor/ISP/推流链路至少在当前状态下恢复过。
- 限制：推流成功不等价于 ALPR 已完成识别；仍需先确认 `v4l2-ctl` 单帧 NV12 raw 为 `12441600` bytes，再跑短帧数 ALPR probe。

## 决定 21：Windows 播放与识别解耦，按源 FPS 原速验收

决定：

- Windows 新实时实验使用独立脚本 `alpr_realtime_async.py`，不改基准主线。
- 视频线程按输入源 FPS 原速运行；后台识别只取最新帧，旧帧允许被替换，识别延迟不得累积到播放线程。
- 视频只显示原始画面，识别结果放终端/JSONL；tracking、plate OBB、图片保存等开销均设为可选。
- 当前 `测试图\14.mp4` 的验收基准是源文件 `24 FPS`，不是强制 30 FPS。

原因：

- 原 demo 将读取、车辆 YOLO、OCR、plate OBB、Top-K/诊断复制和窗口刷新串行执行，任何识别重帧都会直接降低播放 FPS。
- 2026-08-05 异步实测在后台识别约 `9.265 FPS` 时，视频仍为 `24.011 FPS`；过期帧替换避免了排队延迟。
- 当前源视频本身只有 24 个独立帧/秒，强制显示 30 FPS只能加速或重复帧，不能作为真实 30 FPS 识别结论。

## 决定 22：暂不直接从 Python 全量迁移 C++

决定：

- 先保留 Python 异步编排，并通过阶段耗时确认模型瓶颈。
- 下一性能路线优先级为：关闭/按需运行 plate OBB、减少车辆候选、降低模型输入、导出 ONNX/OpenVINO 做 CPU A/B，之后才评估 C++ 主程序。
- 只有当 ONNX/OpenVINO 模型确定、Python 调度或数据复制仍占明显比例，或部署环境明确要求原生程序时，再启动 C++ 迁移。

原因：

- 当前环境为 CPU-only；短测中 plate OBB 单帧可达约 `2.9 s`，OCR 约 `0.5 s`，模型推理远大于 Python 控制流开销。
- 单纯把控制代码改写为 C++不会自动消除 YOLO/HyperLPR3 模型计算量，且会增加模型导出、OBB 后处理、OCR 绑定和回归验证成本。

## 决定 23：远端 PLR-Test 只保存轻量主程序核心

决定：

- `gcvision_admin/PLR-Test` 不镜像整个本地工程，只保存 Windows 异步主程序及直接依赖。
- RK 调试脚本、模型、视频、实验输出、证据包和内部交接文档不进入该仓库。
- 远端首个 `main` 提交必须经过语法检查、敏感信息扫描和远端哈希回读验证。

原因：

- 用户明确要求“只上传主程序核心代码，尽可能轻量化”。
- 本地工程包含大量模型、视频、板端证据和历史实验内容，整体上传会增加泄露风险和维护成本。

## 决定 24：HyperLPR3 速度分三层统计，默认阈值降至 0.50

决定：

- 不再用后台整帧耗时代表 HyperLPR3 本身速度；分别记录单次 `ocr_ms`、整帧 `recognition_total_ms` 和端到端 `end_to_end_ms`。
- Windows 异步主程序默认接受阈值设为 `0.50`，同时继续执行车牌格式校验。
- 性能结论使用多次调用的分布，不用单个最快值代表稳定速度。

原因：

- 车辆 YOLO、排队等待和可选 plate OBB 会显著放大最终延迟，必须和 OCR 模型调用分开。
- 用户希望观察 HyperLPR3 毫秒耗时并提高低置信度结果召回；降低阈值会增加错误结果风险，因此保留格式过滤和多帧 `track_id` 诊断。

## 决定 25：HyperLPR3 纯识别模块先离线 A/B，不直接接实时链路

决定：

- 将 `plate_rec_sim.onnx` 与 HyperLPR3 明确区分；前者配套协议未确认，不作为本轮候选。
- 使用 HyperLPR3 自带 `rpv3_mdict_160_r3.onnx` 和官方内部识别类，在现有 OBB 裁正车牌图上做独立离线测试。
- 只有文字质量和性能均通过后，才在异步程序新增 `hyperlpr3-rec` 引擎；当前不接入。

原因：

- 18组完整 A/B 中，纯识别虽然跳过检测和分类，但 `P50=81.616 ms`、`P95=186.169 ms`，推理本身占 `P50=81.184 ms`，远未稳定达到20ms。
- 纯识别合法车牌率和与现有参考结果的一致率不足，不能仅凭单个 `冀B6R9F9` 正确样本替换当前主 OCR。

## 决定 26：车牌专用 PP-OCRv4 先独立训练验收，再考虑替换 HyperLPR3

决定：

- 采用 PP-OCRv4 Mobile 官方结构和预训练权重做车牌专用微调，不从零开始正式训练；100 步随机初始化仅允许作为结构冒烟。
- 模型字典严格复用 HyperLPR3 官方 76 个非 blank 字符并增加一个 CTC blank，总输出 77 类；模型张量统一为 RGB `1x3x48x160`。
- 正式训练必须由数据审计硬门槛阻止不合格数据启动；只有 `source=real_verified` 的人工核验实拍数据进入真实准确率统计。
- Paddle、ONNX/OpenVINO 和 RKNN 必须对同一测试集做文本一致性与量化精度下降检查；未同时通过准确率和双端延迟门槛，不新增实时 OCR engine。

原因：

- HyperLPR3 官方字符表实测为 76 个非 blank 字符，旧方案中的 77/78 类描述与真实协议不符，不能人为补字。
- 100 步 CPU 冒烟已证明数据、训练、checkpoint 和 Paddle 导出链路可运行，但不具备模型质量意义；完整训练需要 GPU、预训练权重和足量人工真值。
- 修正归一化后的通用 `plate_rec_sim.onnx` 仍只有 `P95=79.76 ms`，且样本输出质量明显不满足车牌任务，不能用通用字典模型绕过专用微调。

## 决定 27：已裁正单层车牌优先评估 HyperLPR3 纯识别模块

决定：

- 当上游 plate OBB 已经输出裁正单层车牌时，允许将 `PPRCNNRecognitionORT` 作为速度优先的可选 OCR engine 做真实链路 A/B，不再重复调用完整 HyperLPR3 detector/classifier。
- 当前不直接替换默认 HyperLPR3 公共接口；必须先给实际 OBB crop 配人工真值，验证整牌准确率、双层牌处理、格式过滤和多帧投票。
- 纯识别模块输出应继续记录置信度和阶段耗时；不能把“产生了格式合法文本”视为“识别正确”。

原因：

- 对1041张预裁车牌，完整接口仍漏掉262张，而纯识别全部产生文本；重复检测会增加计算并可能因裁剪过紧而漏检。
- 纯识别实测 `P50=26.034 ms`、`P95=43.254 ms`，相对完整接口分别加速约3.01倍和4.87倍，方向明确，但仍未稳定达到20ms。
- 无人工真值的 `sharp` 目录只能验证延迟和输出行为，不能证明纯识别准确率已通过上线门槛。

## 决定 28：完整 HyperLPR3 性能按条件调用链拆分

决定：

- 完整接口不再只报告一个总毫秒数；固定拆分检测三段、透视拉正、OCR三段、条件颜色分类三段、流水线杂项、结果解析与公共总耗时。
- 对OCR、透视和分类同时报告每张输入摊销与实际调用条件分布；不同分母的P50/P95不得相加，只有各阶段平均贡献可以与平均总耗时闭合。
- “最终无文本”必须继续区分零检测候选和检测后OCR/长度/结果过滤，不能统一称为检测不到。

原因：

- 当前1041张中完整接口空输出262张，但只有216张是零检测候选，另46张已进入OCR后未形成公开结果。
- 每张输入平均耗时中OCR占60.85%、检测占32.68%，真正瓶颈仍是ONNX模型推理，而不是透视、CTC解码或Python结果包装。

## 决定 29：单张OCR诊断严格排除启动与读盘时间

决定：

- 单张纯识别命令分别显示模型加载、图片读取、OCR预处理、ONNX推理、CTC解码和OCR总耗时。
- 模型加载和图片读取不计入OCR总耗时；用户可以通过`--warmup 0`观察冷调用，通过`--warmup 20`观察预热后的单次调用。
- 单次最快值或某次低于20ms不能替代P50/P95稳定性验收。

原因：

- 模型初始化通常超过100ms，但属于进程启动成本；实时程序正常情况下只加载一次模型。
- Windows CPU调度会让单次ONNX推理波动，必须明确冷/热口径并保留批量分布结论。

## 决定 30：Windows Demo 增加 HyperLPR3 纯识别可选引擎

决定：

- 仅在 `alpr_topk_capture_demo.py` 增加 `hyperlpr3-rec`，不替换原 `hyperlpr3`，不修改 `alpr_topk_capture.py`。
- 固定链路为“车辆检测 → 车牌 OBB → 透视裁正 → HyperLPR3 纯识别 → 格式/置信度过滤 → 同车投票”。
- `hyperlpr3-rec` 必须返回 `use_vehicle_first=False`，所有实时 OCR 来源只能是已裁正车牌。
- 无论识别为空、格式非法、置信度不足或抛出异常，每次调用都必须写入 run 级事件；过滤只控制投票，不能控制诊断留存。
- `ocr_ms` 对纯识别引擎只覆盖官方识别器调用，即预处理、ONNX 推理和 CTC 解码，不包含 YOLO、OBB、透视、磁盘、打印或投票。
- 延迟报告使用正常完成调用的 mean/P50/P95/min/max；模型加载只发生一次且不计入 OCR 延迟。
- 第一版不处理双层车牌，也不对纯识别失败自动回退完整接口。

原因：

- 项目已经由 OBB 提供定位和透视裁正，重复运行 HyperLPR3 检测与颜色分类会增加延迟。
- 独立引擎可以与完整接口做可解释 A/B，同时避免改变既有完整接口行为。
- run 级逐次事件可以解决历史上 `recognition_results.jsonl` 缺失或只剩单个结果的问题，并通过 `track_id` 保留同车关系。

## 决定 31：原速观感采用播放与纯识别解耦

决定：

- 完整道路视频不能把“每帧必须识别完”作为播放前提；主线程严格按源视频时间轴显示，后台只消费最新帧。
- 后台识别固定为“车辆定位 → 车牌 OBB → 透视裁正 → HyperLPR3纯识别”，禁止调用 HyperLPR3 检测器、颜色分类器或车辆 crop OCR。
- 后台算力不足时允许覆盖尚未开始的过期帧；不得通过降低播放速度来保证逐帧识别。
- 播放 FPS 与后台识别 FPS 分开显示和汇报；`DROP` 表示为保持原速而覆盖的过期识别帧。
- 原速验收以视频时间轴为准：610帧@24FPS理论25.417秒，实测需接近该值；识别质量和覆盖率另行验收，不能混成同一指标。

原因：

- 本机 CPU 每帧车辆YOLO已经超过24FPS的41.7ms预算，同步处理不可能原速。
- 纯OCR本身已回到约20–35ms，长期播放瓶颈主要是车辆检测；latest-frame结构能保证画面流畅并保留最新识别机会。

## 决定 32：以 2026-08-14 交接文档统一当前全局状态

决定：

- `NEW_CHAT_HANDOFF_20260814.md` 作为新对话的当前全局入口；`NEW_CHAT_HANDOFF_20260717.md` 继续作为 RK/SC850SL 专项历史入口。
- 新接手者必须区分当前 Windows 原速纯识别、长期 RK 道路部署和 PP-OCR 独立训练准备，不能把三条线的验收状态混为一谈。
- 旧文档保留为决策演进记录；其中已被后续证据更新的 sensor、video node、纯识别接入限制和远端版本描述不得继续作为当前事实。

原因：

- 7月17日后新增了 HyperLPR3 完整/纯识别基准、PP-OCR训练工具、demo纯识别和异步原速链路，旧交接已无法覆盖当前全貌。
- 当前工作区和 Gitea 轻量仓库存在版本差异，必须明确本地源码与实际运行产物优先，避免新对话使用旧发布快照继续开发。

## 决定 33：GitHub 发布采用白名单同步，不做目录镜像

决定：

- 使用 `release_manifest.txt` 明确可从完整项目同步到 `codex/github-release` 的一方源码、配置和文档。
- 使用 `tools/sync_github_release.py` 执行批量同步；默认只预览，显式 `--apply` 才写入。
- 写入前必须确认发布 worktree 分支正确且工作区干净；同步只新增/更新，不删除目标文件，也不自动暂存、提交或推送。
- 同步阶段继续执行 95 MiB 硬上限、禁止目录/类型和常见敏感信息检查；发布分支已有 pre-commit、pre-push 和 GitHub Actions 作为后续保护。

原因：

- 完整项目混有模型、数据集、视频、依赖副本、第三方源码和大量实验结果，按扩展名或整目录复制容易污染发布历史。
- 版本化白名单能一次同步多份核心代码，同时让新增发布范围经过明确审查；不自动提交和推送可让用户在 VS Code 中最后检查差异。
- 独立 worktree 保持本地完整 `main` 和 GitHub 干净发布历史互不覆盖。
