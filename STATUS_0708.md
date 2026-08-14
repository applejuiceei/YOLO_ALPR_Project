# 项目状态

更新时间：2026-07-08

## 已完成

- Windows Top-K + HyperLPR3 主线已形成，主脚本为 `alpr_topk_capture.py`。
- Windows 实验副本 `alpr_topk_capture_demo.py` 已用于 deblur、A/B 和弹窗显示等尝试。
- RK3588 板端视频文件识别链路已跑通。
- RKNN 车辆模型和车牌 OBB 模型已在板端加载运行。
- HyperLPR3 已在板端导入并运行。
- 本地 IMX585 板曾运行 `/root/deploy/144.mp4` 1000 帧并锁定 `冀JC5210` 和 `冀B6R9F9`。
- 远程 SC850SL 板运行同一内置视频时，用户确认表现与本地 IMX585 板一致，可锁定 `冀JC5210`。
- 这说明 SC850SL 板端 ALPR 主流程、模型、OCR、投票锁定和浏览器发布链路可用。
- 远程板实际摄像头模组已确认是 SC850SL，不是 IMX585。
- `/dev/video33` 已确认可输出 SC850SL BG10 RAW10 原始帧，但只作为临时调试/对照。
- `/dev/video71` 已通过证据包确认可输出 SC850SL 标准 ISP 4K `NV12`，约 30 FPS。
- `/dev/video44` 已判断为错误链路，不再作为 SC850SL 4K ISP 主输出判断依据。
- `/dev/video53` 是另一路 ISP mainpath，只能作为对照，不作为 SC850SL 主链路。
- 已创建并使用后补脚本 `rk3588_topk_capture_mipi_debug_sc850.py` 作为远程 SC850SL 调试主脚本。
- `rk3588_topk_capture_mipi_debug_sc850.py` 已支持 `NV12/nv12`、RAW10 灰度、detect ROI、ROI tiles、motion/hybrid 候选源和 motion 过滤参数。
- 当前浏览器预览机制是 ALPR 程序持续写 `/tmp/frame.jpg`，HTTP 页面定时刷新该 JPEG。
- Windows 端 2026-07-08 已跑 `alpr_topk_capture.py` 完整视频：
  - 输入：`D:\YOLO_ALPR_Project\测试图\14.mp4`
  - 输出：`D:\YOLO_ALPR_Project\captures_topk_codex_win_20260708\run_20260708_131529`
  - 共 6971 帧，`track_count=8`
  - 锁定包含 `冀JC5216`、`冀B6R9F9`、`鲁V0JU1Q`、`冀CH7V97`
  - `冀JC5216` 与历史常见 `冀JC5210` 有差异，待复核。
- 本地 IMX585 板 2026-07-08 已跑 `rk3588_topk_capture_mipi_debug.py` 1000 帧内置视频：
  - 输入：`/root/deploy/144.mp4`
  - 输出：`/root/alpr_topk_rk3588/runs_codex_mipi_debug_video_20260708/run_20260708_053036`
  - 本地拉回：`D:\YOLO_ALPR_Project\RK3588_dev\runs_codex_mipi_debug_video_20260708\run_20260708_053036`
  - `frames_processed=1000`
  - 约 `4.07 FPS`
  - 锁定 `冀JE5210` 和 `冀B6R9F9`
  - `冀JE5210` 与历史常见 `冀JC5210` 有差异，待复核。

## 正在进行

- 围绕远程 SC850SL 实时摄像头输入继续推进。
- 主线从“摄像头是否能出图”转向“`/dev/video71` NV12 实时道路画面下车辆候选质量如何收敛”。
- 当前重点是先让汽车框稳定、减少电动车/车轮/行人/非目标区域误检，再接 plate OBB/OCR。
- 由于当前 Codex 不能直连远程 SC850SL 板，反馈方式改为：在远程板运行命令自动收集日志、run 目录和关键帧，打包为 tar.gz 后传回本地分析。
- 已新增远程板收集脚本 `RK3588_dev/sc850_video71_vehicle_probe_collect.sh`，用于 `/dev/video71` NV12 车辆框诊断和反馈打包。
- 已分析用户传回的 `RK3588_dev/sc850_video71_vehicle_probe_20250626_111756.tar.gz`：
  - `/dev/video71` 1 帧 NV12 raw 大小为 `12441600` bytes，符合 3840x2160 NV12 预期，并成功转为 jpg。
  - `/tmp/frame.jpg` 前后 mtime 和 MD5 均变化，说明发布帧在刷新。
  - rkaiq 对 `/dev/media7` 有 stream start success，dmesg 有 `sc850sl 4-0030: s_stream: 1` 和 `rkisp1-vir1: first params buf queue`。
  - 300 帧中 `vehicle_detections_raw=1068`、`vehicle_detections_nms=722`，说明 vehicle RKNN 在 `/dev/video71` NV12 彩色图上已经起量。
  - 本轮 `min_process_vehicle_conf=1.10`，所以 722 个候选全部被 `gated:vehicle confidence` 挡掉，`track_count=0` 属于参数设计结果，不代表没有检测到车。
  - `frame_after.jpg` 中可见蓝框框住真实白色 SUV，说明至少部分真实汽车可被框住。
- 已更新 `RK3588_dev/sc850_video71_vehicle_probe_collect.sh`，新增 `MIN_PROCESS_VEHICLE_CONF`、`PLATE_CONF`、`OCR_ENGINE` 环境变量，下一轮可不改脚本正文放行候选进入 plate OBB。

## 当前卡点

### 远程 SC850SL 板无法从当前 Codex 直连

事实：
- 当前环境能 SSH 到本地 IMX585 板 `192.168.137.168`。
- 当前环境 SSH 到远程 SC850SL 板 `192.168.8.88` 超时。
- 2026-07-08 从本地 IMX585 板 `192.168.137.168` 也 ping 不通 `192.168.8.88`；本地板上 `nc` 不存在，无法从该板进一步做 22 端口探测。

推断：
- 当前 Codex 所在机器可能不能直连远程电脑背后的 SC850SL 板，或存在网络/路由/权限限制。
- 远程 SC850SL 板很可能只在远程电脑所在局域网内可访问。

待确认：
- 是否需要用户在远程电脑上手动执行命令并回传结果。
- 是否存在可供当前 Codex 访问远程 SC850SL 板的跳板机、端口转发或远程终端。

### SC850SL 实时车辆候选质量尚未稳定

事实：
- `/dev/video71` NV12 已确认可作为 SC850SL 主输入。
- 低阈值下已经能框到汽车，但也会框到电动车、车轮、行人或非目标区域。
- `vehicle-source motion` 能框到真实运动汽车，但不是车辆分类器，也会产生非汽车运动候选。

推断：
- 当前失败集中在实时摄像头图像域、曝光、ROI、vehicle 阈值、候选过滤和模型适配，而不是 ALPR 主流程损坏。

## 下一步

1. 若能连接远程 SC850SL 板，优先确认 `/root/alpr_topk_rk3588/rk3588_topk_capture_mipi_debug_sc850.py` 版本和参数。
2. 在远程 SC850SL 板运行 `/dev/video71`、`NV12`、`vehicle-source rknn` 的车辆框诊断，不急着把 `ocr-engine none` 的结果当识别完成。
3. 观察 `/tmp/frame.jpg` 是否持续刷新，检查 frame 计数、文件修改时间或 MD5。
4. 收窄机动车道 ROI，逐步提高 `vehicle-conf`，过滤电动车/车轮/行人/非目标区域。
5. 汽车框稳定后，再启用 HyperLPR3 OCR，验证真实车牌锁定和随车显示。
6. 每轮测试保存 run 目录并查看 summary、rejected、vote history。
7. 远程板不可直连时，优先让用户运行 `sc850_video71_vehicle_probe_collect.sh` 并传回生成的 `/tmp/sc850_video71_vehicle_probe_*.tar.gz`。
8. 下一轮建议使用 `MIN_PROCESS_VEHICLE_CONF=0.12 OCR_ENGINE=none`，先放行候选进入 plate OBB，观察 plate attempts、accepted/rejected 和误检来源。

## 2026-07-08 远程 SC850SL 第二轮回传包分析

来源：
- 本地文件：`RK3588_dev/sc850_video71_vehicle_probe_20250626_113214.tar.gz`
- 解压目录：`RK3588_dev/sc850_video71_vehicle_probe_20250626_113214_extract/sc850_video71_vehicle_probe_20250626_113214`

事实：
- 本轮使用 `/dev/video71`、3840x2160、`NV12`、`vehicle_source=rknn`、`vehicle_conf=0.12`、`min_process_vehicle_conf=0.12`、`ocr_engine=none`。
- 300 帧处理完成，约 `1.23 FPS`。
- `vehicle_detections_raw=404`，`vehicle_detections_nms=287`，`vehicles_ready=193`，`plate_attempts=193`。
- `obb_candidates=43`，`accepted_candidates=26`，`ocr_skipped:none=26`，`plate_detect_locks=26`。
- 代码中即使 `lock_on_plate_detect=false`，只要 `ocr_engine == "none"`，接受的 plate OBB 候选仍会被锁成 `PLATE`，因此画面中的 `LOCK PLATE` 不是 OCR 成功。
- `track_11`、`track_24`、`track_8` 等样本包含真实车辆和真实车牌 crop，说明 SC850SL `/dev/video71` 链路已经能把真车送入 plate OBB。
- `track_84` 样本把公交车身广告字当作车牌候选，画面中也能看到部分路面箭头、标线、墙面/施工区域产生假候选。

判断：
- 当前已经从“相机是否出帧/主流程是否能跑”推进到“SC850SL 道路视角下候选过滤和 OCR 投票如何收敛”。
- 不能把本轮 `PLATE` 当作真实车牌识别；它只证明 plate OBB 有命中和误命中。
- 下一轮应启用 `OCR_ENGINE=hyperlpr3`，用真实 OCR/vote 观察哪些候选能形成真实车牌文本；同时保留完整 run、summary、crop 和 rejected 样本。

下一步：
- 让远程 SC850SL 板运行第三轮采集：保持 `/dev/video71` NV12，启用 `OCR_ENGINE=hyperlpr3`，暂不修改主脚本，先观察真实 OCR 输出、vote history 和 locked_text。

## 2026-07-08 远程 SC850SL 第三轮回传包分析

来源：
- 本地文件：`RK3588_dev/sc850_video71_vehicle_probe_20250626_144216.tar.gz`
- 解压目录：`RK3588_dev/sc850_video71_vehicle_probe_20250626_144216_extract/sc850_video71_vehicle_probe_20250626_144216`

事实：
- 本轮启用了 HyperLPR3，`alpr_vehicle_probe.log` 中出现真实 OCR 锁定日志：`[LOCK] track=20 plate=苏E8H8R5 frame=46 events=4`。
- 最后一帧 `frame_after.jpg` 显示到 `frame:268`，画面主要是蓝色车辆框，相比 `OCR_ENGINE=none` 那轮，大面积橙色 `LOCK PLATE` 占位误锁消失。
- 最后一帧左上角显示约 `veh:9`、`total_hits:72`、`fps:1.14`。
- 本包中的 `run/run_20250626_144219` 为空目录，没有 `run_summary.json`、track `summary.json`、Top-K crop 或 rejected 样本。
- `alpr_vehicle_probe.log` 没有 `Saving Top-K capture run`、`Run stats`、`Saved Top-K capture run` 等正常收尾记录。

判断：
- HyperLPR3 在远程 SC850SL `/dev/video71` NV12 实时画面上已经能触发真实文本锁定，但本包缺少 crop/summary，因此还不能验证 `苏E8H8R5` 对应的原始车牌 crop 是否正确。
- 本轮大概率在 Python 正常保存结果前被外层超时或人工中断截断；原因待确认。
- 下一轮要缩短 `MAX_FRAMES` 或显式加大 `TIMEOUT_SECONDS`，确保程序跑到保存阶段。

下一步：
- 远程板下一轮建议用 `MAX_FRAMES=120 TIMEOUT_SECONDS=900 OCR_ENGINE=hyperlpr3`，优先拿到完整 `run_summary.json` 和 Top-K crop，而不是追求更长帧数。

## 2026-07-08 远程 SC850SL 第四轮回传包分析

来源：
- 本地文件：`RK3588_dev/sc850_video71_vehicle_probe_20250626_150317.tar.gz`
- 解压目录：`RK3588_dev/sc850_video71_vehicle_probe_20250626_150317_extract/sc850_video71_vehicle_probe_20250626_150317`

事实：
- 本轮完整保存了 `run/run_20250626_150320/run_summary.json`、track `summary.json`、Top-K crop 和 rejected 样本。
- 参数为 `/dev/video71`、3840x2160、`NV12`、`OCR_ENGINE=hyperlpr3`、`MAX_FRAMES=120`。
- 处理 120 帧，用时约 `120.117s`，约 `1.00 FPS`。
- `vehicle_detections_raw=374`，`vehicle_detections_nms=249`，`plate_attempts=185`，`obb_candidates=208`，`ocr:hyperlpr3=69`，`accepted_candidates=69`。
- 没有任何 `locked_text`，但多个 track 进入 `VERIFYING`。
- 典型样本：
  - `track_49` 的 vehicle/plate crop 肉眼支持 `粤E2KPA8`，OCR 也给出 `粤E2KPA8`，但只有 1 次 vote，未达到 3 票锁定。
  - `track_2` 连续读出 `川E0MA19`、`川EU9619`、`桂E0GA19`、`云E0RA19`、`浙E0R619`、`辽E0RA19`，主体字符相似但省份/局部字符漂移。
  - `track_25/27/29` 疑似同一或相邻车辆片段，OCR 读出 `粤UEP920`、`京UEP920`、`苏UEP920` 等，后缀 `EP920` 稳定但省份漂移。

判断：
- 当前主问题不是车辆/牌框无法定位，而是远距离小糊车牌导致 HyperLPR3 单帧 OCR 文本漂移，现有整串/字符一致投票策略过于保守，无法锁定。
- 不能简单把 `vote_threshold` 降到 1，否则会把部分高置信但省份错误的结果提前锁死。
- 下一轮应先验证“高质量单帧锁定”策略：只有当 OCR 置信、车框置信、candidate score、OBB 置信同时较高时，才允许单帧锁定。

已改动：
- 本地 `RK3588_dev/sc850_video71_vehicle_probe_collect.sh` 新增环境变量透传：`VOTE_THRESHOLD`、`MIN_CHAR_VOTE_RATIO`、`MIN_OCR_CONF`、`MIN_LOCK_VEHICLE_CONF`、`MIN_LOCK_CANDIDATE_SCORE`、`MIN_LOCK_OBB_CONF`。

下一步：
- 将更新后的采集脚本传到远程板，再跑 `VOTE_THRESHOLD=1 MIN_OCR_CONF=0.85 MIN_LOCK_VEHICLE_CONF=0.80 MIN_LOCK_CANDIDATE_SCORE=0.60 MIN_LOCK_OBB_CONF=0.85` 的短帧数实验，验证能否锁住类似 `track_49` 的高质量真牌，同时挡住 `track_27/29` 这类不够稳的结果。

## 2026-07-09 远程 SC850SL 第五轮回传包分析

来源：
- 本地文件：`RK3588_dev/sc850_video71_vehicle_probe_20250626_103725.tar.gz`
- 解压目录：`RK3588_dev/sc850_video71_vehicle_probe_20250626_103725_extract/sc850_video71_vehicle_probe_20250626_103725`

事实：
- 本轮完整保存了 `run/run_20250626_103727/run_summary.json`、track `summary.json`、Top-K crop 和 rejected 样本。
- 本轮确实使用了高质量单帧锁定实验参数：`vote_threshold=1`、`min_ocr_conf=0.85`、`min_lock_vehicle_conf=0.8`、`min_lock_candidate_score=0.6`、`min_lock_obb_conf=0.85`。
- 处理 120 帧，用时约 `96.596s`，约 `1.25 FPS`。
- `vehicle_detections_raw=82`，`vehicle_detections_nms=69`，`plate_attempts=59`，`obb_candidates=35`，`ocr:hyperlpr3=15`，`accepted_candidates=15`。
- 没有任何 `locked_text`，也没有任何 `vote_events`；所有 track 的 `lock_attempts=0`。
- `frame_after.jpg` 最后一帧显示 `veh:0 new_hits:0 total_hits:15`，当前帧没有车辆框。
- 抽查样本显示：`track_2`、`track_9` 是真车真牌但 plate crop 小且糊，HyperLPR3 未输出文本；`track_3` 为公交/广告文字场景，高质量门槛未误锁。

判断：
- 本轮不能证明高质量单帧锁定策略失败，因为没有 OCR 文本进入投票阶段。
- 当前样本更像是该 120 帧时间段内可读车牌不足，候选牌照太小/太糊或车辆距离不合适。
- 高质量单帧策略仍需在更多车辆、更清晰车牌的时间段继续验证。

下一步：
- 保持高质量锁定参数不变，建议把 `MAX_FRAMES` 提到 `300`，或在画面中有更多近距离车辆时再运行。
- 若连续多轮仍没有 `vote_events`，再考虑降低 `MIN_OCR_CONF` 到 `0.80`、`MIN_LOCK_CANDIDATE_SCORE` 到 `0.55` 做对照。

## 2026-07-09 远程 SC850SL 第六轮回传包分析

来源：
- 本地文件：`RK3588_dev/sc850_video71_vehicle_probe_20250626_110254.tar.gz`
- 解压目录：`RK3588_dev/sc850_video71_vehicle_probe_20250626_110254_extract/sc850_video71_vehicle_probe_20250626_110254`

事实：
- 本轮完整保存了 `run/run_20250626_110256/run_summary.json`、track `summary.json`、Top-K crop 和 rejected 样本。
- 本轮使用高质量单帧锁定实验参数，并把 `MAX_FRAMES` 提到 `300`。
- 处理 300 帧，用时约 `263.91s`，约 `1.14 FPS`。
- `vehicle_detections_raw=568`，`vehicle_detections_nms=414`，`plate_attempts=275`，`obb_candidates=285`，`ocr:hyperlpr3=74`，`accepted_candidates=74`。
- 出现 5 个 `vote_events`，但没有任何 `locked_text`。
- 被挡原因：
  - `track_48`：OCR `E377883`，被 `lock candidate score` 挡住；文本不符合中文车牌格式，挡住合理。
  - `track_42`：OCR `苏E69T60`，被 `lock vehicle confidence` 挡住；vehicle_conf 约 `0.765`，crop 是本轮最接近可锁定的真车真牌。
  - `track_41`：OCR `苏UQX825`，vehicle_conf 约 `0.622`，挡住合理。
  - `track_37`：OCR `粤EQ7E00`，vehicle_conf 约 `0.714`，挡住合理。
  - `track_21`：OCR `京N21910`，vehicle_conf 约 `0.626`，挡住合理。

判断：
- 高质量单帧门槛有效防止了明显低质量/不合格文本误锁。
- 当前门槛中最可能过严的是 `MIN_LOCK_VEHICLE_CONF=0.80`，因为 track 42 这种较可信真牌只差车辆置信。
- 不建议同时降低 OCR 置信、candidate score 或 OBB 置信，否则会放大 track 48 一类误锁风险。

下一步：
- 下一轮建议只把 `MIN_LOCK_VEHICLE_CONF` 从 `0.80` 调到 `0.75`，其它高质量单帧参数保持不变，继续跑 `MAX_FRAMES=300`。

## 2026-07-09 远程 SC850SL 第七轮回传包分析

来源：
- 本地文件：`RK3588_dev/sc850_video71_vehicle_probe_20250626_112854.tar.gz`
- 解压目录：`RK3588_dev/sc850_video71_vehicle_probe_20250626_112854_extract/sc850_video71_vehicle_probe_20250626_112854`

事实：
- 本轮完整保存了 `run/run_20250626_112857/run_summary.json`、track `summary.json`、Top-K crop 和 rejected 样本。
- 参数确认：`MAX_FRAMES=300`、`vote_threshold=1`、`min_ocr_conf=0.85`、`min_lock_vehicle_conf=0.75`、`min_lock_candidate_score=0.60`、`min_lock_obb_conf=0.85`。
- 处理 300 帧，用时约 `246.748s`，约 `1.22 FPS`。
- `vehicle_detections_raw=303`，`vehicle_detections_nms=246`，`plate_attempts=179`，`obb_candidates=141`，`ocr:hyperlpr3=48`，`accepted_candidates=48`。
- 只有 1 个 `vote_event`：`track_57` OCR 为 `沪V9MVF2`，但 vehicle_conf 约 `0.516`、candidate_score 约 `0.302`、OBB 约 `0.609`，被 `lock vehicle confidence` 挡住。
- 抽查 `track_57`：货车尾部/小糊牌，OCR 结果不可靠，不锁定是正确行为。
- 最后一帧 `frame_after.jpg` 显示 `veh:0 new_hits:0 total_hits:48`，当前帧无车辆框。

判断：
- `MIN_LOCK_VEHICLE_CONF=0.75` 已生效，但本轮没有出现足够高质量的可锁候选。
- 本轮没有误锁，说明高质量单帧策略仍在有效保护主链路。
- 继续盲目降低 vehicle/candidate/OBB 门槛会增加误锁风险，不建议。

下一步：
- 暂时保持 `MIN_LOCK_VEHICLE_CONF=0.75`、`MIN_LOCK_CANDIDATE_SCORE=0.60`、`MIN_LOCK_OBB_CONF=0.85` 不变。
- 若要更快得到锁定样本，优先选择车流更近、更清晰的时间段或等车辆进入画面中部再启动采集。
- 若连续多轮仍只有低质量 vote，再考虑代码级“车牌格式校验 + 字符级聚类/后缀稳定”策略，而不是继续降低质量阈值。

## 2026-07-09 远程 SC850SL 第八轮回传包分析

来源：
- 本地文件：`RK3588_dev/sc850_video71_vehicle_probe_20250626_115610.tar.gz`
- 解压目录：`RK3588_dev/sc850_video71_vehicle_probe_20250626_115610_extract/sc850_video71_vehicle_probe_20250626_115610`

事实：
- 本轮完整保存了 `run/run_20250626_115613/run_summary.json`、track summary 和 Top-K crop。
- 参数为 `/dev/video71`、`3840x2160`、`NV12`、`OCR_ENGINE=hyperlpr3`、`MAX_FRAMES=300`、`vote_threshold=1`、`min_ocr_conf=0.85`、`min_lock_vehicle_conf=0.75`、`min_lock_candidate_score=0.60`、`min_lock_obb_conf=0.85`。
- 处理 300 帧，用时约 `247.013s`，约 `1.22 FPS`。
- `vehicle_detections_raw=404`，`vehicle_detections_nms=299`，`vehicles_ready=187`，`plate_attempts=187`，`obb_candidates=85`，`ocr:hyperlpr3=31`，`accepted_candidates=31`。
- 没有 `locked_text`。
- 唯一进入投票/验证的候选是 `track_23`：OCR 文本为 `粤189M14`，`confidence≈0.878`，`vehicle_conf≈0.882`，`candidate_score≈0.564`，`obb_conf≈0.917`，被 `lock candidate score` 挡住。
- `track_23` 的 vehicle/plate crop 显示是真车真蓝牌，但 OCR 文本 `粤189M14` 按常规中文民用车牌格式第二位应为字母而不是数字，属于格式可疑文本；实际车牌肉眼仍待确认。
- 日志中出现过 NumPy `Mean of empty slice` / `invalid value encountered in scalar divide` warning，程序未崩溃，但说明 consensus/ratio 计算需要空列表保护。

判断：
- 本轮证明不能只靠继续降低 `MIN_LOCK_CANDIDATE_SCORE` 推进，否则可能释放 `粤189M14` 这类高 OCR 置信但格式可疑的文本。
- 当前应进入代码级策略：先增加车牌文本格式过滤，再在受保护前提下小幅试探候选分阈值。

已改动：
- `rk3588_topk_capture_mipi_debug_sc850.py` 新增 `--strict-plate-format`，打开后只有符合“省份汉字 + 字母 + 5/6 位字母数字”的文本才允许进入投票。
- `rk3588_topk_capture_mipi_debug_sc850.py` 对 `consensus()` 增加空 `scored_ratios` 保护，避免空均值 warning。
- `RK3588_dev/sc850_video71_vehicle_probe_collect.sh` 新增 `STRICT_PLATE_FORMAT=1` 环境变量透传。

验证：
- Windows 本地已执行 `python -m py_compile rk3588_topk_capture_mipi_debug_sc850.py`，语法通过。
- Windows 本地无 `bash` 命令，`sc850_video71_vehicle_probe_collect.sh` 语法需上传到 RK3588 板端后验证。

下一步：
- 将更新后的 `rk3588_topk_capture_mipi_debug_sc850.py` 和 `RK3588_dev/sc850_video71_vehicle_probe_collect.sh` 上传到远程 SC850SL 板端 `/root/alpr_topk_rk3588/`。
- 下一轮建议运行：`STRICT_PLATE_FORMAT=1 MIN_LOCK_CANDIDATE_SCORE=0.55 MIN_LOCK_VEHICLE_CONF=0.75 MIN_LOCK_OBB_CONF=0.85 MIN_OCR_CONF=0.85 VOTE_THRESHOLD=1 MAX_FRAMES=300 OCR_ENGINE=hyperlpr3`。

## 2026-07-09 远程 SC850SL 第九轮回传包分析

来源：
- 本地文件：`RK3588_dev/sc850_video71_vehicle_probe_20250626_123643.tar.gz`
- 解压目录：`RK3588_dev/sc850_video71_vehicle_probe_20250626_123643_extract/sc850_video71_vehicle_probe_20250626_123643`

事实：
- 本包大小约 `1.6 MB`，没有 `run_summary.json`，没有 track summary，也没有 Top-K crop。
- `alpr_vehicle_probe.log` 只有一行：`MIPI capture: device=/dev/video71 reported=3840x2160 fps=30.00 backend=v4l2ctl mode=nv12 buffer=1`。
- 外层采集脚本从 `12:36:59` 进入 ALPR 主程序，到 `12:51:59` 超时收尾，说明主程序在 MIPI 读帧阶段卡住，没有进入 `Processed ...` 循环。
- `video71_1f_nv12.raw` 为 `0` 字节，`video71_1f_nv12_convert.txt` 显示 `raw_size=0 expected=12441600`。
- `/tmp/frame.jpg` 前后 mtime 和 MD5 完全相同，mtime 为 `12:00:20`，MD5 为 `592180e6e5ea6193a3255b8a2296fefb`；本包中的 `frame_after.jpg` 是旧帧，不代表本轮程序正在运行。
- `/dev/video71` 仍显示为 `rkisp_mainpath`、`3840x2160`、`NV12`，`/dev/video-camera0 -> video71`。
- 板端 `rk3588_topk_capture_mipi_debug_sc850.py` SHA256 为 `eb23c2df4ed89d2066d08c2655b65617cfbb5a636a9dac80eccba6be3e0f97f9`，与本地文件一致，说明 SC850 主脚本上传成功。

判断：
- 第九轮不是 OCR/锁牌策略失败，也不是 `--strict-plate-format` 导致失败；如果参数不被支持，Python 会立即报 unknown argument，而本轮是读 MIPI 帧阻塞。
- 当前卡点回到 `/dev/video71`/ISP/MIPI 实际出帧问题：节点枚举正常，但当时 stream 没交付有效 NV12 帧。
- 浏览器显示的旧 `/tmp/frame.jpg` 不能作为本轮程序仍在工作的证据。

下一步：
- 先不要继续跑完整 ALPR；先在远程板端单独做 `/dev/video71` 短超时出帧自检，确认 raw size 是否能恢复到 `12441600`。
- 若单帧仍为 0 字节，优先重启 `rkaiq_3A.service` 或重启板端相机链路后再测，不进入 OCR 策略调参。

## 2026-07-09 远程 SC850SL recover probe 分析

来源：
- 本地文件：`RK3588_dev/sc850_video71_recover_probe_20250626_130350.tar.gz`
- 解压目录：`RK3588_dev/sc850_video71_recover_probe_20250626_130350_extract/sc850_video71_recover_probe_20250626_130350`

事实：
- 本包大小约 `3.6 KB`，是短自检包。
- `video71_1f_nv12.raw` 仍为 `0` 字节，未恢复到期望的 `12441600` 字节。
- `video71_stream.txt` 显示 `VIDIOC_STREAMON returned 0 (Success)`，但没有实际帧写入。
- `/tmp/frame.jpg` 前后 mtime/MD5 仍完全不变，继续停留在 `12:00:20` 的旧帧，MD5 为 `592180e6e5ea6193a3255b8a2296fefb`。
- `process.txt` 只看到 `rkaiq_3A_server` 和 `python3 -m http.server 8080`，没有正在运行的 ALPR Python 或 v4l2-ctl 进程。
- `rkaiq_status_before.txt` 显示 rkaiq 仍 active，但停在 `/dev/media7: wait stream start event...`。
- dmesg 出现 `sc850sl 4-0030: s_stream: 0`、`rkcif-mipi-lvds4: stream[0] start stopping`，并出现大量 `rk3x-i2c feac0000.i2c` 对 `addr 0x30` 的访问日志。

判断：
- `/dev/video71` 当前仍未恢复实际出帧；这是相机/ISP/MIPI 流状态问题，不是 ALPR 主代码、OCR、投票或 `--strict-plate-format` 的问题。
- `VIDIOC_STREAMON` 成功但 raw 为 0 字节，说明节点可打开但没有有效 buffer 完成。
- 下一步应先重启 rkaiq/相机链路并再次短自检；若仍为 0 字节，再考虑整板 reboot 或更底层的 sensor/ISP 链路排查。

下一步：
- 让用户在远程板端执行 rkaiq 重启后的 recover probe，仍只验证 `/dev/video71` raw 大小和 `/tmp/frame.jpg` 刷新。
- 在 raw 恢复到 `12441600` 字节前，不运行完整 ALPR。

## 2026-07-09 远程 SC850SL rkaiq restart probe 分析

来源：
- 本地文件：`RK3588_dev/sc850_video71_rkaiq_restart_probe_20250626_132231.tar.gz`
- 解压目录：`RK3588_dev/sc850_video71_rkaiq_restart_probe_20250626_132231_extract/sc850_video71_rkaiq_restart_probe_20250626_132231`

事实：
- `systemctl restart rkaiq_3A.service` 执行后服务确实重启，进程变为 `68009/68010`，状态为 active。
- 重启后的 `rkaiq_status_after_restart.txt` 显示 rkaiq 等待的是 `/dev/media5: wait stream start event...`，而不是 SC850SL 主链路此前确认的 `/dev/media7`。
- `/dev/video71` 单帧测试仍输出 `0` 字节 raw。
- dmesg 在本轮出现了 `rkcif-mipi-lvds4: stream[0] start streaming`、`rockchip-mipi-csi2 ... stream ON`、`sc850sl 4-0030: s_stream: 1`，说明本轮确实触发过 SC850SL 传感器开流。
- 约 10 秒后 dmesg 出现 `rkcif-mipi-lvds4: stream[0] start stopping`，但期间没有有效 NV12 buffer 写入。
- `/tmp/frame.jpg` 仍是旧帧，mtime 和 MD5 未刷新。

判断：
- 单纯重启 `rkaiq_3A.service` 没有恢复 `/dev/video71` 出帧，反而暴露出 rkaiq 可能绑定/等待到 `/dev/media5` 的问题。
- 当前状态不是 ALPR 代码问题，也不是 OCR/锁牌策略问题；卡点是 SC850SL `/dev/media7 -> /dev/video71` 的 ISP/3A/IQ 参数注入或流完成问题。
- 因为 dmesg 已出现 `s_stream:1`，传感器驱动能被拉起；更可疑的是 ISP params/first IQ、rkaiq media 绑定或多路 camera event 没落到 `rkisp1-vir1`。

下一步：
- 先收集 rkaiq 启动脚本、systemd service、当前 media symlink、rkaiq 进程 fd/cmdline、`/etc/iqfiles` 和 `/dev/media5`/`/dev/media7` 拓扑，确认重启后为什么等 `/dev/media5`。
- 在没有恢复 `/dev/video71` raw 正常大小前，继续禁止完整 ALPR 实验。

## 2026-07-09 远程 SC850SL rkaiq binding probe 分析

来源：
- 本地文件：`RK3588_dev/sc850_rkaiq_binding_probe_20250626_133404.tar.gz`
- 解压目录：`RK3588_dev/sc850_rkaiq_binding_probe_20250626_133404_extract/sc850_rkaiq_binding_probe_20250626_133404`

事实：
- `/etc/init.d/rkaiq_3A.sh` 中 `rkaiq_3A_server` 是无参数启动：`/usr/bin/rkaiq_3A_server 2>&1 | logger -t rkaiq &`。
- systemd service 也只是调用 `/etc/init.d/rkaiq_3A.sh start`，没有显式 media/camera 参数。
- 当前进程 cmdline 为 `/usr/bin/rkaiq_3A_server`。
- 当前 rkaiq fd 中同时打开了 `/dev/v4l-subdev8`、`/dev/video78`、`/dev/video79`、`/dev/video76`、`/dev/video75`、`/dev/video77`，这些属于 `/dev/media7`/`rkisp1-vir1`/SC850SL 链路；同时也打开了另一组 `/dev/media5` 相关节点。
- `media7.txt` 确认 `/dev/media7 -> rkisp1-vir1 -> /dev/video71`，上游为 `rkcif-mipi-lvds4`，格式 `SBGGR10_1X10/3840x2160`。
- `media5.txt` 确认 `/dev/media5 -> rkisp0-vir2 -> /dev/video53`，上游为 `rkcif-mipi-lvds2`，不是 SC850SL `/dev/video71` 主链路。
- `video71_all.txt` 仍显示 `/dev/video71` 是 `rkisp_mainpath`、`3840x2160 NV12`，`Size Image=12441600`。
- rkaiq status 当前最新尾部显示 `/dev/media7: wait stream start event...`，说明它后续又回到等待 media7 的状态；上一包中看到的 `/dev/media5` 不是唯一状态。
- dmesg tail 仍显示上一次 `/dev/video71` 测试触发过 `sc850sl ... s_stream: 1`，随后 10 秒后停止，但没有有效 buffer。

判断：
- rkaiq 不是完全没有打开 SC850SL/media7；它会自扫描多路 camera/ISP。
- 当前卡点更像 `/dev/video71` stream on 后没有有效帧完成，或 ISP params/3A 与 capture 时序没有形成有效输出；不是 ALPR、OCR 或锁牌策略问题。
- 继续重复重启 rkaiq 的收益有限；下一步更合理的是整板 reboot，让 sensor/cif/isp/rkaiq 从冷启动状态重新枚举，然后立即做 `/dev/video71` 5 帧 NV12 验证。

下一步：
- 建议整板 reboot。重连后先只做 `/dev/video71` 5 帧 NV12 raw 验证和打包，确认 raw 大小是否恢复为 `5 * 12441600 = 62208000` 字节。
- raw 未恢复前仍禁止完整 ALPR。

## 2026-07-09 远程 SC850SL after reboot probe 分析

来源：
- 本地文件：`RK3588_dev/sc850_video71_after_reboot_probe_20250626_084815.tar.gz`
- 解压目录：`RK3588_dev/sc850_video71_after_reboot_probe_20250626_084815_extract/sc850_video71_after_reboot_probe_20250626_084815`

事实：
- reboot 后探针运行时间为 `2025-06-26 08:48:28 CST`，距离 rkaiq 启动约 3 分 35 秒。
- `rkaiq_3A.service` active，但状态尾部显示 `/dev/media5: wait stream start event...`。
- `/tmp/frame.jpg` 不存在，说明 reboot 后 HTTP 预览旧帧也不存在，当前没有 ALPR 发布帧。
- `/dev/video71` 5 帧 NV12 采集仍为 `0` 字节。
- 本轮 `VIDIOC_STREAMON returned -1 (Operation not permitted)`，不是前几轮的 streamon 成功但无 buffer。
- dmesg 明确出现 `rkisp1-vir1: check rkisp_mainpath link or isp input`。
- reboot 后 `media7.txt` 显示 `/dev/media7` 的 `rkisp-isp-subdev` pad0 退成 `SRGGB8_1X8/800x600`，且没有 `rkcif-mipi-lvds4 -> rkisp-isp-subdev` 输入实体/链路；rawrd 链路也未启用。
- 这与之前成功状态不同：此前 `/dev/media7` 应显示 `rkcif-mipi-lvds4`、`SBGGR10_1X10/3840x2160`，并链接到 `/dev/video71`。

判断：
- 冷启动后 `/dev/video71` 节点仍在，但背后的 SC850SL 输入链未接到 `rkisp1-vir1`，所以 `/dev/video71` 无法 stream on。
- 当前问题已经从“ALPR 实时识别”退回到“reboot 后 SC850SL media graph 未恢复正确拓扑”。
- 下一步需要枚举所有 `/dev/media*`、`v4l-subdev*` 和 dmesg 中的 SC850SL/rkcif/rkisp 注册信息，确认 SC850SL 是移动到了别的 media，还是没有正确注册。

下一步：
- 收集 reboot 后全量 media 拓扑、video-camera symlink、v4l2 device list、subdev 列表和 dmesg 关键词。
- 在 media graph 未恢复为 `rkcif-mipi-lvds4 -> rkisp1-vir1 -> /dev/video71` 前，继续禁止完整 ALPR。

## 2026-07-09 远程 SC850SL media graph probe 分析

来源：
- 本地文件：`RK3588_dev/sc850_media_graph_probe_20250626_105135.tar.gz`
- 解压目录：`RK3588_dev/sc850_media_graph_probe_20250626_105135_extract/sc850_media_graph_probe_20250626_105135`

事实：
- 探针时间为 `2025-06-26 10:51:35 CST`。
- `process.txt` 中只有 `rkaiq_3A_server` 和采集命令，没有 ALPR/http 进程。
- `/dev/video-camera0` 仍指向 `video71`，`v4l2-ctl --list-devices` 仍把 `/dev/video71-77` 归在 `rkisp_mainpath (platform:rkisp1-vir1)`。
- `media7.txt` 仍异常：`rkisp-isp-subdev` pad0 为 `SRGGB8_1X8/800x600`，没有此前成功状态中的 `rkcif-mipi-lvds4 -> rkisp-isp-subdev` 上游输入链路。
- `media3.txt` 是 `rkcif-mipi-lvds4`，但拓扑中没有 `sc850sl 4-0030` 传感器实体接到 `rockchip-csi2-dphy3`。
- `dmesg_camera_grep.txt` 中 `sc850sl 4-0030` 驱动 probe 后报 `Unexpected sensor id(000000), ret(0)`；`sc850sl_2L 5-0030` 和 `sc850sl_2L 7-0030` 也报 `Unexpected sensor id(000000)`。
- dmesg 同时出现 `rkcif-mipi-lvds4: ... get remote terminal sensor failed` 和 `There is not terminal subdev, not synchronized with ISP`。
- dmesg 后续继续出现 `rkisp1-vir1: check rkisp_mainpath link or isp input`。

判断：
- 当前 SC850SL 没有作为 terminal sensor 正确注册进 media graph，导致 `rkcif-mipi-lvds4` 无法同步到 ISP，`/dev/video71` 虽然节点存在但没有有效上游输入。
- 这是传感器识别、供电/复位、I2C、设备树、驱动或物理连接链路问题，不是 ALPR Python、OCR、投票、`--strict-plate-format` 或阈值问题。
- 在 sensor id 恢复正常、media7 拓扑恢复为 SC850SL 4K RAW10 输入到 `rkisp1-vir1` 之前，继续跑完整 ALPR 没有意义。

下一步：
- 优先让远程板做一次真正断电重上电或确认 SC850SL 模组排线、供电、复位状态；单纯软件重启已经不能证明可恢复。
- 若暂时无法物理处理，下一轮只收集 sensor/I2C/sysfs 健康探针和短帧 direct CIF/ISP 自检包，不进入 ALPR。

## 2026-07-09 远程 SC850SL sensor health probe 分析

来源：
- 本地文件：`RK3588_dev/sc850_sensor_health_probe_20250626_110349.tar.gz`
- 解压目录：`RK3588_dev/sc850_sensor_health_probe_20250626_110349_extract/sc850_sensor_health_probe_20250626_110349`

事实：
- 探针时间为 `2025-06-26 11:03:49 CST`。
- `process.txt` 只有 `/usr/bin/rkaiq_3A_server` 和 `logger -t rkaiq`，没有 ALPR/http/v4l2 长时间占用进程。
- `video71_1f_nv12.raw` 仍为 `0` 字节。
- `video71_stream.txt` 显示 `VIDIOC_STREAMON returned -1 (Operation not permitted)`；虽然格式可设为 `3840x2160 NV12`，但 `video71_all.txt` 中 crop/crop_bounds 仍为 `800x600`。
- `i2cdetect_bus4.txt`、`i2cdetect_bus5.txt`、`i2cdetect_bus7.txt` 中 `0x30` 均未响应；只有 bus2 的 `0x10` 为 `UU`。
- `/sys/bus/i2c/devices/4-0030`、`5-0030`、`7-0030` symlink 存在，但这只说明设备树实例存在，不说明实际 sensor 在 I2C 总线上响应。
- `media3.txt` 为 `rkcif-mipi-lvds4`，仅看到 `rockchip-csi2-dphy3 -> rockchip-mipi-csi2`，没有 `sc850sl 4-0030` sensor 实体。
- `media7.txt` 仍为 `rkisp1-vir1` 自身 800x600 默认状态，没有 SC850SL 4K RAW10 上游输入。
- dmesg 再次显示 `sc850sl 4-0030: Unexpected sensor id(000000), ret(0)`，并伴随 `rkcif-mipi-lvds4: ... get remote terminal sensor failed`、`There is not terminal subdev, not synchronized with ISP`。
- 本包 `rkaiq_journal.txt` 中存在晚于 `date.txt` 的历史时间记录，时间线疑似混杂，暂不作为主证据。

判断：
- 本轮已把问题进一步定位到 SC850SL I2C/sensor 端：设备树节点在，但物理总线上的 `0x30` 没有可用响应，driver 读到 sensor id `000000`。
- 这不是完整 ALPR 脚本占用设备导致的，因为本包采集时没有 ALPR 进程。
- 现在最优先检查远程 SC850SL 模组的排线方向、接触、供电、复位脚、模组是否上电，以及实际模组是否与当前设备树/驱动匹配。

下一步：
- 若远程现场可操作，先断电重插/压紧 SC850SL 排线，确认模组供电和 reset，再整板冷启动后重新跑 sensor health probe。
- 如果无法物理操作，下一步只能收集设备树 gpio/regulator 绑定细节和尝试驱动 unbind/bind，但这属于次优路径，且不能替代物理链路确认。

## 2026-07-09 远程 SC850SL sensor health probe 084905 分析

来源：
- 本地文件：`RK3588_dev/sc850_sensor_health_probe_20250626_084905.tar.gz`
- 解压目录：`RK3588_dev/sc850_sensor_health_probe_20250626_084905_extract/sc850_sensor_health_probe_20250626_084905`

事实：
- 探针时间为 `2025-06-26 08:49:05 CST`，接近冷启动后早期状态。
- `process.txt` 只有 `/usr/bin/rkaiq_3A_server` 和 `logger -t rkaiq`，没有 ALPR/http 进程。
- `video71_1f_nv12.raw` 为 `0` 字节。
- `video71_stream.txt` 显示 `VIDIOC_STREAMON returned -1 (Operation not permitted)`。
- `i2cdetect_bus4.txt`、`i2cdetect_bus5.txt`、`i2cdetect_bus7.txt` 中 `0x30` 均未响应；只有 bus2 的 `0x10` 为 `UU`。
- dmesg 中 `sc850sl 4-0030` probe 后仍为 `Unexpected sensor id(000000), ret(0)`，`sc850sl_2L 5-0030`/`7-0030` 也读到 `000000`。
- dmesg 继续出现 `rkcif-mipi-lvds4: ... get remote terminal sensor failed`、`There is not terminal subdev, not synchronized with ISP` 和 `rkisp1-vir1: check rkisp_mainpath link or isp input`。

判断：
- 这包证明冷启动早期 SC850SL 就没有正常 I2C 响应和 sensor id，不是后续 ALPR 进程占用造成。
- `/root/mediamtx` 推流工具可以作为网络/推流链路测试，但在 `0x30` 不响应、`/dev/video71` 不能 stream on 的前提下，它不能修复摄像头，也大概率无法从 SC850SL 推出真实画面。

下一步：
- 若要用 `/root/mediamtx`，先只读打包 `gstPushStream.sh`、`start_4_stream.sh`、`mediamtx.yml` 和日志，确认它的输入源是 `/dev/video71`、其它 video 节点，还是 `stream.h264` 文件。
- 如果输入源是文件，推流成功也不能证明 SC850SL 正常；如果输入源是 `/dev/video71`，当前预期是失败或无画面。

## 2026-07-09 mediamtx probe 分析

来源：
- 本地文件：`RK3588_dev/mediamtx_probe_20250626_085507.tar.gz`
- 解压目录：`RK3588_dev/mediamtx_probe_20250626_085507_extract/mediamtx_probe_20250626_085507`

事实：
- `gstPushStream.sh` 明确使用 `v4l2src device=/dev/video71`，不是推 `stream.h264` 文件。
- pipeline 为 `/dev/video71` 3840x2160 NV12 -> `clockoverlay` -> `mpph264enc` -> `h264parse` -> `rtspclientsink location=rtsp://localhost:8559/video71`。
- `start_4_stream.sh` 会启动 `./mediamtx`，再启动 `gstPushStream.sh`。
- `mediamtx.log` 显示 RTSP 端口为 `8559`，WebRTC 端口为 `8889`，路径包含 `video71`。
- `gst_push.log` 里出现过 `GstV4l2Src` 3840x2160 NV12 caps、H264 caps 和大量 RTP stats，说明该工具曾经至少成功从 `/dev/video71` 推过 H264。
- 本包 `date.txt` 为 `2025-06-26 08:55:07 CST`，但日志中包含更晚时间记录，存在历史日志混杂；不能只凭旧日志判断当前实时状态。

判断：
- mediamtx 工具可以作为“当前 `/dev/video71` 是否还能被 GStreamer 实时打开并推流”的辅助验证。
- 它不能替代 sensor health probe；如果推流成功，需要同步收集当前 `i2cdetect`、media graph、dmesg 和一小段 RTSP 抓流，确认不是旧流/历史日志。
- 若推流能稳定输出真实道路画面，则需要重新评估 `v4l2-ctl` 单帧失败与 GStreamer 成功之间的差异，可能是采集方式/占用/时序问题，而不是摄像头完全离线。

下一步：
- 运行一次受控 mediamtx 实时推流探针：停止旧进程、清空/备份日志、启动推流约 20 秒、抓 process/log/media/i2c/dmesg，并尝试从 `rtsp://127.0.0.1:8559/video71` 保存短 H264 或截图。
- 探针结束后停止 mediamtx/gst，避免长期占用 `/dev/video71`。

## 2026-07-09 mediamtx live probe 分析

来源：
- 本地文件：`RK3588_dev/mediamtx_live_probe_20250626_090155.tar.gz`
- 解压目录：`RK3588_dev/mediamtx_live_probe_20250626_090155_extract/mediamtx_live_probe_20250626_090155`

事实：
- `mediamtx_live.log` 显示 mediamtx 在 `09:01:57` 正常启动，RTSP 监听 `:8559`。
- `gst_push_live.log` 显示 `v4l2src device=/dev/video71` 启动后失败：`Internal data stream error`，`streaming stopped, reason not-negotiated (-4)`。
- `rtsp_pull_8s.h264` 为 `0` 字节。
- `rtsp_pull.log` 显示拉流失败，mediamtx 返回 `Not Found (404)`，服务端日志为 `no stream is available on path 'video71'`。
- 推流前后 `i2cdetect` 中 bus4/bus5/bus7 的 `0x30` 仍未响应。
- 推流前后 `media7` 均为 `SRGGB8_1X8/800x600`，没有 SC850SL 4K RAW10 上游输入。
- 推流前后 `video71_all` crop/crop_bounds 均为 `800x600`。
- dmesg 继续包含 `sc850sl ... Unexpected sensor id(000000)`、`get remote terminal sensor failed`、`There is not terminal subdev, not synchronized with ISP`。

判断：
- 受控实时验证确认当前 mediamtx/GStreamer 不能从 `/dev/video71` 发布可拉取的实时流。
- 之前 `gst_push.log` 中的成功 H264/RTP 记录是历史成功证据，不能代表当前摄像头在线。
- 当前结论回到 SC850SL sensor/I2C/media graph 未恢复；不是 ALPR、不是 Python，也不是单纯 `v4l2-ctl` 工具差异。

下一步：
- 不再用 mediamtx 继续试探 `/dev/video71`，除非先恢复 SC850SL `0x30` I2C 响应和 media graph。
- 远程现场应优先确认 SC850SL 是否实际连接、排线方向/压紧、供电、reset/pwdn、接口位置和模组型号是否匹配设备树。
## 2026-07-09 SC850 文件版本盘点包分析

来源：
- 本地文件：`RK3588_dev/sc850_file_versions_20250626_092450.tar.gz`
- 解压目录：`RK3588_dev/sc850_file_versions_20250626_092450_extract/sc850_file_versions_20250626_092450`

事实：
- 远端 `/root/alpr_topk_rk3588/` 只发现当前两个候选文件：`rk3588_topk_capture_mipi_debug_sc850.py` 和 `sc850_video71_vehicle_probe_collect.sh`。
- 远端包内未发现 `.bak`、`.old` 或其他可直接回退的 SC850 专用旧版文件。
- 远端当前 `rk3588_topk_capture_mipi_debug_sc850.py` SHA256 为 `eb23c2df4ed89d2066d08c2655b65617cfbb5a636a9dac80eccba6be3e0f97f9`，与本地根目录当前文件一致。
- 远端当前 `sc850_video71_vehicle_probe_collect.sh` SHA256 为 `1307fe364ba6bf559ad0bc6f6386d1a0ec7f8150524110d5e7a83893f2f967b7`，与本地 `RK3588_dev/sc850_video71_vehicle_probe_collect.sh` 一致。
- 本地离线包 `RK3588_dev/offline_bundle/rk3588_alpr_roadtest_bundle_20260701/alpr_topk_rk3588/` 只有通用 `rk3588_topk_capture.py` 和 `rk3588_topk_capture_mipi_debug.py`，没有 `rk3588_topk_capture_mipi_debug_sc850.py` 或 `sc850_video71_vehicle_probe_collect.sh`。
- 当前 SC850 脚本里的 `--strict-plate-format` 默认值为 false；采集 sh 里的 `STRICT_PLATE_FORMAT` 默认值为 `0`。因此不显式开启时，严格车牌格式保护不会参与 vote/lock。

判断：
- 当前没有可证明的“原始 SC850 旧版”能直接原样恢复。
- 如果要排除“换 sh/换 SC850 脚本导致异常”的疑点，只能做可控的旧行为验证或从通用 MIPI 脚本重新派生测试副本，不能把它称为完整回退。
- 现有 sensor health、media graph、mediamtx live 证据仍然指向 SC850SL sensor/I2C/media graph 异常；这些探针不依赖 SC850 ALPR 主脚本，因此不能用 ALPR 脚本变化解释 `0x30` 不响应、`sensor id(000000)` 和 `media7` 无上游输入。

下一步：
- 不覆盖当前远端文件。
- 若用户坚持试“改回去”，优先让板端先备份当前两个文件，再做旧行为短测：显式 `STRICT_PLATE_FORMAT=0`，并只跑短帧/短超时验证是否仍然卡在 `/dev/video71` 出帧层。
## 2026-07-09 旧行为短测 093419 分析

来源：
- 外层包：`RK3588_dev/sc850_old_behavior_short_probe_20250626_093419.tar.gz`
- 内层包：`RK3588_dev/sc850_video71_vehicle_probe_20250626_093419.tar.gz`
- 解压目录：
  - `RK3588_dev/sc850_old_behavior_short_probe_20250626_093419_extract/sc850_old_behavior_short_probe_20250626_093419`
  - `RK3588_dev/sc850_video71_vehicle_probe_20250626_093419_extract/sc850_video71_vehicle_probe_20250626_093419`

事实：
- 本轮显式 `STRICT_PLATE_FORMAT=0`，`run_summary.json` 中 `strict_plate_format=false`。
- 主脚本哈希仍为 `eb23c2df4ed89d2066d08c2655b65617cfbb5a636a9dac80eccba6be3e0f97f9`，采集 sh 哈希仍为 `1307fe364ba6bf559ad0bc6f6386d1a0ec7f8150524110d5e7a83893f2f967b7`。
- `run_summary.json` 存在，但 `frames_processed=0`、`track_count=0`、`elapsed_seconds=0.077`。
- `alpr_vehicle_probe.log` 只显示 MIPI capture 初始化和 RKNN 模型加载，随后直接保存空 run。
- `/dev/video71` 单帧 raw 仍为 `0` 字节。
- `video71_1f_nv12_stream.txt` 显示 `VIDIOC_STREAMON returned -1 (Operation not permitted)`。
- `/dev/video71 --list-formats-ext` 当前只列出 `32x32 - 800x600` stepwise 范围；`video71_all.txt` 虽显示可设为 `3840x2160 NV12`，但 crop/crop_bounds 仍为 `800x600`。
- `media_media7.txt` 仍是 `rkisp1-vir1` 自身 800x600，无 `rkcif-mipi-lvds4` 上游输入。
- `dmesg_after.txt` 仍出现 `rkisp1-vir1: check rkisp_mainpath link or isp input`。
- 新发现：`/dev/video-camera0 -> video53`，不是此前目标 `/dev/video71`。
- `media_media5.txt` 显示 `/dev/media5 -> rkisp0-vir2` 存在 `rkcif-mipi-lvds2 -> rkisp-isp-subdev` 的 `SRGGB12_1X12/3840x2160` enabled 链路。

判断：
- “旧行为短测”已经排除 `STRICT_PLATE_FORMAT=1` 或锁牌策略导致本轮 `/dev/video71` 无帧的可能。
- 当前 `/dev/video71` 仍不是有效 4K NV12 主链路；问题在视频节点/media graph/传感器链路层，不在 OCR 或 vote。
- `/dev/video-camera0` 指向 `video53` 是新线索，说明当前系统默认 camera 节点可能已经切到另一条 ISP mainpath；需要做多节点探针确认哪个 video 节点当前能真实出帧。
- 暂不能直接把最终主线改成 `/dev/video53`，因为此前决策中 `/dev/video53` 被判断为非 SC850SL 链路；但必须重新验证当前远端实际节点映射。

下一步：
- 让远端板端执行多 video 节点探针，至少覆盖 `/dev/video33`、`/dev/video44`、`/dev/video53`、`/dev/video71`、`/dev/video72`，同时打包 `v4l2-ctl --list-devices`、全量 media graph、i2cdetect、单帧 raw 大小和 dmesg。
- 若 `/dev/video53` 可稳定输出 3840x2160 NV12，再决定是否临时把 SC850 实时识别输入从 `/dev/video71` 切到 `/dev/video53` 做验证。
## 2026-07-09 用户确认 `/dev/video71` 仍是 SC850SL ISP 主端口

事实：
- 用户明确确认：远程 SC850SL 的 ISP 处理后目标端口就是 `/dev/video71`。
- 因此上一轮分析中发现的 `/dev/video-camera0 -> video53` 只能作为系统默认 symlink 或旁路对照线索，不能作为切换主线依据。

修正判断：
- 不再把“重新选择最终输入节点”作为当前主方向。
- 当前主方向应表述为：`/dev/video71` 这个目标 ISP 端口存在，但它当前的上游 sensor/media graph/ISP input 没有恢复到可出帧状态。
- `/dev/video53` 如需检查，只能用于对照“系统里是否还有其他 ISP 链路正常”，不能替代 SC850SL `/dev/video71` 主线。

下一步：
- 聚焦 `/dev/video71` 的上游链路：SC850SL sensor probe、I2C 0x30、`rkcif-mipi-lvds4`、`rkisp1-vir1/media7`、rkaiq 对 media7 的启动事件。
## 2026-07-09 video71 upstream probe 094644 分析

来源：
- 本地文件：`RK3588_dev/sc850_video71_upstream_probe_20250626_094644.tar.gz`
- 解压目录：`RK3588_dev/sc850_video71_upstream_probe_20250626_094644_extract/sc850_video71_upstream_probe_20250626_094644`

事实：
- `/dev/video71` 是 `rkisp_mainpath (platform:rkisp1-vir1)`，仍是目标 ISP 输出端口。
- `video71_stream_tests.txt` 中 3840x2160 NV12 和 800x600 NV12 两次测试均为 `VIDIOC_STREAMON returned -1 (Operation not permitted)`，两个 raw 文件均为 0 字节。
- `video71_all_before.txt` 显示 `/dev/video71` 可设为 3840x2160 NV12，但 crop/crop_bounds 为 800x600。
- `video71_formats_before.txt` 当前枚举范围只到 `32x32 - 800x600`。
- `media7.txt` 中 `rkisp1-vir1` 的 `rkisp-isp-subdev` pad0 为 `SRGGB8_1X8/800x600`，无 `rkcif-mipi-lvds4` 或 SC850SL 上游输入链路。
- `media3.txt` 中 `rkcif-mipi-lvds4` 存在，并连接到 `rockchip-csi2-dphy3 -> rockchip-mipi-csi2`，但 media graph 中没有 `sc850sl 4-0030` terminal sensor 实体接入。
- `i2cdetect_bus4.txt`、`i2cdetect_bus5.txt`、`i2cdetect_bus7.txt` 中 `0x30` 均无响应。
- sysfs 中存在 `/sys/bus/i2c/devices/4-0030`、`5-0030`、`7-0030`，并已绑定到对应 driver；这说明设备树实例和 driver binding 存在，但不证明硬件 I2C 正常响应。
- dmesg 明确显示：
  - `sc850sl 4-0030: Unexpected sensor id(000000), ret(0)`
  - `sc850sl_2L 5-0030: Unexpected sensor id(000000), ret(-5)`
  - `sc850sl_2L 7-0030: Unexpected sensor id(000000), ret(-5)`
  - `rkcif-mipi-lvds4: rkcif_update_sensor_info: stream[0] get remote terminal sensor failed`
  - `rkcif-mipi-lvds4: There is not terminal subdev, not synchronized with ISP`
  - stream 后新增 `rkisp1-vir1: check rkisp_mainpath link or isp input`
- dmesg 中 `sc850sl 4-0030` 的 reset GPIO 为 `gpio-39 (reset)`；同时日志显示缺少 power GPIO 和 dvdd/dovdd/avdd regulator，被 dummy regulator 替代。

判断：
- `/dev/video71` 本身不是 ALPR 层问题；它失败的直接原因是 `rkisp1-vir1` 没有有效上游 ISP input。
- 更上游的根因链条是：SC850SL sensor 未读出有效 ID -> rkcif-mipi-lvds4 无 terminal sensor -> media7/rkisp1-vir1 退回 800x600 默认状态 -> video71 streamon 失败。
- 当前证据强烈指向 SC850SL 物理连接、供电、reset/pwdn、电源 rail、I2C 总线或设备树硬件描述问题。
- 因为设备树/driver binding 已存在但 `0x30` 不响应，所以“文件回退、OCR、vote、采集脚本参数”都不是当前主矛盾。

下一步：
- 如果现场可操作，优先断电重插/压紧 SC850SL 模组，确认模组供电、reset/pwdn、电源板和接口位置。
- 如果只能远程继续，下一轮先做只读的设备树、GPIO、regulator、pinctrl、clock 探针，确认 `4-0030` 的 reset/power/supply 描述和实际 GPIO 状态，不直接 toggle reset。
## 2026-07-09 DT/GPIO/power probe 095237 分析

来源：
- 本地文件：`RK3588_dev/sc850_dt_gpio_power_probe_20250626_095237.tar.gz`
- 解压目录：`RK3588_dev/sc850_dt_gpio_power_probe_20250626_095237_extract/sc850_dt_gpio_power_probe_20250626_095237`

事实：
- `sc850sl-4@30` 设备树节点存在，compatible 为 `smartsens,sc850sl`，I2C 地址 `reg=0x30`，有 `xvclk`、`pinctrl-0`、`power-domains`、`reset-gpios`、module index/name/lens/facing 等属性。
- `sc850sl-4@30` 的 `reset-gpios` 为 phandle `0x129`、offset `7`、flag `1`。dmesg 对应显示 `gpio-39 (reset)`。
- `sc850sl-1@30` 和 `sc850sl-2@30` 也存在，compatible 为 `smartsens,sc850sl_2L`，reset offset 分别为 `8`、`9`，dmesg 对应 `gpio-40`、`gpio-41`。
- 三个 SC850 节点均未在当前设备树文本中看到 `power-gpios`，dmesg 明确打印 `No GPIO consumer power found` 和 `Failed to get power_gpios`。
- 三个 SC850 节点均未绑定真实 `dvdd`、`dovdd`、`avdd` regulator，dmesg 显示均为 `supply ... not found, using dummy regulator`。
- `i2cdetect` 在 bus4/bus5/bus7 仍均看不到 `0x30`。
- `debug_gpio.txt` 里可见一个名为 `reset` 的 GPIO 为 `out lo ACTIVE LOW`。它与 dmesg 的 SC850 reset GPIO 映射关系高度相关，但由于 debugfs 输出只显示一个 `reset` 名称，具体对应 `gpio-39/40/41` 仍需进一步只读解析，待确认。
- `clk_summary.txt` 显示 `clk_mipi_camaraout_m1` 有引用计数痕迹，其他 mipi camera out 多数为 0；但 sensor probe 失败后 clock 状态可能已被释放，不能单独作为根因。
- regulator 列表中存在系统级 1.8V/3.3V/1.2V 等 regulator，但没有看到明确命名为 SC850/camera dvdd/dovdd/avdd 的专用供电绑定。

判断：
- 当前不是“没有设备树节点”或“driver 没绑定”，而是设备树实例存在、driver 尝试 probe，但硬件 I2C 读不到有效 sensor id。
- 缺少 power-gpios 和真实 dvdd/dovdd/avdd supply 可能是板级设计采用常供电，也可能是设备树缺失；需要结合硬件原理图/模组供电确认，不能直接下结论。
- reset GPIO active-low 且 debugfs 中存在 `out lo ACTIVE LOW` 的 reset 信号是高优先级疑点：若该线对应 SC850SL 且物理电平保持低，则可能让 sensor 一直处于 reset；但对应关系和有效极性需进一步确认，不能直接远程 toggle。

下一步：
- 继续做只读 deep DT/phandle/pinctrl/endpoint 探针，解析 phandle `0x129`、pinctrl phandle、port/endpoint 和 dphy/csi2/rkcif/rkisp 连接。
- 不做 GPIO toggle、unbind/bind 或设备树覆盖，除非用户确认愿意承担状态改变风险。
## 2026-07-09 deep DT/phandle probe 095747 分析

来源：
- `RK3588_dev/sc850_deep_dt_phandle_probe_20250626_095747.tar.gz`
- 解压目录：`RK3588_dev/sc850_deep_dt_phandle_probe_20250626_095747_extract/sc850_deep_dt_phandle_probe_20250626_095747`

事实：
- `sc850sl-4@30` 节点存在于 `i2c@feac0000`，`compatible=smartsens,sc850sl`，`reg=0x30`，endpoint `data-lanes=1 2 3 4`。
- `sc850sl-4@30/port/endpoint` 的 phandle 为 `0x37`，remote-endpoint 为 `0x15f`；`0x15f` 是 `csi2-dphy3/ports/port@0/endpoint@1`，并反向指回 `0x37`。
- `sc850sl-4@30` 的 `reset-gpios=<0x129 7 1>`；`0x129` 是 gpio1 控制器，dmesg 解析为 `gpio-39 (reset)`。
- `sc850sl-4@30` 的 `pinctrl-0=0x15e`，对应 `mipim0-camera2-clk`；`feac0000.i2c` 当前 pinctrl 使用 `i2c4m3-xfer`。
- bus4/bus5/bus7 的 `i2cdetect` 均无 `0x30`。
- dmesg 仍显示 `sc850sl 4-0030: Unexpected sensor id(000000), ret(0)`，并显示缺少 `power-gpios`，`dvdd/dovdd/avdd` 使用 dummy regulator。
- `media3` 中有 `rkcif-mipi-lvds4`、`rockchip-csi2-dphy3 -> rockchip-mipi-csi2`，但没有成功注册的 `sc850sl 4-0030` sensor entity。
- `media7` 仍为 `rkisp1-vir1` 自身 800x600 状态，`/dev/video71` 仍没有 SC850SL 4K 上游输入。
- `debug_gpio.txt` 中可见一个 `reset out lo ACTIVE LOW`，但该行显示为 `gpio-38`；dmesg 对 SC850SL-4 的 reset 解析为 `gpio-39`，两者关系仍需谨慎确认，不能直接等同。

判断：
- 当前不优先怀疑 `sc850sl-4@30` 到 `csi2-dphy3` 的 endpoint phandle 完全写错；这条设备树连接描述基本能对上。
- 当前主嫌疑继续收敛到 SC850SL 模组物理连接、供电、reset/pwdn、I2C 硬件响应或板级电源/设备树供电绑定。
- 在 `0x30` 未恢复响应、sensor id 未读出、terminal sensor 未进入 media graph 前，不运行完整 ALPR，不继续调 OCR 或锁牌阈值。

下一步：
- 优先让远程现场断电后重插/压紧 SC850SL 模组，确认排线方向、接口位置、供电、reset/pwdn 和模块型号，再冷启动。
- 冷启动后只跑短的 sensor health/upstream probe，确认 `i2cdetect` 是否出现 `0x30`、dmesg 是否不再是 `sensor id(000000)`、`media7` 是否恢复 SC850SL 4K 上游。
- 不做 reset GPIO toggle、driver unbind/bind 或设备树 overlay，除非用户明确确认愿意承担状态改变风险。
