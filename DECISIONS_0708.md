# 重要决定记录

更新时间：2026-07-08

## 决定 1：Windows 基准主线不随意修改

决定：
- `alpr_topk_capture.py` 作为 Windows 行为基准脚本，不随意修改。
- Windows 实验优先使用 `alpr_topk_capture_demo.py`。

原因：
- Windows 主线已经包含车辆检测、车牌 OBB、Top-K、HyperLPR3、OCR 投票、锁定跳过和诊断输出。
- 基准脚本稳定性比短期实验更重要。

## 决定 2：RK 端不机械复刻 Windows

决定：
- RK3588 使用专门设计的板端脚本。
- RK 端允许车辆检测降频、ROI、predicted display、锁定后跳过 OBB/OCR、发布 `/tmp/frame.jpg` 等策略。

原因：
- RK 端依赖 RKNNLite、OpenCV、NumPy，算力和环境与 Windows/PyTorch 不同。
- MIPI、ISP、NPU、实时发布和浏览器展示会显著影响 FPS。

## 决定 3：当前 OCR 主推 HyperLPR3

决定：
- 当前中文车牌 OCR 主推 HyperLPR3。

原因：
- PaddleOCR 对小而模糊的中文车牌不稳定且速度慢。
- plate-rec 系列曾出现较多泛中文乱码。
- HyperLPR3 当前在项目样本中表现相对最好。

## 决定 4：本地 IMX585 和远程 SC850SL 分开看

决定：
- 本地 IMX585 板用于验证内置视频和 IMX585 MIPI 能力。
- 远程 SC850SL 板用于最终真实道路摄像头识别目标。
- 不把本地 IMX585 的摄像头结论机械套到远程 SC850SL。

原因：
- 两块板摄像头模组不同：本地是 IMX585，远程是 SC850SL。
- 图像域、ISP、IQ、曝光、设备节点和模型适配都可能不同。

## 决定 5：SC850SL 适配使用后补副本

决定：
- 远程 SC850SL 实时调试主脚本是 `rk3588_topk_capture_mipi_debug_sc850.py`。
- 不直接污染 `rk3588_topk_capture_mipi_debug.py`。

原因：
- `rk3588_topk_capture_mipi_debug.py` 是本地 IMX585/MIPI 调试参考脚本。
- SC850SL 需要独立适配，避免破坏 IMX585 已可用基线。

## 决定 6：SC850SL 实时主输入切换到 `/dev/video71` NV12

决定：
- SC850SL 实时道路测试主输入从 `/dev/video33` RAW10 灰度切到 `/dev/video71` 标准 ISP `NV12`。
- `/dev/video33` RAW10 灰度只保留为临时对照/救生绳。

原因：
- `/dev/video71` 已通过证据包确认 4K `NV12` 可出帧，约 30 FPS。
- `/dev/video71` 属于 SC850SL 对应的 `rkisp1-vir1` mainpath。
- 标准 ISP 彩色/YUV 输出更接近最终道路实测需求。

## 决定 7：不再把 `/dev/video44` 和 `/dev/video53` 当作 SC850SL 主输出

决定：
- `/dev/video44` 不再作为 SC850SL 4K ISP 主输出判断节点。
- `/dev/video53` 只作为另一路 ISP mainpath 对照，不作为 SC850SL 主测试节点。

原因：
- 探针包显示 `/dev/video44` 属于 `rkisp0-vir0`，不是 SC850SL 主链路。
- `/dev/video53` 上游是另一条 `rkcif-mipi-lvds2/SRGGB12_1X12` 链，不是已确认的 SC850SL 链。
- SC850SL 链路应看 `/dev/video71`。

## 决定 8：先稳定车辆框，再调车牌/OCR

决定：
- 远程 SC850SL 实时道路测试先做车辆框诊断。
- 不急着把 `ocr-engine none`、`PLATE` 或低阈值假锁定当作目标完成。
- 2026-07-08 第一轮打包反馈中 vehicle RKNN 已起量，但 `min_process_vehicle_conf=1.10` 故意挡掉全部候选；下一轮决定把 `MIN_PROCESS_VEHICLE_CONF` 放低到 `0.12` 左右，先观察 plate OBB，不直接开启真实 OCR 锁定。

原因：
- 如果车辆框不稳定，plate OBB/OCR 没有可靠输入。
- 当前主要问题是实时道路画面车辆候选质量不稳定，以及电动车、车轮、行人和非目标区域误检。
- 先看 plate OBB 的 accepted/rejected 结构，比直接启用 HyperLPR3 更容易定位问题发生在车辆候选、车牌 OBB 还是 OCR。

## 决定 9：motion 只作为候选源，必须过滤

决定：
- `--vehicle-source motion` 只作为固定机位运动候选源，不视为车辆分类器。
- 必须结合尺寸、长宽比、填充率、车道 ROI、稳定跟踪和车牌验证过滤非汽车目标。

原因：
- motion 能框到真实汽车，但也会框到电动车、车轮和其他运动物体。
- 最终目标是汽车车牌随车显示，不能把所有运动物体都送入车牌识别阶段。

## 决定 10：deblur 暂不进入 RK 实时主链路

决定：
- deblur 先在 Windows demo 和离线 Top-K crop 中做 A/B。
- 只有 OCR 收益明确后，才考虑作为 RK 后台补票层。

原因：
- deblur 会占用算力。
- 当前 OCR 增益未稳定验证。
- RK 实时链路优先保证 FPS、车辆框稳定和主流程可靠。

## 待确认

- 当前 Codex 是否能通过某种跳板方式访问远程 SC850SL 板。
- 远程板上 `rk3588_topk_capture_mipi_debug_sc850.py` 是否与本地项目根目录版本一致。
- 远程道路实测的最佳 ROI、曝光、vehicle 阈值和 motion 过滤参数。

## 决定 11：`LOCK PLATE` 只作为诊断信号，下一轮启用 HyperLPR3 验证真实文本

决定：
- 远程 SC850SL 第二轮 `OCR_ENGINE=none` 中出现的 `LOCK PLATE` 不作为真实识别结果。
- 下一轮优先启用 `OCR_ENGINE=hyperlpr3`，查看真实 OCR 文本、投票记录和锁定结果。
- 暂不因为 `LOCK PLATE` 数量多而直接修改 Windows 基准脚本或 IMX585 主脚本。

原因：
- `rk3588_topk_capture_mipi_debug_sc850.py` 当前逻辑中，`ocr_engine == "none"` 时接受的 plate OBB 候选会被锁成占位标签 `PLATE`。
- 第二轮 Top-K crop 显示既有真实车辆真实车牌，也有公交广告字、路面箭头、标线等误候选。
- 只有启用 HyperLPR3 后，才能区分“真车牌能否读出”和“误候选是否会被 OCR/vote 挡住”。

## 决定 12：下一轮优先缩短帧数拿完整 summary/crop

决定：
- 远程 SC850SL 下一轮 HyperLPR3 采集优先使用较短 `MAX_FRAMES`，例如 `120`，并显式设置较长 `TIMEOUT_SECONDS`，例如 `900`。
- 验证重点从“长时间显示”临时切换为“确保保存完整 run 目录、summary、Top-K crop、vote history”。

原因：
- `sc850_video71_vehicle_probe_20250626_144216.tar.gz` 已经出现 OCR 锁定 `苏E8H8R5`，但 run 目录为空，缺少可复核证据。
- 没有 `run_summary.json` 和 crop 时，无法判断锁定文本是否对应真实车牌，也无法系统分析误候选是否被 OCR/vote 挡住。
- 先拿到完整闭环证据，比继续跑更长但被截断的实时流更有价值。

## 决定 13：优先验证高质量单帧锁定，而不是盲目降低投票门槛

决定：
- 不直接把 `vote_threshold` 无条件降到 1。
- 下一轮只在同时满足高 OCR 置信、高车辆置信、高 candidate score、高 OBB 置信时允许单帧锁定。
- 先通过采集脚本暴露已有参数进行实验，不马上修改 `rk3588_topk_capture_mipi_debug_sc850.py` 的核心投票逻辑。

原因：
- 第四轮完整包显示真车真牌已经能被定位，部分单帧 OCR 也可能正确，例如 `track_49` 的 `粤E2KPA8`。
- 同时也存在高置信但省份漂移的读数，例如 `京UEP920`、`苏UEP920`，直接单票锁定有误锁风险。
- 利用现有 `--min-ocr-conf`、`--min-lock-vehicle-conf`、`--min-lock-candidate-score`、`--min-lock-obb-conf` 可以先做低侵入 A/B。

## 决定 14：第五轮无锁定不视为高质量单帧策略失败

决定：
- `sc850_video71_vehicle_probe_20250626_103725.tar.gz` 中没有锁定，不直接判定高质量单帧锁定策略失败。
- 下一轮优先增加采集帧数或等待更清晰车辆进入 ROI，而不是立刻大幅降低阈值。

原因：
- 第五轮 `vote_events` 为空，说明没有 OCR 文本进入投票阶段，锁定逻辑没有真正被触发。
- 抽查 crop 显示真车牌仍然偏小偏糊，且该轮车辆数量少于第四轮。
- 阈值实验需要在至少存在可读 OCR 文本的样本上才有判断意义。

## 决定 15：优先微调车辆锁定置信到 0.75

决定：
- 下一轮只将 `MIN_LOCK_VEHICLE_CONF` 从 `0.80` 降到 `0.75`。
- `MIN_OCR_CONF=0.85`、`MIN_LOCK_CANDIDATE_SCORE=0.60`、`MIN_LOCK_OBB_CONF=0.85` 暂不降低。

原因：
- 第六轮中 `track_42` 的 `苏E69T60` 是较可信真车真牌，但被 `vehicle_conf=0.765 < 0.80` 挡住。
- 第六轮中的其他 OCR vote 大多因 vehicle/candidate/OBB 不足被挡，挡住结果合理。
- 只微调一个阈值可以验证最小风险路径，避免同时放松多个门槛造成误锁。

## 决定 16：暂不继续降低高质量单帧门槛

决定：
- `MIN_LOCK_VEHICLE_CONF=0.75` 保持不变。
- 暂不降低 `MIN_LOCK_CANDIDATE_SCORE=0.60` 和 `MIN_LOCK_OBB_CONF=0.85`。

原因：
- 第七轮中唯一 OCR vote 的 candidate/OBB/vehicle 质量都很低，不锁定是正确结果。
- 当前缺的是足够清晰、足够高质量的车牌样本，不是锁定门槛普遍过严。
- 继续降低门槛可能释放货车尾部糊牌、广告字或非标准文本误锁。

## 决定 17：SC850SL 进入代码级锁牌策略，先加格式保护再降候选分

决定：
- 在 `rk3588_topk_capture_mipi_debug_sc850.py` 增加可开关的 `--strict-plate-format`。
- 打开后，只有符合“省份汉字 + 字母 + 5/6 位字母数字”的 OCR 文本才允许进入 vote/lock。
- 暂不直接把 `MIN_LOCK_CANDIDATE_SCORE` 无保护地降到 `0.55` 或更低；下一轮必须配合 `STRICT_PLATE_FORMAT=1`。
- 同步让 `RK3588_dev/sc850_video71_vehicle_probe_collect.sh` 支持 `STRICT_PLATE_FORMAT=1` 环境变量。

原因：
- `sc850_video71_vehicle_probe_20250626_115610.tar.gz` 中 `track_23` 是真车真蓝牌，但 OCR 文本 `粤189M14` 第二位为数字，按常规中文民用车牌格式明显可疑，且只因 `candidate_score≈0.564 < 0.60` 被挡住。
- 如果直接降低 candidate score，会把这类高 OCR 置信但格式可疑的文本释放成锁牌风险。
- 先做格式保护，可以让后续阈值微调更有边界，并保留完整 summary 中的 `ocr_rejected:plate format` 诊断计数。

限制：
- 格式规则是工程保护，不是最终车牌真伪证明；特殊牌照规则覆盖是否充分待确认。
- Windows 本地无 `bash`，采集脚本 shell 语法需上传到 RK3588 后验证。

## 决定 18：第九轮先回退到 `/dev/video71` 出帧自检，不继续调 OCR 阈值

决定：
- `sc850_video71_vehicle_probe_20250626_123643.tar.gz` 没有 ALPR run 结果时，不把它解释为锁牌策略失败。
- 下一步优先确认 `/dev/video71` 能否在短超时内输出 `3840x2160 NV12` 的 `12441600` 字节 raw 帧。
- 在 `/dev/video71` 单帧出帧恢复前，不继续降低 OCR、candidate、OBB 或 vehicle 锁定阈值。

原因：
- 本轮 `video71_1f_nv12.raw` 为 0 字节，Python 主程序只打印 MIPI capture 初始化行后卡住到外层 900 秒超时。
- `/tmp/frame.jpg` 前后 mtime/MD5 未变化，是旧帧，不能证明本轮程序正常运行。
- 板端 SC850 主脚本 hash 与本地一致，说明当前失败点不是代码未上传或 `--strict-plate-format` 参数不兼容。

## 决定 19：recover probe 仍为 0 字节时，先重启 rkaiq/相机链路

决定：
- `sc850_video71_recover_probe_20250626_130350.tar.gz` 仍显示 `/dev/video71` raw 为 0 字节时，不继续运行完整 ALPR。
- 下一步先重启 `rkaiq_3A.service` 并重新做 `/dev/video71` 单帧短自检。
- 若重启 rkaiq 后仍然 0 字节，再考虑整板 reboot 或传感器/ISP 链路级排查。

原因：
- `VIDIOC_STREAMON` 返回成功，但没有有效 NV12 buffer 写出。
- rkaiq active 但停在 `/dev/media7: wait stream start event...`。
- dmesg 显示 SC850SL 处于 `s_stream: 0`/stream stopping 状态，并出现 sensor I2C 地址 `0x30` 访问日志。

## 决定 20：不再单纯重启 rkaiq，先查 rkaiq media 绑定

决定：
- `sc850_video71_rkaiq_restart_probe_20250626_132231.tar.gz` 显示重启 rkaiq 后仍为 0 字节，因此不继续重复 `systemctl restart rkaiq_3A.service`。
- 下一步优先查 `/etc/init.d/rkaiq_3A.sh`、`rkaiq_3A.service`、`rkaiq_3A_server` cmdline/fd 和 media 拓扑。
- 在确认 rkaiq 是否正确服务 `/dev/media7` 前，不运行完整 ALPR。

原因：
- 重启后 rkaiq 状态显示等待 `/dev/media5: wait stream start event...`，而 SC850SL `/dev/video71` 已确认属于 `/dev/media7`/`rkisp1-vir1`。
- dmesg 同时显示 `/dev/video71` 测试触发了 `sc850sl ... s_stream: 1`，但没有有效 buffer 输出，指向 ISP/3A/IQ 参数注入或 media event 对接问题。

## 决定 21：rkaiq 可见 media7 后仍无帧，下一步整板 reboot 后冷启动验证

决定：
- `sc850_rkaiq_binding_probe_20250626_133404.tar.gz` 显示 rkaiq fd 已打开 media7 相关节点，因此不再把问题简化为“rkaiq 完全没绑定 media7”。
- 下一步不继续重复重启 rkaiq，而是整板 reboot 后立即做 `/dev/video71` 5 帧 NV12 验证。
- `/dev/video71` raw 未恢复正常大小前，不运行完整 ALPR。

原因：
- rkaiq 无参数自扫描，多路打开；fd 中同时有 `/dev/v4l-subdev8`、`/dev/video78`、`/dev/video79`、`/dev/video76/75/77`，这些是 `/dev/media7`/SC850SL 链路相关节点。
- 上一次 v4l2 测试已经触发 `sc850sl ... s_stream: 1`，但 10 秒内无有效 buffer，说明问题更接近 sensor/cif/isp/rkaiq 状态机卡死或时序问题。
- 冷启动比继续局部重启更可能恢复此前已验证过的 `/dev/video71` 4K NV12 出帧状态。

## 决定 22：冷启动后 media7 拓扑异常，先全量枚举 media graph

决定：
- `sc850_video71_after_reboot_probe_20250626_084815.tar.gz` 显示 `/dev/media7` 不再包含 `rkcif-mipi-lvds4` 输入链，因此不继续对 `/dev/video71` 直接跑 ALPR。
- 下一步全量枚举 `/dev/media0-7`、`/dev/v4l-subdev*`、`v4l2-ctl --list-devices` 和 dmesg 关键词。
- 只有确认 SC850SL media graph 恢复到 `rkcif-mipi-lvds4 -> rkisp1-vir1 -> /dev/video71` 后，才回到 `/dev/video71` 出帧验证。

原因：
- 本轮 `VIDIOC_STREAMON` 返回 `Operation not permitted`，dmesg 报 `rkisp1-vir1: check rkisp_mainpath link or isp input`。
- `media7.txt` 中 `rkisp-isp-subdev` 输入为 `SRGGB8_1X8/800x600`，且没有此前成功状态中的 `rkcif-mipi-lvds4` 实体与 enabled link。
- 这说明 `/dev/video71` 节点存在但没有正确上游输入，继续 ALPR 没有意义。

## 决定 23：SC850SL sensor id 为 000000 时，停止 ALPR 调参，转入传感器链路排查

决定：
- `sc850_media_graph_probe_20250626_105135.tar.gz` 显示 `sc850sl 4-0030` 报 `Unexpected sensor id(000000)`，因此当前不继续跑完整 ALPR。
- 在 SC850SL 重新作为 terminal sensor 出现在 `rkcif-mipi-lvds4`/`rkisp1-vir1` media graph 前，不再调整 OCR、vote、candidate、OBB 或 vehicle 阈值。
- 下一步优先检查 SC850SL 物理连接、供电/复位、I2C 读写、设备树绑定和驱动 probe 状态。

原因：
- `media3.txt` 中 `rkcif-mipi-lvds4` 没有接到 `sc850sl 4-0030` 传感器实体。
- `media7.txt` 中 `rkisp-isp-subdev` 退回 `SRGGB8_1X8/800x600`，没有 SC850SL 4K RAW10 输入链路。
- dmesg 同时出现 `get remote terminal sensor failed`、`There is not terminal subdev, not synchronized with ISP` 和 `rkisp1-vir1: check rkisp_mainpath link or isp input`。
- 这些证据共同指向 sensor/driver/media graph 层，而不是 ALPR 主程序或识别策略。

## 决定 24：I2C 0x30 不响应时，优先物理链路和上电复位确认

决定：
- `sc850_sensor_health_probe_20250626_110349.tar.gz` 显示 bus4/bus5/bus7 的 `0x30` 均未响应，因此下一步优先检查 SC850SL 模组物理连接、供电和复位。
- 暂停完整 ALPR、暂停 OCR/锁牌阈值调整，也暂停继续用完整采集 sh 反复打开 `/dev/video71`。
- 只有 `i2cdetect` 或驱动 probe 能证明 SC850SL `0x30` 恢复响应后，才回到 `/dev/video71` 出帧验证。

原因：
- sysfs 中存在 `4-0030`/`5-0030`/`7-0030` 只能说明设备树创建了 I2C client，不等价于 sensor 硬件在线。
- dmesg 的 `Unexpected sensor id(000000)` 与 `i2cdetect` 不见 `0x30` 互相印证，指向 sensor 没有正确应答。
- `video71_stream.txt` 的 `Operation not permitted` 是上游 sensor/ISP 输入缺失后的结果，不是 ALPR 代码层错误。

## 决定 25：mediamtx 推流工具先查输入源，不直接作为 SC850SL 恢复证据

决定：
- `/root/mediamtx` 中的推流工具可以用于辅助排查，但必须先确认脚本输入源。
- 若推流脚本读取 `stream.h264` 文件或其它非 SC850SL 输入，推流成功只能证明网络/RTSP/HTTP 推流链路可用，不证明摄像头正常。
- 若推流脚本读取 `/dev/video71`，在当前 `0x30` 不响应和 `STREAMON Operation not permitted` 状态下，预期仍然失败或无真实画面。

原因：
- `sc850_sensor_health_probe_20250626_084905.tar.gz` 证明冷启动后早期已经没有 SC850SL sensor id 和 I2C 响应。
- 推流工具位于应用层/多媒体层，不能绕过 sensor 未注册、media graph 无上游输入的问题。

## 决定 26：允许做一次受控 mediamtx 实时推流验证

决定：
- 因 `gstPushStream.sh` 的输入源确认为 `/dev/video71`，允许下一步做一次短时、受控的 mediamtx 实时推流验证。
- 验证必须同时打包当前进程、日志、`i2cdetect`、media graph、dmesg，以及 RTSP 短抓流结果。
- 验证结束后必须停止 mediamtx/gst，避免继续占用 `/dev/video71`。

原因：
- 现有 `gst_push.log` 显示该工具曾经能从 `/dev/video71` 产生 3840x2160 NV12/H264/RTP 数据。
- 但日志可能混有历史记录，不能直接证明当前摄像头在线。
- 受控验证可以区分“当前 GStreamer 能打开视频流”与“旧日志/旧流误导”。

## 决定 27：mediamtx 实时推流失败后，回到 SC850SL 物理/I2C 链路排查

决定：
- `mediamtx_live_probe_20250626_090155.tar.gz` 已证明当前 mediamtx/GStreamer 不能从 `/dev/video71` 成功发布实时流，因此不再继续用 mediamtx 作为恢复手段。
- 在 SC850SL `0x30` I2C 响应和 media graph 恢复前，不再运行完整 ALPR、完整采集脚本或长时间推流。

原因：
- `gst_push_live.log` 报 `v4l2src` `not-negotiated (-4)`。
- mediamtx 返回 `no stream is available on path 'video71'`，`rtsp_pull_8s.h264` 为 0 字节。
- 推流前后 `0x30` 仍不响应，`media7` 和 `video71` 仍退在 800x600 无上游输入状态。
## 决定 28：没有原始 SC850 旧版备份时，不直接覆盖回退

决定：
- 不把当前 `rk3588_topk_capture_mipi_debug_sc850.py` 和 `sc850_video71_vehicle_probe_collect.sh` 直接覆盖成未知来源文件。
- 如需验证“换 sh/换 SC850 脚本后才异常”的疑点，先做备份，然后做旧行为短测，而不是声称已经恢复到真实旧版。
- 旧行为短测优先使用当前脚本的默认路径：`STRICT_PLATE_FORMAT=0`，因为 `--strict-plate-format` 默认关闭。

原因：
- `sc850_file_versions_20250626_092450.tar.gz` 显示远端没有 `.bak/.old` 等可回退版本。
- 本地离线包没有 SC850 专用旧版脚本，只有通用 `rk3588_topk_capture.py` 和 `rk3588_topk_capture_mipi_debug.py`。
- 当前 SC850 严格格式保护默认关闭，不显式设置 `STRICT_PLATE_FORMAT=1` 时不会影响 vote/lock，更不会影响 sensor probe、media graph 或 mediamtx 推流。
- 现有异常核心仍是 `0x30` 不响应、`sensor id(000000)`、`/dev/video71` 0 字节或 streamon 失败、`media7` 缺少 SC850SL 4K 上游输入，这些证据位于 ALPR 脚本之外。

限制：
- “改回去”只能作为排除疑点的工程实验，不能替代 SC850SL 物理连接、供电、reset、I2C、设备树和 media graph 排查。
## 决定 29：旧行为短测后转入多 video 节点定位

决定：
- 不继续只用 `/dev/video71` 跑 ALPR。
- 下一步先做 `/dev/video33`、`/dev/video44`、`/dev/video53`、`/dev/video71`、`/dev/video72` 的多节点出帧探针。
- 暂不把 `/dev/video53` 定为最终主线，只把它作为当前最值得验证的新候选节点。

原因：
- 旧行为短测中 `STRICT_PLATE_FORMAT=0`，但 `/dev/video71` 仍 `STREAMON Operation not permitted`，raw 仍为 0 字节，ALPR `frames_processed=0`。
- `/dev/video71` 当前格式枚举只到 800x600，media7 也没有 SC850SL 4K 上游链路。
- 本轮发现 `/dev/video-camera0 -> video53`，且 media5 存在 `rkcif-mipi-lvds2 -> rkisp0-vir2` 的 3840x2160 enabled 链路。
- 这说明当前远端实际 video 节点映射可能已经变化，必须先定位“哪个节点真实出帧”，再谈 ALPR 参数。

限制：
- `/dev/video53` 是否为远端 SC850SL 实际输出仍待确认。
- 即使 `/dev/video53` 能出帧，也需要确认画面内容、格式、分辨率和摄像头来源，不能仅凭 symlink 就修改最终项目约束。
## 决定 30：`/dev/video71` 仍是 SC850SL ISP 主线，不切换到 video53

决定：
- 远程 SC850SL 实时识别主线继续以 `/dev/video71` 为目标 ISP 输出端口。
- 不把 `/dev/video-camera0 -> video53` 当作修改主线的依据。
- `/dev/video53` 只作为旁路对照，不用于替代最终验收链路。

原因：
- 用户已确认 `/dev/video71` 是 SC850SL ISP 处理后的端口。
- 旧行为短测证明的问题不是“选错最终端口”，而是 `/dev/video71` 当前上游输入链路异常：media7 800x600、raw 0 字节、streamon 失败、dmesg 报 `check rkisp_mainpath link or isp input`。

限制：
- 在 `/dev/video71` 恢复有效出帧前，不进入 OCR、vote、锁牌阈值或显示效果调参。
## 决定 31：video71 断点定位到 sensor/I2C/terminal subdev 层

决定：
- 暂停所有完整 ALPR、OCR、vote、锁牌策略实验。
- 暂不再尝试通过改 sh、改 Python 或改输入参数恢复 `/dev/video71`。
- 下一步只做 SC850SL 设备树、GPIO、regulator、pinctrl、clock 和现场物理链路排查。

原因：
- `sc850_video71_upstream_probe_20250626_094644.tar.gz` 显示 `/dev/video71` 的 3840x2160 和 800x600 两种 stream 均失败，raw 均为 0。
- `sc850sl 4-0030` driver probe 读到 sensor id `000000`，bus4/bus5/bus7 的 `0x30` 均无响应。
- `rkcif-mipi-lvds4` 明确报找不到 remote terminal sensor，`rkisp1-vir1` 报 `check rkisp_mainpath link or isp input`。
- 这是 ISP 输入链路缺失，不是 ALPR 代码、OCR 或锁牌逻辑问题。

限制：
- 不做 reset GPIO toggle、driver unbind/bind 或设备树覆盖这类可能改变硬件状态的动作，除非先说明风险并获得用户确认。
## 决定 32：reset/供电疑点先只读解析，不直接 toggle

决定：
- 暂不对 SC850SL reset GPIO 做手动拉高/拉低。
- 暂不做 driver unbind/bind 或设备树覆盖。
- 下一步只读解析 phandle、pinctrl、endpoint 和 GPIO 映射，确认 `gpio-39/40/41` 与 SC850SL reset 的关系。

原因：
- `sc850_dt_gpio_power_probe_20250626_095237.tar.gz` 显示设备树和 driver binding 存在，但 `0x30` 仍无 I2C 响应。
- dmesg 显示 SC850SL 缺少 `power-gpios` 和真实 `dvdd/dovdd/avdd` regulator，且 reset GPIO 存在。
- debugfs 显示名为 `reset` 的 GPIO 为 `out lo ACTIVE LOW`，可能与 reset 保持有关，但当前还不能确认它就是目标 SC850SL 的实际 reset 线。
- 直接 toggle reset 可能改变远端现场状态，必须先说明风险并经用户确认。
## 决定 33：deep DT/phandle 已基本对上，下一步转现场物理/供电/reset 验证

决定：
- 暂不把当前 `/dev/video71` 失效归因于 ALPR、Python、OCR、采集 sh 或锁牌策略。
- 暂不优先判断为 `sc850sl-4@30` 到 `csi2-dphy3` 的 endpoint phandle 完全缺失。
- 在没有用户明确确认前，不远程 toggle SC850SL reset GPIO，不做 driver unbind/bind，不做设备树 overlay。
- 下一步优先让现场断电重插/压紧 SC850SL 模组并冷启动，然后只做 sensor/I2C/media graph 验证。

原因：
- `sc850_deep_dt_phandle_probe_20250626_095747.tar.gz` 显示 `sc850sl-4@30` endpoint `0x37` 与 `csi2-dphy3` input endpoint `0x15f` 能互相指回。
- `reset-gpios=<0x129 7 1>` 可解析到 gpio1 offset 7，dmesg 对应 `gpio-39 (reset)`；I2C4 pinctrl `i2c4m3-xfer` 也存在。
- 但 `i2cdetect` 仍看不到 `0x30`，dmesg 仍读到 `sensor id(000000)`，media graph 仍没有 SC850SL terminal sensor，`/dev/video71` 仍无有效上游。
- 因此目前最可靠的推进路径是先恢复 sensor 硬件在线，再回到 `/dev/video71` NV12 出帧和 ALPR。
