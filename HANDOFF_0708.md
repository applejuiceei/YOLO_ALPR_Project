# 新 AI 接手说明

更新时间：2026-07-08

## 阅读顺序

新 AI 接手本项目时，请按以下顺序阅读：

1. `AGENTS_0708.md`：先读规则、红线、协作方式。
2. `PR0JECT_0708.md`：确认项目目标、需求、验收标准和不能改的内容。
3. `STATUS_0708.md`：确认当前完成情况、卡点和下一步。
4. `DECISIONS_0708.md`：理解关键技术决定和原因。
5. `HANDOFF_0708.md`：确认接手后的第一步。
6. `NEW_CHAT_HANDOFF_20260708.md`：读取更完整的 2026-07-08 新对话总览。
7. 按需读取旧记忆文件：`AGENTS.md`、`PROJECT.md`、`STATUS.md`、`DECISIONS.md`、`HANDOFF.md`、`PROJECT_HANDOFF.md`。
8. 读取当前任务相关源码，不要一上来全局乱改。

## 当前状态

事实：
- Windows `alpr_topk_capture.py` 已在 2026-07-08 跑完整 `D:\YOLO_ALPR_Project\测试图\14.mp4`。
- Windows 输出目录为 `D:\YOLO_ALPR_Project\captures_topk_codex_win_20260708\run_20260708_131529`。
- Windows 结果锁定包含 `冀JC5216`、`冀B6R9F9`、`鲁V0JU1Q`、`冀CH7V97`；其中 `冀JC5216` 与历史常见 `冀JC5210` 不一致，待复核。
- 本地 IMX585 板已用 `rk3588_topk_capture_mipi_debug.py` 跑 `/root/deploy/144.mp4` 到 frame 1000。
- 本地 IMX585 板端输出为 `/root/alpr_topk_rk3588/runs_codex_mipi_debug_video_20260708/run_20260708_053036`。
- 本地已拉回到 `D:\YOLO_ALPR_Project\RK3588_dev\runs_codex_mipi_debug_video_20260708\run_20260708_053036`。
- 本地 IMX585 板端结果锁定 `冀JE5210` 和 `冀B6R9F9`；其中 `冀JE5210` 与历史常见 `冀JC5210` 不一致，待复核。
- 远程电脑连接的板子摄像头模组是 SC850SL。
- 远程 SC850SL 板主要运行后补脚本 `rk3588_topk_capture_mipi_debug_sc850.py`。
- 本地离线包 `RK3588_dev\offline_bundle\rk3588_alpr_roadtest_bundle_20260701` 中没有 `rk3588_topk_capture_mipi_debug_sc850.py`，项目根目录有该文件；远程板上脚本来源和版本待确认。
- 当前 Codex 能 SSH 到本地 IMX585 板 `192.168.137.168`。
- 当前 Codex SSH 到远程 SC850SL 板 `192.168.8.88` 超时，远程直连待确认。
- 2026-07-08 从本地 IMX585 板也 ping 不通 `192.168.8.88`，说明远程 SC850SL 板大概率只能从远程电脑所在局域网访问。
- 为减少截图往返，已新增 `RK3588_dev/sc850_video71_vehicle_probe_collect.sh`。该脚本应复制到远程 SC850SL 板运行，自动收集 `/dev/video71`、rkaiq、dmesg、当前帧、ALPR 车辆框诊断 run，并打包成 `/tmp/sc850_video71_vehicle_probe_*.tar.gz`。
- 2026-07-08 已分析 `sc850_video71_vehicle_probe_20250626_111756.tar.gz`：`/dev/video71` NV12 出帧正常，发布帧刷新正常，rkaiq/media7 正常，vehicle RKNN 已起量；本轮因 `min_process_vehicle_conf=1.10` 故意挡掉全部候选，导致 `track_count=0`。
- 已更新本地收集脚本，新增 `MIN_PROCESS_VEHICLE_CONF`、`PLATE_CONF`、`OCR_ENGINE` 环境变量。下一轮建议传新版脚本并用 `MIN_PROCESS_VEHICLE_CONF=0.12 OCR_ENGINE=none` 观察 plate OBB。

推断：
- 远程 SC850SL 当前主问题不是 ALPR 主流程坏了，而是实时摄像头图像域、曝光、ROI、车辆候选质量和 SC850SL 适配。
- 下一步主线应继续围绕 `/dev/video71` NV12 和 `rk3588_topk_capture_mipi_debug_sc850.py` 调车辆框质量。

## 接手后的第一步

如果能直连远程 SC850SL 板：

1. SSH 到 `root@192.168.8.88`。
2. 确认 `/root/alpr_topk_rk3588/rk3588_topk_capture_mipi_debug_sc850.py` 存在并记录文件时间、大小和版本差异。
3. 确认 `/dev/video71` 可用，`/dev/video-camera0` 是否指向 `video71`。
4. 先跑车辆框诊断命令，不把 `ocr-engine none` 结果当作真实识别完成。
5. 检查 `/tmp/frame.jpg` 是否持续刷新，观察 frame 计数、FPS、vehicle boxes、plate attempts。
6. 保存 run 目录并查看 `run_summary.json`、track summary、rejected 样本和 vote history。

如果当前 Codex 仍不能直连远程 SC850SL 板：

1. 明确记录“远程板直连待确认/当前不可达”。
2. 给用户可直接粘贴到远程电脑 PowerShell/SSH 终端的命令。
3. 让用户回传终端输出、`run_summary.json` 和关键截图。
4. 不编造远程板实验结果。

优先回传方式：

1. 把 `RK3588_dev/sc850_video71_vehicle_probe_collect.sh` 传到远程 SC850SL 板。
2. 在板端执行脚本。
3. 传回脚本生成的 `/tmp/sc850_video71_vehicle_probe_*.tar.gz`。
4. 本地解压后分析 `collect.log`、`alpr_vehicle_probe.log`、`video71_1f_nv12.jpg`、`frame_after.jpg` 和 `run/run_summary.json`。

## 远程 SC850SL 建议起始命令

先跑车辆框诊断，不急着 OCR：

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

如果误检电动车、车轮或非目标区域很多：

- 收窄 `--detect-roi` 到机动车道。
- 逐步把 `--vehicle-conf` 从 `0.12` 提到 `0.18`、`0.22`、`0.28`。
- 必要时使用 `--vehicle-source motion` 或 `hybrid`，但必须加 motion 过滤参数。
- 汽车框稳定后，再启用 `--ocr-engine hyperlpr3` 验证真实车牌锁定。

## 注意事项

- `/tmp/frame.jpg` 可能是旧帧。
- `ocr-engine none` 和 `PLATE` 不是最终目标。
- 车辆框不稳时，不要急着调 OCR。
- 每轮测试都要保存 run 目录并分析 summary/rejected/vote history。
- 信息不确定时写“待确认”。

## 2026-07-08 新增接手重点

最新已分析回传包：
- `RK3588_dev/sc850_video71_vehicle_probe_20250626_113214.tar.gz`

关键事实：
- 本轮 `OCR_ENGINE=none`，因此画面中的 `LOCK PLATE` 是占位诊断锁，不是真实 OCR 结果。
- 300 帧内有 `plate_attempts=193`、`accepted_candidates=26`、`plate_detect_locks=26`。
- 保存样本中 `track_11`、`track_24`、`track_8` 可见真实车和真实车牌 crop；`track_84` 可见公交车身文字被误当作车牌候选。

接手后的第一步：
- 给用户第三轮远程板端命令，使用同一个采集脚本在 `/dev/video71` NV12 下启用 `OCR_ENGINE=hyperlpr3`，回传新的 `sc850_video71_vehicle_probe_*.tar.gz`。
- 新包回来后优先看 `run_summary.json`、各 track `vote_history`、`locked_text`、`plate_rank1.jpg`、`rejected` 样本，而不是只看浏览器截图。

## 2026-07-08 第三轮包后的接手重点

已分析回传包：
- `RK3588_dev/sc850_video71_vehicle_probe_20250626_144216.tar.gz`

关键事实：
- HyperLPR3 已在日志中锁定一次：`track=20 plate=苏E8H8R5 frame=46 events=4`。
- `frame_after.jpg` 到 `frame:268`，显示多辆车被蓝框跟踪，`OCR_ENGINE=none` 那轮的大面积 `LOCK PLATE` 占位框没有再出现。
- 该包的 run 目录为空，没有 `run_summary.json` 和 Top-K crop，不能算完整闭环。

接手后的第一步：
- 让用户在远程板执行短帧数 HyperLPR3 采集：`MAX_FRAMES=120 TIMEOUT_SECONDS=900 OCR_ENGINE=hyperlpr3`。
- 新包回来后必须先确认 `run_summary.json` 是否存在，再判断 OCR 文本是否真实。

## 2026-07-08 第四轮包后的接手重点

已分析回传包：
- `RK3588_dev/sc850_video71_vehicle_probe_20250626_150317.tar.gz`

关键事实：
- 该包完整保存了 summary/crop/rejected，是当前最重要的 SC850SL 闭环证据。
- 120 帧内 `ocr:hyperlpr3=69`、`accepted_candidates=69`，但没有任何 `locked_text`。
- `track_49` 可能是正确单帧识别 `粤E2KPA8`，但因为只有 1 票未锁定。
- `track_2` 和 `track_25/27/29` 暴露出省份和局部字符漂移问题。
- 本地 `RK3588_dev/sc850_video71_vehicle_probe_collect.sh` 已新增投票/锁定阈值环境变量透传。

接手后的第一步：
- 让用户上传更新后的 `sc850_video71_vehicle_probe_collect.sh` 到远程板 `/root/alpr_topk_rk3588/`。
- 下一轮运行高质量单帧锁定实验，优先验证是否能锁住清晰真牌而不锁漂移结果。

## 2026-07-09 第五轮包后的接手重点

已分析回传包：
- `RK3588_dev/sc850_video71_vehicle_probe_20250626_103725.tar.gz`

关键事实：
- 本轮使用了高质量单帧参数，且完整保存了 summary/crop。
- 120 帧内 `ocr:hyperlpr3=15`、`accepted_candidates=15`，但 `vote_events` 为空、`lock_attempts=0`、没有 `locked_text`。
- 抽查 `track_2`、`track_9` 是真车真牌但 plate crop 小糊，HyperLPR3 未输出文本；`track_3` 为公交/广告文字场景且未误锁。

接手后的第一步：
- 不要把第五轮无锁定当作阈值策略失败。
- 下一轮建议保持高质量单帧参数，改用 `MAX_FRAMES=300` 或等待更多近距离车辆再采集。

## 2026-07-09 第六轮包后的接手重点

已分析回传包：
- `RK3588_dev/sc850_video71_vehicle_probe_20250626_110254.tar.gz`

关键事实：
- 本轮 300 帧完整保存，出现 5 个 OCR vote，但没有锁定。
- `track_42` 的 `苏E69T60` 是最接近可锁定的真车真牌，被 `MIN_LOCK_VEHICLE_CONF=0.80` 挡住，实际 vehicle_conf 约 `0.765`。
- `track_48` 的 `E377883` 被 candidate/OBB 质量挡住，挡住合理。

接手后的第一步：
- 下一轮仅将 `MIN_LOCK_VEHICLE_CONF` 调到 `0.75`，其它高质量参数保持不变，继续跑 `MAX_FRAMES=300`。

## 2026-07-09 第七轮包后的接手重点

已分析回传包：
- `RK3588_dev/sc850_video71_vehicle_probe_20250626_112854.tar.gz`

关键事实：
- `MIN_LOCK_VEHICLE_CONF=0.75` 已生效。
- 300 帧内仅 1 个 OCR vote：`track_57` 的 `沪V9MVF2`，但 vehicle/candidate/OBB 质量都低，被挡住合理。
- 本轮无 `locked_text`，也无误锁。

接手后的第一步：
- 不要继续盲目降低质量阈值。
- 下一轮保持当前高质量单帧参数，优先在更清晰、更近车辆进入 ROI 时采集。
- 若多轮仍无法锁定，再考虑代码级格式校验和字符聚类。

## 2026-07-09 新接手补充

最新状态：
- 已分析 `RK3588_dev/sc850_video71_vehicle_probe_20250626_115610.tar.gz`。
- 本轮 300 帧完整保存，HyperLPR3 有 31 次 accepted OCR，但没有 `locked_text`。
- 唯一进入 vote 的 `track_23` 文本为 `粤189M14`，被 `lock candidate score` 挡住；crop 显示是真车真蓝牌，但文本结构按常规中文民用车牌格式可疑。
- 已对 `rk3588_topk_capture_mipi_debug_sc850.py` 做最小代码级改动：新增 `--strict-plate-format`，格式不合格文本不进入投票，并记录 `ocr_rejected:plate format`；同时修复 `consensus()` 空 ratio 保护。
- 已对 `RK3588_dev/sc850_video71_vehicle_probe_collect.sh` 增加 `STRICT_PLATE_FORMAT=1` 透传。
- 已在 Windows 本地执行 `python -m py_compile rk3588_topk_capture_mipi_debug_sc850.py`，语法通过；采集脚本因 Windows 无 `bash` 未能本地 `bash -n`。

接手第一步：
- 把更新后的 `D:\YOLO_ALPR_Project\rk3588_topk_capture_mipi_debug_sc850.py` 和 `D:\YOLO_ALPR_Project\RK3588_dev\sc850_video71_vehicle_probe_collect.sh` 上传到远程 SC850SL 板端 `/root/alpr_topk_rk3588/`。
- 在远程板端运行下一轮采集，建议参数：
  `STRICT_PLATE_FORMAT=1 MIN_LOCK_CANDIDATE_SCORE=0.55 MIN_LOCK_VEHICLE_CONF=0.75 MIN_LOCK_OBB_CONF=0.85 MIN_OCR_CONF=0.85 VOTE_THRESHOLD=1 MAX_FRAMES=300 OCR_ENGINE=hyperlpr3 ./sc850_video71_vehicle_probe_collect.sh`
- 回传新生成的 `/tmp/sc850_video71_vehicle_probe_*.tar.gz` 后，优先检查 `run_summary.json` 中 `locked_text`、`ocr_rejected:plate format`、`vote_events`，再看对应 track 的 vehicle/plate crop。

## 2026-07-09 第九轮回传后接手补充

最新状态：
- 已分析 `RK3588_dev/sc850_video71_vehicle_probe_20250626_123643.tar.gz`。
- 本轮没有 `run_summary.json`、track summary 或 Top-K crop。
- `alpr_vehicle_probe.log` 只有 MIPI capture 初始化行，随后主程序到外层 900 秒超时，未进入 `Processed ...` 循环。
- `video71_1f_nv12.raw` 为 `0` 字节，`/tmp/frame.jpg` 前后 mtime/MD5 不变，是旧帧。
- 板端 `rk3588_topk_capture_mipi_debug_sc850.py` SHA256 与本地一致，说明主脚本上传成功；当前失败点不是 `--strict-plate-format` 参数导致。

接手第一步：
- 不要继续调 OCR 阈值；先让用户在远程板端做 `/dev/video71` 单帧/短流出帧自检。
- 只有 raw 恢复到 `12441600` 字节、`/tmp/frame.jpg` 能刷新后，再重新跑 `STRICT_PLATE_FORMAT=1` 的 300 帧 ALPR 采集。

## 2026-07-09 rkaiq restart probe 后接手补充

最新状态：
- 已分析 `RK3588_dev/sc850_video71_rkaiq_restart_probe_20250626_132231.tar.gz`。
- 重启 `rkaiq_3A.service` 后，服务 active，但日志显示等待 `/dev/media5`，不是 SC850SL 主链路 `/dev/media7`。
- `/dev/video71` 单帧 raw 仍为 0 字节。
- dmesg 显示本轮确实触发 `sc850sl 4-0030: s_stream: 1` 和 `rkcif-mipi-lvds4: stream[0] start streaming`，但 10 秒内没有有效 NV12 buffer 完成。

接手第一步：
- 不要重复跑完整 ALPR，也不要继续调 OCR。
- 先收集并分析 rkaiq media 绑定：`/etc/init.d/rkaiq_3A.sh`、systemd service、`rkaiq_3A_server` cmdline/fd、`/dev/media5` 与 `/dev/media7` 拓扑、`/etc/iqfiles`。
- 若无法让 rkaiq 回到 `/dev/media7`，再考虑整板 reboot 后先做 `/dev/video71` 单帧验证。

## 2026-07-09 media graph probe 后接手补充

最新状态：
- 已分析 `RK3588_dev/sc850_media_graph_probe_20250626_105135.tar.gz`。
- `sc850sl 4-0030` probe 失败，dmesg 明确为 `Unexpected sensor id(000000), ret(0)`。
- `sc850sl_2L 5-0030` 和 `sc850sl_2L 7-0030` 也读到 `Unexpected sensor id(000000)`。
- `rkcif-mipi-lvds4` 报 `get remote terminal sensor failed` 和 `There is not terminal subdev, not synchronized with ISP`。
- `media3.txt` 是 `rkcif-mipi-lvds4`，但没有 `sc850sl 4-0030` 传感器实体挂到 dphy/csi2。
- `media7.txt` 仍只有 `rkisp1-vir1` 自身节点，pad0 为 `SRGGB8_1X8/800x600`，没有 SC850SL 4K RAW10 上游输入链路。

接手第一步：
- 不要跑完整 ALPR，不要继续调 `STRICT_PLATE_FORMAT`、OCR 或锁牌阈值。
- 先让远程端确认是否可以对 SC850SL 模组/整板做真正断电重上电，并检查排线、供电、复位。
- 如果不能物理处理，就发下一轮 sensor/I2C/sysfs 健康探针命令，目标是证明 `0x30` 设备是否可见、驱动是否绑定、SC850SL 是否能重新进入 media graph。

## 2026-07-09 sensor health probe 后接手补充

最新状态：
- 已分析 `RK3588_dev/sc850_sensor_health_probe_20250626_110349.tar.gz`。
- 当前没有 ALPR 进程占用设备，只有 rkaiq。
- `/dev/video71` 单帧 NV12 raw 仍为 0 字节，`VIDIOC_STREAMON` 返回 `Operation not permitted`。
- `i2cdetect` 结果显示 bus4/bus5/bus7 的 `0x30` 均未响应；sysfs 的 `4-0030`/`5-0030`/`7-0030` 只是设备树实例存在。
- dmesg 再次确认 `sc850sl 4-0030: Unexpected sensor id(000000), ret(0)`。
- `media3` 没有 SC850SL sensor 实体，`media7` 仍是 800x600 无上游输入状态。

接手第一步：
- 不要再跑完整 `sc850_video71_vehicle_probe_collect.sh`，也不要运行 ALPR。
- 让远程现场优先断电、重插/压紧 SC850SL 排线、确认供电和 reset，再冷启动。
- 冷启动后只重复 sensor health probe；若 `0x30` 仍不响应，继续查硬件/设备树/驱动，不进入识别策略。

## 2026-07-09 sensor health probe 084905 后接手补充

最新状态：
- 已分析 `RK3588_dev/sc850_sensor_health_probe_20250626_084905.tar.gz`。
- 该包时间为冷启动早期 `2025-06-26 08:49:05 CST`，仍显示 `0x30` 不响应、`sensor id(000000)`、`video71` stream on 失败。
- 这说明 SC850SL 异常不是后续 ALPR 进程占用导致。
- 用户发现板端 `/root/mediamtx` 有推流工具，包括 `gstPushStream.sh`、`start_4_stream.sh`、`mediamtx.yml`、`stream.h264` 等。

接手第一步：
- 先让用户只读打包 `/root/mediamtx` 的脚本、配置和日志，确认推流输入源。
- 如果输入源不是 `/dev/video71`，不要把推流成功视为 SC850SL 恢复。
- 如果输入源是 `/dev/video71`，当前失败是预期结果，仍应回到 sensor/I2C/物理链路排查。

## 2026-07-09 mediamtx probe 后接手补充

最新状态：
- 已分析 `RK3588_dev/mediamtx_probe_20250626_085507.tar.gz`。
- `gstPushStream.sh` 输入源确认为 `/dev/video71`，不是 `stream.h264` 文件。
- `gst_push.log` 里曾出现 3840x2160 NV12、H264 caps 和 RTP stats，说明该工具历史上至少成功推过 `/dev/video71`。
- 但日志包含疑似历史记录，不能直接代表当前实时状态。

接手第一步：
- 给用户一条受控 mediamtx 实时探针命令：停止旧进程、启动推流 20 秒、抓 RTSP 短流/日志/I2C/media/dmesg、停止进程、打包回传。
- 新包回来后优先判断：当前是否真的有 mediamtx/gst 进程、RTSP 是否能保存非空短流、dmesg 是否出现 `s_stream`/rkisp 输入变化、`i2cdetect 0x30` 是否恢复。

## 2026-07-09 mediamtx live probe 后接手补充

最新状态：
- 已分析 `RK3588_dev/mediamtx_live_probe_20250626_090155.tar.gz`。
- mediamtx 启动成功，但 `gstPushStream` 的实时 `/dev/video71` 推流失败。
- `gst_push_live.log` 报 `v4l2src` `Internal data stream error` / `not-negotiated (-4)`。
- RTSP 拉流返回 404，`rtsp_pull_8s.h264` 为 0 字节。
- `i2cdetect` 仍看不到 bus4/bus5/bus7 的 `0x30`。
- `media7` 和 `video71_all` 仍显示 800x600，无 SC850SL 4K 上游输入。

接手第一步：
- 不要继续用 mediamtx 或 ALPR 反复打开 `/dev/video71`。
- 下一步只能回到 SC850SL 物理连接/供电/reset/I2C/设备树匹配排查；远程现场需确认摄像头是否真的插好并上电。
## 2026-07-09 SC850 文件版本包后接手补充

最新状态：
- 已分析 `RK3588_dev/sc850_file_versions_20250626_092450.tar.gz`。
- 远端当前 `rk3588_topk_capture_mipi_debug_sc850.py` 与本地当前文件哈希一致：`eb23c2df4ed89d2066d08c2655b65617cfbb5a636a9dac80eccba6be3e0f97f9`。
- 远端当前 `sc850_video71_vehicle_probe_collect.sh` 与本地当前文件哈希一致：`1307fe364ba6bf559ad0bc6f6386d1a0ec7f8150524110d5e7a83893f2f967b7`。
- 远端未发现 SC850 专用旧版备份；本地离线包也没有 `*_sc850.py` 或 `sc850_video71_vehicle_probe_collect.sh` 旧版。
- 当前严格车牌格式保护默认关闭，只有显式 `STRICT_PLATE_FORMAT=1` 才启用。

接手第一步：
- 不要直接覆盖远端当前文件。
- 如用户要求排除“换 sh 后异常”的疑点，给用户一条先备份、再 `STRICT_PLATE_FORMAT=0` 旧行为短测、最后打包回传 stdout/log/hash 的命令。
- 若短测仍停在 `/dev/video71` 出帧层，继续回到 SC850SL sensor/I2C/media graph 排查，不进入 OCR/锁牌调参。
## 2026-07-09 旧行为短测 093419 后接手补充

最新状态：
- 已分析 `sc850_old_behavior_short_probe_20250626_093419.tar.gz` 和 `sc850_video71_vehicle_probe_20250626_093419.tar.gz`。
- 本轮显式 `STRICT_PLATE_FORMAT=0`，`run_summary.json` 中 `strict_plate_format=false`。
- ALPR 没有真实处理任何帧：`frames_processed=0`、`track_count=0`。
- `/dev/video71` 单帧 raw 仍为 0 字节，`VIDIOC_STREAMON returned -1 (Operation not permitted)`。
- `/dev/video71` 当前 media7 仍是 800x600 无上游输入，dmesg 仍有 `rkisp1-vir1: check rkisp_mainpath link or isp input`。
- 新线索：`/dev/video-camera0 -> video53`，而 media5 有 3840x2160 的 `rkcif-mipi-lvds2 -> rkisp0-vir2` enabled 链路。

接手第一步：
- 不要继续跑完整 `/dev/video71` ALPR。
- 先发多 video 节点探针命令，确认 `/dev/video53`、`/dev/video71` 等节点哪个能真实输出非 0 raw。
- 只有确认某个节点稳定输出真实道路画面后，再回到 SC850 ALPR 输入节点选择和实时识别。
## 2026-07-09 `/dev/video71` 主线确认补充

最新约束：
- 用户已明确确认 `/dev/video71` 就是远程 SC850SL 的 ISP 后端目标端口。
- 不要因为 `/dev/video-camera0 -> video53` 就把主线切到 `/dev/video53`。
- `/dev/video53` 只能作为系统其他链路是否正常的对照，不是当前 SC850SL 验收端口。

接手第一步：
- 继续围绕 `/dev/video71` 排查上游链路为什么没有有效输入。
- 优先看 SC850SL sensor/I2C、`rkcif-mipi-lvds4`、`media7/rkisp1-vir1`、rkaiq media7 stream start，而不是改 ALPR 输入节点。
## 2026-07-09 video71 upstream probe 094644 后接手补充

最新状态：
- 已分析 `RK3588_dev/sc850_video71_upstream_probe_20250626_094644.tar.gz`。
- `/dev/video71` 确认为 `rkisp1-vir1` 的 `rkisp_mainpath`，仍是目标 ISP 输出端口。
- 3840x2160 NV12 和 800x600 NV12 stream 均失败：`VIDIOC_STREAMON returned -1 (Operation not permitted)`，raw 均为 0。
- `media7` 仍是 800x600 默认状态，无 SC850SL/rkcif-mipi-lvds4 上游输入。
- `rkcif-mipi-lvds4` 存在，但没有 SC850SL terminal sensor 实体接入。
- `i2cdetect` 在 bus4/bus5/bus7 均看不到 `0x30`。
- dmesg：`sc850sl 4-0030: Unexpected sensor id(000000)`，并有 `rkcif-mipi-lvds4 ... get remote terminal sensor failed` / `There is not terminal subdev`。
- dmesg 显示 `sc850sl 4-0030` 使用 `gpio-39` 作为 reset，缺少 power GPIO，dvdd/dovdd/avdd 使用 dummy regulator。

接手第一步：
- 不要跑 ALPR。
- 发只读的 SC850SL DT/GPIO/regulator/pinctrl/clock 探针，确认 reset/power/supply 描述和实际状态。
- 如现场可操作，优先让远程现场断电重插/压紧 SC850SL 模组并确认供电/reset/pwdn。
## 2026-07-09 DT/GPIO/power probe 095237 后接手补充

最新状态：
- 已分析 `RK3588_dev/sc850_dt_gpio_power_probe_20250626_095237.tar.gz`。
- `sc850sl-4@30` DT 节点存在，compatible 为 `smartsens,sc850sl`，有 `reset-gpios`、`xvclk`、`pinctrl-0`、`power-domains` 等。
- dmesg 显示 `sc850sl 4-0030` 使用 `gpio-39 (reset)`，但缺 `power-gpios`，`dvdd/dovdd/avdd` 使用 dummy regulator。
- `sc850sl-1@30`/`sc850sl-2@30` 也类似，分别对应 `gpio-40`、`gpio-41` reset。
- `i2cdetect` 在 bus4/bus5/bus7 均看不到 `0x30`。
- `debug_gpio.txt` 中出现 `reset out lo ACTIVE LOW`，这是高优先级疑点，但还不能确认具体对应哪个 SC850SL reset。

接手第一步：
- 发只读 deep DT/phandle/pinctrl/endpoint probe。
- 不要直接 toggle GPIO，不要 unbind/bind driver，除非用户明确同意。
## 2026-07-09 deep DT/phandle probe 095747 后接手补充

最新状态：
- 已分析 `RK3588_dev/sc850_deep_dt_phandle_probe_20250626_095747.tar.gz`。
- `sc850sl-4@30` 设备树节点存在，位于 `i2c@feac0000`，4 lane endpoint 指向 `csi2-dphy3`，且 `csi2-dphy3` endpoint 反向指回 SC850SL endpoint。
- `sc850sl-4@30` 的 `reset-gpios` 映射到 gpio1 offset 7，dmesg 解析为 `gpio-39 (reset)`；`pinctrl-0` 对应 `mipim0-camera2-clk`；I2C4 pinctrl 为 `i2c4m3-xfer`。
- 但是 bus4/bus5/bus7 的 `0x30` 仍无 I2C 响应，dmesg 仍为 `Unexpected sensor id(000000)`，`media7` 仍没有 SC850SL 4K 上游输入。
- 当前结论：不是 ALPR 主程序问题；也不优先怀疑 endpoint 完全没连。主线继续是 SC850SL 物理连接、供电、reset/pwdn、I2C 或供电绑定问题。

接手第一步：
- 不要运行完整 ALPR，不要继续调 `STRICT_PLATE_FORMAT`、OCR 或锁牌阈值。
- 先让远程现场断电重插/压紧 SC850SL 模组并冷启动；冷启动后只跑 sensor health/upstream probe。
- 只有当 `i2cdetect` 恢复 `0x30`、dmesg 不再读 `sensor id(000000)`、`media7` 恢复 SC850SL 4K 上游后，才回到 `/dev/video71` 4K NV12 出帧和 ALPR。
- 不要直接 toggle reset GPIO 或 unbind/bind driver，除非用户明确确认允许做会改变硬件状态的操作。
