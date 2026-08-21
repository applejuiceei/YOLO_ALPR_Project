# 项目目标与验收

更新时间：2026-08-14

文件名说明：用户首次提到 `PR0JECT.md`，后续明确要求更新 `PROJECT.md`。当前按 `PROJECT.md` 建档；是否还需要额外创建 `PR0JECT.md` 待确认。

## 项目目标

在高速路固定摄像头场景下，尽可能接近原视频速度完成中文车牌识别，并最终部署到 RK3588 板端进行实地道路测试。

理想流程：

1. 从固定摄像头或视频流中检测车辆。
2. 对车辆区域内车牌进行 OBB 检测。
3. 对车牌进行透视拉正，得到 `320x96` plate crop。
4. 调用 OCR 识别真实车牌号。
5. 对同一辆车多帧 OCR 结果进行投票。
6. 投票锁定后，后续不再对该 track 做 OBB/OCR，只继续跟踪车辆并显示锁定车牌号。
7. RK 板端实时输出画面到 `/tmp/frame.jpg`，由浏览器流服务展示。

一句话目标：

> 锁定前识别，锁定后不再识别，只跟踪车辆并持续显示已锁定真实车牌号。

更具体的板端显示目标：

> 识别出的真实车牌号必须显示在对应车辆上方，并跟随该车辆，直到 YOLO 或预测跟踪都无法继续框住它。

## 当前需求

- 2026-07-08 新增 `NEW_CHAT_HANDOFF_20260708.md`，作为新开对话时的完整接手总览，集中记录项目目标、当前结论、关键脚本、测试结果、文件结构和已做尝试。
- Windows 端保持 Top-K + HyperLPR3 主线稳定，作为行为基准。
- RK3588 端保持视频文件识别链路可运行。
- 修通新线下测试板 MIPI 摄像头真实出帧。
- 在 RKISP 输出链路修复前，先用 SC850SL `/dev/video33` BG10 RAW10 灰度输入跑通 ALPR 识别流程。
- 2026-07-06 已确认远程 SC850SL 板运行同一内置场地视频时，表现与本地 IMX585 板一致，能正常锁定车牌；因此实时摄像头问题不再归因于板端 ALPR 主流程损坏。
- SC850SL `/dev/video33` BG10 RAW10 灰度输入只作为临时调试/救生绳；最终道路实测应优先获得正常 ISP 彩色/YUV 输出，或在无法修通 ISP 时再评估灰度域模型适配。
- 2026-07-06 已分析远程 SC850SL 探针包，当前判断 `/dev/video44` 属于另一条 `rkisp0-vir0` 链路，不能再作为 SC850SL 4K ISP 主输出的判断依据。探针包中 `/dev/video53` 确实是 ISP mainpath，但它上游为 `rkcif-mipi-lvds2/SRGGB12_1X12`，不是已确认的 SC850SL `rkcif-mipi-lvds4/SBGGR10_1X10` 链；SC850SL 对应的 ISP mainpath 是 `/dev/video71`，并且 `/dev/video-camera0 -> video71`。
- 2026-07-06 已确认 `rkaiq_3A.service` 正在运行，且 `/etc/iqfiles` 下存在 `sc850sl_GC_12MM.json` 与 `sc850sl_2L_GC_12MM.json`；随后通过 `sc850_rkaiq_debug_20250626_142419` 日志包确认 `/dev/video71` 的 4K `NV12` 已可连续出帧，5 帧约 60 MB，约 30 FPS，rkaiq 对 `/dev/media7` 收到 stream start/stop event。SC850SL 标准 ISP 输出链路已从“待确认”推进为“已通”，下一步应切换实时 ALPR 输入到 `/dev/video71`。
- 针对高位远景画面，支持检测前 ROI 裁剪放大，避免整幅 4K 缩放后车辆过小导致 `tracks=0`。
- 针对远程 SC850SL 灰度高位视角，支持检测前 ROI 分块，避免单块 ROI 缩放后车辆仍过小。
- 分块 ROI 已让模型输出 boxes，但低阈值下主要是假阳性；当前需要先让 vehicle 检测框住真实车辆，再验证 plate OBB 在 SC850SL 灰度/夜间车辆 crop 上的命中能力。
- 由于 SC850SL 灰度高位视角下 RKNN vehicle 仍无法稳定框住运动真车，新增固定机位运动目标 fallback，先以运动框验证车辆跟踪闭环。
- 固定机位运动目标 fallback 已能框到真实汽车，但会同时框到电动车、车轮等非汽车运动目标；需要使用运动框尺寸、长宽比、填充率和车道 ROI 过滤后，再进入 plate OBB/OCR。
- 以 `rk3588_topk_capture_mipi_debug.py` 为摄像头调试参考，但不直接污染；SC850SL 适配放在副本 `rk3588_topk_capture_mipi_debug_sc850.py`。
- MIPI 出图后进行道路实测，记录 FPS、vehicle hits、plate hits、locked_text 和错误样本。
- 将 `best_obb_finetuned_e20.pt` 转为 RKNN 并与当前 `best_obb.rknn` 做 A/B，待执行。
- deblur 先做 Windows demo 和离线 crop A/B，收益明确前不进入 RK 实时主链路。

## 验收标准

### Windows 基准链路

- 能对 `D:\YOLO_ALPR_Project\测试图\14.mp4` 跑完整 Top-K 流程。
- 能输出每个 track 的 summary、candidate crops、rejected 样本和 OCR vote history。
- 能使用 HyperLPR3 输出真实车牌号并完成投票锁定。

### RK 视频自测链路

- `/root/deploy/144.mp4` 能在 RK3588 上跑通。
- `/root/deploy/144.mp4` 作为最终实测场地视角的内置视频回归样本；2026-07-06 本地 IMX585 板 1000 帧回归已锁定 `冀JC5210` 和 `冀B6R9F9`。
- 2026-07-06 远程 SC850SL 板运行同一内置视频时，识别表现与 IMX585 板一致，并锁定 `冀JC5210`。
- RKNN vehicle 和 plate OBB 模型能加载运行。
- HyperLPR3 能导入并执行。
- 至少跑到 frame 1000。
- run 目录中保存完整结果。

### 新板 MIPI 链路

- `v4l2-ctl` 或 `gst-launch` 能生成非 0 字节 jpg/raw。
- 浏览器能看到新板真实摄像头画面。
- `rk3588_topk_capture.py` 能持续处理 MIPI 帧。
- 短期允许使用 `/dev/video33` BG10 RAW10 灰度转 BGR 输入做调试；长期仍以 RKISP 输出 UYVY/NV12 或等价标准彩色/YUV 输入为目标。
- 当前优先验证 `/dev/video71` 是否能输出 SC850SL 的 `NV12/UYVY` ISP 帧；如可用，应替代 `/dev/video33` 灰度临时链路进入实时道路 ALPR。`/dev/video53` 只能作为“另一路 ISP mainpath”候选观察，不能直接当作 SC850SL 输出。
- `/dev/video71` 已确认可输出 3840x2160 `NV12`，下一步验收重点从“修通 ISP 出帧”转为“确认 ISP 画面质量，并让实时 ALPR 使用 `/dev/video71` 标准 YUV 输入跑道路测试”。
- 短期灰度链路应支持 `--detect-roi` 和必要时的 `--detect-roi-tiles`，在 vehicle RKNN 前裁剪/分块道路区域，并将检测框映射回原始全图坐标。
- 短期 motion 链路应支持过滤非汽车运动物体，包括电动车、车轮、行人或非车道区域运动目标，避免把这些框送入车牌识别阶段。

### 道路实测

- 使用真实道路车辆输入。
- 保存完整 run 目录。
- 记录 FPS、车辆检测、车牌命中、OCR 投票、锁定文本和失败样本。

## 不能修改或需谨慎修改的内容

- `alpr_topk_capture.py`：Windows 基准主线，不要随意修改。
- `rk3588_topk_capture_mipi_debug.py`：当前 MIPI 摄像头调试参考脚本，不直接改；适配实验应复制副本。
- `PROJECT_HANDOFF.md`：历史交接文档，除非用户要求，不作为日常状态文件改写。
- 已有实验输出目录：不要删除或覆盖。
- RK 离线部署包：不要无说明地替换。
- 当前板端主 OCR 选择 HyperLPR3，不要未经 A/B 就切换主 OCR。

## 待确认

- 是否需要同时创建兼容文件名 `PR0JECT.md`。
- 新线下测试板 MIPI 摄像头硬件、设备树、驱动和 IQ 文件的现场确认结果。
- `best_obb_finetuned_e20.pt` 转 RKNN 的最终转换参数和量化策略。
## 2026-07-10 交接入口

- 新增 `NEW_CHAT_HANDOFF_20260710.md` 作为当前项目的新对话完整交接文档。
- 该文档不改变项目目标：最终仍是在远程 RK3588 板上通过 SC850SL `/dev/video71` NV12 实时道路画面完成车辆和车牌识别。
- 当前主卡点仍是 SC850SL sensor/I2C/ISP 出帧链路恢复，而不是 Windows 基准或 RK 内置视频识别主流程。

## 2026-07-10 最新验证补充

- 用户已通过板端 mediamtx/GStreamer 从 `/dev/video71` 成功推出实时道路 RTSP 画面，说明远程 SC850SL 链路已从“sensor 未上线”推进到“需要验证 ALPR 直接采集 `/dev/video71`”。
- 远程 SC850SL 最终目标不变：仍需使用 `rk3588_topk_capture_mipi_debug_sc850.py` 在 `/dev/video71` NV12 实时画面上完成车辆检测、车牌 OBB、HyperLPR3 OCR、投票锁定和随车显示。
- 用户本地 IMX585 RK3588 板 2026-07-10 内置视频 1000 帧回归通过，继续作为板端主流程可用性的参考基准。

## 2026-08-05 Windows 原速播放与后台识别目标

- 新增 Windows 实时实验链路 `alpr_realtime_async.py`，不修改基准主线 `alpr_topk_capture.py`。
- 视频读取/原始画面播放必须与车辆检测、车牌 OBB、OCR 解耦；识别慢时只替换尚未处理的旧帧，不允许识别队列反向拖慢视频。
- 默认以输入源声明的 FPS 原速播放。当前 `测试图\14.mp4` 为 `1920x1080 @ 24 FPS`，验收目标是约 24 FPS，不通过加速或重复帧伪造 30 FPS。
- 识别结果只需输出到终端和 JSONL，不在视频中画框或显示文字。
- 必须保留运行期开关：窗口模式按 `R` 开始/暂停识别；也支持按帧自动开始/停止和 `on/off/quit` 控制文件。
- tracking、plate OBB、结果文件保存均可关闭；默认不保存图片、不保存 rejected、不跑 deblur。

### Windows 异步实时链路验收

- 识别开启时，视频循环仍接近输入源 FPS，且统计视频 FPS 与后台识别 FPS。
- 后台只处理最新帧，并统计被替换的过期帧数量，避免延迟持续累积。
- `--tracking none` 和 `--plate-stage off` 可作为速度优先模式；`--plate-stage fallback`/`always` 作为更重的识别模式。
- HyperLPR3 输出的真实车牌结果写入 `recognition_results.jsonl`；`ocr-engine none` 仅允许做诊断/性能测试。
- 是否迁移 C++ 由分阶段耗时基准决定；在模型推理占主导时，不以语言迁移代替模型/推理后端优化。

## 2026-08-06 核心源码发布范围

- Gitea `gcvision_admin/PLR-Test` 只发布 Windows 当前异步主程序及其直接依赖，保持轻量。
- 不上传模型权重、测试视频、运行结果、RK 实验包、离线依赖、内部项目记忆或登录凭据。
- 远端源码应包含最小运行说明、依赖清单和忽略规则；凭据只用于推送，不得写入仓库。

## 2026-08-07 HyperLPR3 延迟观测

- Windows 异步主程序对每条有效结果记录单次 OCR `ocr_ms`、后台整帧 `recognition_total_ms` 和提交到完成 `end_to_end_ms`。
- 终端用 `[OCR_SPEED]` 直接显示上述耗时；`summary.json` 记录 `ocr_calls`、`average_ocr_ms` 和累计 OCR 时间。
- 默认有效 OCR 置信度阈值调整为 `0.50`，但车牌格式校验仍保留；降低阈值可能增加错误车牌结果，需结合 `track_id` 多帧结果判断。

## 2026-08-07 HyperLPR3 纯识别模块离线 A/B

- `plate_rec_sim.onnx` 是独立车牌识别模型，不属于 HyperLPR3；在配套字典/解码未确认前，不用于正式识别结论。
- HyperLPR3 纯识别试验使用其自带 `rpv3_mdict_160_r3.onnx` 和官方 `PPRCNNRecognitionORT`，输入必须是 OBB 透视裁正后的车牌图。
- 本阶段只允许独立离线 A/B，不修改 `alpr_topk_capture.py`、`alpr_topk_capture_demo.py` 或实时主程序；准确率通过后再考虑新增实时 OCR engine。
- 性能验收同时报告 P50/P95，并拆分预处理、ONNX 推理和 CTC 解码；`summary.json` 旧 OCR 仅作参考，不作为人工真值。

## 2026-08-08 车牌专用 PP-OCRv4 Mobile 目标

- 新训练与部署代码统一放在独立目录 `ppocr_plate`，不得在质量和双端性能门槛通过前接入 Windows 或 RK3588 实时主线。
- 第一版仅覆盖裁正后的单层 7/8 位中文车牌；对外输入为 OpenCV BGR crop，模型固定输入为 RGB `float32 [1,3,48,160]`，输出为 CTC 时间步分数。
- HyperLPR3 官方字符表实际为 `76` 个非 blank 字符，新模型采用相同 76 字符加 CTC blank，共 `77` 类；不得为迎合旧描述自行增加不存在的字符。
- 正式训练只允许在不少于 10 万张公开/合成训练样本、人工核验实拍 2000/500/500、无车辆组泄漏且许可证审查通过后开始；历史 summary 与旧 OCR 只能辅助标注，不能进入准确率门槛。
- 晋级条件保持不变：实拍整牌准确率不低于 98%、字符准确率不低于 99.5%、INT8 整牌准确率下降不超过 0.5 个百分点，Windows CPU 和 RK3588 均需预热 50 次后连续 1000 次端到端 OCR `P95 < 20 ms`。
- 当前只完成 100 步 CPU 结构冒烟和 Paddle 固定形状导出，不代表正式模型训练或准确率达标；正式微调仍需经审计数据、官方预训练权重和 GPU 环境。

## 2026-08-11 HyperLPR3 清晰车牌 crop 速度基准

- 对已经由 plate OBB 检测并透视拉正的单层车牌 crop，性能结论必须区分完整 `LicensePlateCatcher` 公共接口和内部 `PPRCNNRecognitionORT` 纯识别模块。
- 基准输入为 `Dataset/dataset/test/sharp` 的 1041 张 350×150 JPG；全部可解码，预先载入内存，batch=1、单并发、每路预热50次，磁盘读取不计时。
- 纯识别模块是已裁正车牌的速度优先候选，但只能作为可选引擎先做带人工真值的实际 OBB crop A/B；不得仅凭格式合法率或高置信度直接替换当前主 OCR。
- 纯识别模块仍需保留格式校验、置信度阈值和多帧投票；双层车牌没有 detector 的 `layer_num` 与拆分逻辑，必须另行处理。
- 完整接口分阶段性能必须覆盖检测预处理/推理/后处理、透视拉正、OCR预处理/推理/CTC解码、条件颜色分类、流水线杂项、适配器解析和公共调用总耗时。
- OCR和颜色分类属于条件阶段；报告必须同时给出“每张输入摊销（未调用记0）”和“阶段实际调用时”两种分母，禁止直接相加不同条件分布的P50/P95。
- 提供单张车牌纯识别诊断入口，必须把模型加载、图片读取和OCR调用分开计时；OCR调用继续拆分预处理、ONNX推理和CTC解码，避免把启动成本误认为识别耗时。

## 2026-08-12 Windows Demo 接入 HyperLPR3 纯识别

- `alpr_topk_capture_demo.py` 新增可选引擎 `hyperlpr3-rec`，保留车辆检测与车牌 OBB；仅把 OBB 透视裁正后的 `320×96` BGR 车牌图送入 `rpv3_mdict_160_r3.onnx`。
- `hyperlpr3-rec` 不运行 HyperLPR3 自带检测器和颜色分类器，也不把车辆 crop 送入 OCR；原 `hyperlpr3` 完整接口语义保持不变。
- 每次实际 OCR 调用均先进入内存事件列表，退出时写入 run 根目录的 `recognition_results.jsonl`；事件包含帧号、`track_id`、来源、文字、置信度、纯 OCR 耗时、过滤结果和是否进入投票。
- `run_summary.json` 保存 OCR 调用/成功/错误数量，以及 mean、P50、P95、min、max；异常调用不进入延迟分布。
- 第一版纯识别仅保证已拉正单层车牌；双层车牌继续使用完整 `hyperlpr3`，不做长宽比猜测、自动拆行或自动回退。
- Windows 基准主线 `alpr_topk_capture.py` 未修改。

## 2026-08-14 全局新对话交接入口

- 新增 `NEW_CHAT_HANDOFF_20260814.md`，作为当前全局最新的新对话接手入口。
- 该文档同时区分三条工作线：Windows 原速 HyperLPR3 纯识别、RK3588 + SC850SL 长期道路部署、PP-OCRv4 Mobile 独立训练准备。
- 新文档以当前源码和正式运行产物为依据，明确标记旧文档中已经过时的 sensor、`/dev/video53`、纯识别只限离线和远端源码版本等结论。
- 新对话应先读 `AGENTS.md`，再读 `NEW_CHAT_HANDOFF_20260814.md`；需要继续 RK 专项时再读 `NEW_CHAT_HANDOFF_20260717.md`。

## 2026-08-15 GitHub 灾难恢复发布目标

- 原项目 `D:\YOLO_ALPR_Project` 继续作为完整开发和本地存档工作区；模型、数据、视频、运行结果不迁入 GitHub 源码发布线。
- `D:\YOLO_ALPR_Project_GitHubRelease` 作为 `codex/github-release` 的独立 worktree，只接收白名单内的一方源码、配置和文档。
- `release_manifest.txt` 是批量发布范围的版本化白名单；`tools/sync_github_release.py` 负责预览和同步。
- 日常同步命令为 `python .\tools\sync_github_release.py --apply`。同步只新增或更新文件，不删除、不暂存、不提交、不推送，并继续执行 95 MiB 与敏感信息保护。
