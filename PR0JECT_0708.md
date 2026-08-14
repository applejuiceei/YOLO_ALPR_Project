# 项目目标与验收

更新时间：2026-07-08

本文件记录项目目标、当前需求、验收标准和不能随便修改的内容。信息不确定时统一标注“待确认”。

## 项目目标

在 RK3588 板端接入真实道路摄像头，实现固定机位中文车牌识别，并最终在远程电脑连接的 SC850SL 摄像头上达到实时道路识别效果。

理想流程：

1. 从固定摄像头或视频流中检测车辆。
2. 对车辆区域内车牌进行 OBB 检测。
3. 对车牌进行透视拉正，得到 `320x96` plate crop。
4. 调用 HyperLPR3 OCR 识别真实车牌号。
5. 对同一辆车多帧 OCR 结果进行投票。
6. 投票锁定后，后续不再对该 track 重复做 OBB/OCR，只继续跟踪车辆并显示锁定车牌号。
7. RK 板端实时输出叠框画面到 `/tmp/frame.jpg`，由浏览器服务展示。

一句话目标：

> 锁定前识别，锁定后不再识别，只跟踪车辆并持续显示已锁定真实车牌号。

更具体的最终显示目标：

> 真实车牌号必须显示在对应车辆上方，并跟随该车辆，直到 YOLO 检测或预测跟踪都无法继续框住它。

## 当前需求

- Windows `alpr_topk_capture.py` 保持 Top-K + HyperLPR3 行为基准。
- 本地 IMX585 RK3588 板用内置视频和 `rk3588_topk_capture_mipi_debug.py` 验证板端主流程。
- 远程 SC850SL RK3588 板使用后补脚本 `rk3588_topk_capture_mipi_debug_sc850.py` 继续推进真实摄像头道路识别。
- 远程 SC850SL 主输入应使用 `/dev/video71` 标准 ISP `NV12`，而不是把 `/dev/video33` RAW10 灰度作为最终主线。
- 先把实时道路画面中的汽车框调稳定，再接车牌 OBB/OCR。
- 每轮道路实测都要保存完整 run 目录，查看 `run_summary.json`、track `summary.json`、candidate crops、rejected 样本和 vote history。
- 2026-07-08 已确认远程 SC850SL `/dev/video71` NV12 出帧、rkaiq/media7、`/tmp/frame.jpg` 刷新和 vehicle RKNN 起量均正常；当前需求推进为放行车辆候选进入 plate OBB，分析车牌检测命中和误检结构。

## 验收标准

### Windows 基准链路

- 能对 `D:\YOLO_ALPR_Project\测试图\14.mp4` 跑完整 Top-K 流程。
- 能输出每个 track 的 summary、candidate crops、rejected 样本和 OCR vote history。
- 能使用 HyperLPR3 输出真实车牌号并完成投票锁定。

### 本地 IMX585 板端链路

- `/root/deploy/144.mp4` 能在 RK3588 上跑通。
- 使用 `rk3588_topk_capture_mipi_debug.py` 至少跑到 frame 1000。
- RKNN vehicle 和 plate OBB 模型能加载运行。
- HyperLPR3 能导入并执行。
- run 目录中保存完整结果。

### 远程 SC850SL 实时道路链路

- 使用 `rk3588_topk_capture_mipi_debug_sc850.py`。
- 摄像头主输入使用 `/dev/video71`、`NV12`、3840x2160。
- `/tmp/frame.jpg` 能持续刷新，且不能只凭旧帧判断程序正在运行。
- 实时道路画面中汽车框能稳定框住真实汽车，并尽量过滤电动车、车轮、行人和非目标区域。
- 汽车框稳定后，能触发 plate OBB、HyperLPR3 OCR、投票锁定。
- 当前下一阶段验收重点：在 `/dev/video71` NV12 下，使用 `MIN_PROCESS_VEHICLE_CONF=0.12` 或相近值，让候选进入 plate OBB，记录 `plate_attempts`、accepted/rejected、rejected reason 和预览图。
- 锁定的真实车牌号能显示在对应车辆上方并跟随车辆。
- 保存完整 run 目录，记录 FPS、vehicle hits、plate hits、OCR 投票、locked_text 和失败样本。

## 不能修改或需谨慎修改的内容

- `alpr_topk_capture.py`：Windows 基准主线，不要随意修改。
- `rk3588_topk_capture_mipi_debug.py`：本地 IMX585/MIPI 调试参考脚本，不直接污染。
- `rk3588_topk_capture_mipi_debug_sc850.py`：远程 SC850SL 适配主脚本，SC850SL 改动优先放这里。
- 已有实验输出目录：不要删除或覆盖。
- RK 离线部署包：不要无说明替换。
- 当前 OCR 主推 HyperLPR3，不要未经 A/B 就切换主 OCR。
- deblur 不经 Windows demo/离线 crop A/B 验证，不接入 RK 实时主链路。

## 待确认

- 当前 Codex 所在机器是否能直连远程 SC850SL 板 `192.168.8.88`。
- 远程 SC850SL 板上 `rk3588_topk_capture_mipi_debug_sc850.py` 的实际版本是否与项目根目录版本一致。
- 远程 SC850SL 当前日间/夜间最合适的 exposure、ROI 和 vehicle 阈值。
- `best_obb_finetuned_e20.pt` 转 RKNN 的最终转换参数和量化策略。

## 2026-07-08 当前阶段验收补充

- 远程 SC850SL `/dev/video71` NV12 已确认能出正常道路彩色帧，并能驱动车辆 RKNN 和 plate OBB。
- `OCR_ENGINE=none` 阶段的 `PLATE`/`LOCK PLATE` 只能作为候选诊断，不满足真实识别验收。
- 下一阶段验收应以 HyperLPR3 真实文本、vote history、`locked_text`、对应车辆位置和随车显示为准。
- 对 SC850SL 的候选过滤要同时覆盖三类问题：真实车牌保留、路面箭头/标线误候选抑制、公交广告字/车身文字误候选抑制。
- `sc850_video71_vehicle_probe_20250626_144216.tar.gz` 中已出现 HyperLPR3 锁定日志 `苏E8H8R5`，但因缺少完整 run summary/crop，仍不满足最终验收。
- 下一阶段最小验收闭环是：短帧数运行也能保存完整 `run_summary.json`、Top-K crop、vote history，并能确认 locked_text 对应真实车牌。
- `sc850_video71_vehicle_probe_20250626_150317.tar.gz` 已满足“完整 run 目录保存”要求，但未出现 `locked_text`；该阶段证明了车牌定位和 OCR 调用可用，同时暴露 OCR 文本漂移导致锁定不足。
- 后续验收需要在 SC850SL 实时画面中稳定得到 `locked_text`，并通过 crop/summary 确认该文本对应真实车牌，而不是只依赖浏览器显示。
- `sc850_video71_vehicle_probe_20250626_103725.tar.gz` 已验证高质量单帧参数可运行并完整保存结果，但该轮无 OCR vote，因此仍未满足锁定验收。
- 当前验收前置条件应补充为：测试时间段需要有足够近、足够清晰的车辆车牌进入 ROI，否则无法评价 OCR 锁定策略。
- `sc850_video71_vehicle_probe_20250626_110254.tar.gz` 已验证 300 帧高质量单帧实验能产生 OCR vote，并能通过质量门槛挡住低质量结果；下一步验收重点是降低最小车辆锁定置信后能否锁住较可信真牌。
- `sc850_video71_vehicle_probe_20250626_112854.tar.gz` 验证了 `MIN_LOCK_VEHICLE_CONF=0.75` 可运行且不会误锁低质量 vote；但仍未达到真实车牌锁定验收。
- 后续若仅靠阈值实验无法稳定锁定，应进入代码级策略：车牌格式校验、字符级聚类、后缀稳定投票和同车 track 重关联。

## 2026-07-09 SC850SL 代码级策略补充

当前 SC850SL `/dev/video71` NV12 实时道路链路已经进入“真实 OCR 锁牌策略”阶段，不再停留在相机出帧、车辆框或 `OCR_ENGINE=none` 的占位诊断阶段。

新增阶段目标：
- 在 `rk3588_topk_capture_mipi_debug_sc850.py` 内保护真实锁牌逻辑，避免把格式明显可疑的 OCR 文本锁成最终车牌。
- 在启用格式保护后，再小幅试探候选质量阈值，让类似 `苏E69T60`、`粤E2KPA8` 这类结构合理的单帧高质量候选有机会锁定。
- 最终仍以真实 `locked_text` 显示在对应车辆上方并跟随车辆为验收标准；`LOCK PLATE`、`PLATE` 或格式可疑文本不算验收完成。

新增不能随便改的内容：
- `--strict-plate-format` 是 SC850SL 锁牌保护开关，默认关闭以兼容旧行为；远程道路实测需要显式用 `STRICT_PLATE_FORMAT=1` 打开。
- 不要在没有格式过滤的情况下继续降低 `MIN_LOCK_CANDIDATE_SCORE`、`MIN_LOCK_OBB_CONF` 或 `MIN_OCR_CONF`。
- 格式过滤只解决“明显非法文本进入投票”的问题，不能替代 crop 复核；锁到真实文本后仍必须检查对应 track 的 vehicle/plate crop。

## 2026-07-09 SC850SL 出帧前置验收补充

在继续验证 `--strict-plate-format` 和锁牌阈值前，远程 SC850SL `/dev/video71` 必须先恢复稳定出帧：
- 单帧 NV12 raw 大小应为 `3840 * 2160 * 3 / 2 = 12441600` 字节。
- `/tmp/frame.jpg` 的 mtime 和 MD5 必须随程序运行变化，不能用旧帧判断程序仍在运行。
- 若 `video71_1f_nv12.raw` 为 `0` 字节，当前验收对象回到相机/ISP/MIPI 流状态，不进入 OCR 或投票策略验收。

## 2026-07-09 SC850SL 传感器注册前置验收补充

在 `/dev/video71` 出帧验收之前，还必须确认 SC850SL 已作为有效 terminal sensor 注册进 media graph：
- dmesg 中不能再出现当前阻断级别的 `sc850sl 4-0030: Unexpected sensor id(000000)`。
- `rkcif-mipi-lvds4` 不应继续报 `get remote terminal sensor failed` 或 `There is not terminal subdev, not synchronized with ISP`。
- `/dev/media7` 应恢复为 SC850SL 4K RAW10 输入到 `rkisp1-vir1`/`rkisp_mainpath`，而不是 `SRGGB8_1X8/800x600` 的无上游输入状态。
- 在这些条件恢复前，完整 ALPR、OCR、投票锁牌和阈值调参都不作为有效验收。

补充前置条件：
- SC850SL 所在 I2C 总线上的 `0x30` 必须能响应，不能只看 `/sys/bus/i2c/devices/4-0030` 等设备树实例是否存在。
- 如果 `i2cdetect` 看不到 `0x30`，则当前验收对象是模组上电、复位、排线、I2C 和设备树/驱动匹配，不是 `/dev/video71` 或 ALPR。

## 2026-07-09 mediamtx 验收补充

- `/root/mediamtx` 只能作为 `/dev/video71` 当前是否可被 GStreamer 推流的辅助验证。
- `mediamtx_live_probe_20250626_090155.tar.gz` 中实时推流失败，`rtsp_pull_8s.h264` 为 0 字节，因此不能把历史 `gst_push.log` 的成功记录当作当前摄像头正常。
- 在 SC850SL I2C/media graph 恢复前，mediamtx 成功历史不满足实时道路识别前置验收。
## 2026-07-09 当前文件版本约束补充

- 远端 SC850 板端当前 `rk3588_topk_capture_mipi_debug_sc850.py` 与本地当前文件一致。
- 远端 SC850 板端当前 `sc850_video71_vehicle_probe_collect.sh` 与本地当前文件一致。
- 当前未找到可直接原样恢复的 SC850 专用旧版脚本。
- 本地离线包 `rk3588_alpr_roadtest_bundle_20260701` 只包含通用 RK3588 脚本，不包含 SC850 专用旧版。
- 因此后续如需“改回去试试”，只能做备份后的旧行为验证，不能直接覆盖为未经确认的版本。
## 2026-07-09 输入节点待重新确认

- 旧行为短测确认 `/dev/video71` 当前不能作为有效实时输入：单帧 raw 为 0，streamon 返回 `Operation not permitted`，ALPR `frames_processed=0`。
- 当前发现 `/dev/video-camera0` 指向 `/dev/video53`，不是 `/dev/video71`。
- `/dev/video53` 是否就是远端 SC850SL 实际道路摄像头输出仍待确认。
- 在确认实际可出帧节点前，验收目标仍是“远程 SC850SL 摄像头道路识别”，但具体 video 节点暂标记为待确认，不再无条件假设 `/dev/video71` 当前有效。
## 2026-07-09 `/dev/video71` 主线约束确认

- 用户确认远程 SC850SL 的 ISP 后端目标端口就是 `/dev/video71`。
- `/dev/video71` 仍是最终实时道路识别验收端口。
- `/dev/video53` 不作为替代主线；如后续检查，只能作为旁路对照。
- 当前问题表述修正为：目标端口 `/dev/video71` 存在，但其上游 SC850SL/media graph/ISP input 当前未恢复为有效 4K NV12 出帧状态。
## 2026-07-09 当前主卡点更新

- `/dev/video71` 仍是远程 SC850SL 的 ISP 后端目标端口。
- 当前主卡点不是识别算法，而是 `/dev/video71` 上游 SC850SL sensor/I2C/media graph 未形成有效输入。
- 关键证据：`sc850sl 4-0030` sensor id 为 `000000`，`0x30` I2C 无响应，`rkcif-mipi-lvds4` 找不到 terminal sensor，`media7/rkisp1-vir1` 退回 800x600 默认状态。
- 在 SC850SL terminal sensor 和 `/dev/video71` 有效出帧恢复前，不进入最终识别验收调参。
## 2026-07-09 硬件链路排查约束补充

- SC850SL 设备树节点和 driver binding 已存在，但 sensor id 仍读为 `000000`。
- 当前高优先级疑点包括：SC850SL reset GPIO 状态、模组供电、缺失 power-gpios/dvdd/dovdd/avdd 绑定、I2C 物理链路或模组连接。
- 在确认 reset/power/I2C 前，不能把问题重新归因到 ALPR 代码。
- 对 reset GPIO、driver unbind/bind、设备树 overlay 等会改变硬件状态的动作，必须先征得确认。
## 2026-07-09 SC850SL deep DT/phandle 探针补充

- `sc850_deep_dt_phandle_probe_20250626_095747.tar.gz` 显示 `sc850sl-4@30` 设备树节点存在，`compatible=smartsens,sc850sl`，位于 `i2c@feac0000`，`reg=0x30`，endpoint 为 4 lane。
- `sc850sl-4@30` 的 endpoint phandle 为 `0x37`，remote-endpoint 为 `0x15f`；`0x15f` 对应 `csi2-dphy3/ports/port@0/endpoint@1`，且反向 remote-endpoint 指回 `0x37`。因此当前不优先判断为 SC850SL-4 到 csi2-dphy3 的 endpoint 描述完全缺失。
- `pinctrl-0=0x15e` 对应 `mipim0-camera2-clk`；`reset-gpios=<0x129 7 1>` 对应 gpio1 控制器 offset 7，dmesg 解析为 `gpio-39 (reset)`。
- `feac0000.i2c` 当前 pinctrl 为 `i2c4m3-xfer`，说明 I2C4 控制器的 pinmux 描述存在。
- 但 bus4/bus5/bus7 的 `i2cdetect` 仍看不到 `0x30`，dmesg 仍为 `sc850sl 4-0030: Unexpected sensor id(000000)`，`rkcif-mipi-lvds4` 仍报告没有 terminal sensor，`media7` 仍退回 `SRGGB8_1X8/800x600` 无上游输入。
- 当前验收前置条件仍是恢复 SC850SL 硬件 I2C 响应和 terminal sensor/media graph；在此之前不进入 ALPR/OCR/锁牌阈值验收。
