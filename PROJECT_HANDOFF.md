# YOLO_ALPR_Project 项目交接文档

更新时间：2026-06-26

本文档用于长期维护和新对话交接。目标是让后续对话能够直接接手当前项目状态，不需要重新解释过去已经做过的判断、实验和文件结构。

## 1. 项目最终目标

本项目的最终目标是实现一个适合高速路固定摄像头场景的中文车牌识别系统，并最终部署到 RK3588 板端实地运行。

核心目标可以拆成四层：

1. 在 `D:\YOLO_ALPR_Project\测试图\14.mp4` 这种高速路监控场景中，尽可能准确识别车辆车牌。
2. 在视频中检测到车牌号后，将车牌号显示在对应车辆上方，并且随着车辆移动持续跟随。
3. 一旦某辆车的车牌号被确认锁定，就不再对这辆车继续做 OCR 或车牌检测，只保留车辆跟踪和文字显示，以减少算力。
4. Windows 端用于算法验证和 A/B 测试，RK3588 板端用于最终实时部署和实地测试。

一句话版本：

> 锁定前识别，锁定后不再识别，只跟踪车辆并持续显示已锁定车牌号。

注意：`不 OCR` 模式只是诊断模式，不是最终目标。最终目标不是显示 `PLATE`，而是显示真实车牌号。

## 2. 当前总体结论

### 2.1 图片识别路线

早期图片识别方案是 `test_image2.py`。其中 TinyUNet 模块来源于 `D:\YOLO_ALPR_Project\论文\22404.13677v2` 相关论文。

这个方案的问题：

- 对论文对应数据集 `D:\YOLO_ALPR_Project\Dataset\dataset` 表现较好。
- 对真实高速路视频中截出来的模糊车牌不够鲁棒。
- 当前不再把 TinyUNet 作为唯一方向，后续允许训练全新的轻量中文车牌恢复模型。

### 2.2 视频识别路线

早期视频识别方案是 `alpr_sahi_snapshot2.py`。

它的问题：

- 能从视频中截取车辆和车牌，但车牌图像经常很糊。
- 例如 `D:\YOLO_ALPR_Project\captures\1_JC52IG_fallback_plate.jpg` 中汉字部分糊成一团。
- 单帧 fallback 质量不稳定，因此改为 Top-K 候选抽取，从同一辆车的多个时刻中挑更好的车牌帧。

### 2.3 当前主线

当前主线不是先训练恢复模型，而是先把视频候选抽取、OCR 投票、锁定后跟踪显示打通。

主线流程：

1. YOLO 车辆检测。
2. 车辆 tracker 分配 `track_id`。
3. 对未锁定车辆进行车牌 OBB 检测。
4. 透视拉正车牌到 `320x96`。
5. 对车牌候选打质量分并保存 Top-K。
6. 对候选进行 OCR 和投票。
7. 车牌号锁定后缓存 `locked_text`。
8. 后续帧只跟踪车辆并显示 `locked_text`，不再对该车 OCR。

### 2.4 当前推荐 OCR

已尝试多种 OCR：

- PaddleOCR：启动和推理慢，对模糊小车牌不理想。
- plate-rec / plate-rec-cv2 / plate-rec-ort：能跑，但 raw OCR 经常出现泛中文乱码。
- HyperLPR3：目前中文车牌识别结果相对最好，后续主推。

当前推荐：

- Windows 端和 RK 端优先使用 `hyperlpr3`。
- 但不要无脑对每个全车 crop 高频 OCR。全车 OCR 有时会带来噪声票。

### 2.5 当前 tracking 判断

当前 RK 端不是官方 ByteTrack。

目前使用的是轻量 IoU / 中心距离 / 尺度匹配风格的自写 tracker，并逐步加入了：

- track 最大丢失帧数。
- 中心距离阈值。
- 锁定后预测显示。
- 车牌相对车辆框锚点。

为什么没有直接上 ByteTrack：

- RK 端当前主要瓶颈不只是 tracker，而是车辆检测、车牌 OBB 命中次数少、OCR 有效票数少。
- ByteTrack 对检测结果质量仍然有依赖，不能直接解决 OBB 少和 OCR 少的问题。
- 当前场景是固定高速路摄像头，车辆运动方向比较稳定，轻量 tracker + 车辆框预测 + 车牌锚点更适合先验证。

后续如果轻量 tracker 仍不稳，可以再引入 ByteTrack 或 OC-SORT 风格重关联。

## 3. 当前远程环境

Codex 当前已经可以通过 SSH 直接远程访问 Ubuntu 开发机和 RK3588 板子。

### 3.1 Ubuntu 开发机

- IP：`192.168.217.128`
- 用户名：`apple`
- 系统：Ubuntu 22.04.5 LTS
- 架构：x86_64
- 已验证 SSH 可连接

连接命令：

```powershell
ssh apple@192.168.217.128
```

### 3.2 RK3588 板子

- IP：`192.168.137.168`
- 用户名：`root`
- 系统：Debian/Linux aarch64，主机名类似 `linaro-alip`
- 已配置 Windows 到板端 SSH 免密登录
- 板端视频 `144.mp4` 和 Windows 端 `14.mp4` 内容相同

连接命令：

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

Windows 对应视频：

```text
D:\YOLO_ALPR_Project\测试图\14.mp4
```

### 3.3 板端实时画面

板端运行：

```bash
cd /root/deploy
python3 stream.py
```

Windows 浏览器打开：

```text
http://192.168.137.168:8080
```

如果程序正在更新 `/tmp/frame.jpg`，浏览器可以看到实时画面。

## 4. 工作区文件结构

项目根目录：

```text
D:\YOLO_ALPR_Project
```

当前重要目录：

```text
D:\YOLO_ALPR_Project
  .git
  .venv
  blur models
  captures
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
  RK3588
  RK3588_dev
  Ultralytics
  测试图
  论文
  汇报
```

## 5. 关键脚本和文件作用

### 5.1 Windows 视频识别和 Top-K

#### `alpr_topk_capture.py`

路径：

```text
D:\YOLO_ALPR_Project\alpr_topk_capture.py
```

作用：

- Windows 主线 Top-K 车牌候选抽取脚本。
- 复用 `YOLO(yolo11n.pt)` 检测车辆。
- 复用 `YOLO(best_obb.pt)` 检测车牌 OBB。
- 按车辆 track 维护状态。
- 每辆车保存 Top-K 车牌候选。
- 支持 OCR 投票。
- 支持实时弹窗显示。

当前状态：

- 已恢复为主线版本。
- 不要随意修改它。
- 如果要验证新功能，优先复制到 demo 脚本中改。

#### `alpr_topk_capture_demo.py`

路径：

```text
D:\YOLO_ALPR_Project\alpr_topk_capture_demo.py
```

作用：

- Windows 验证副本。
- 当前已经被恢复成与 `alpr_topk_capture.py` 完全一致的干净副本。
- 用于后续实验，不污染主脚本。

#### `topk_report.py`

路径：

```text
D:\YOLO_ALPR_Project\topk_report.py
```

作用：

- 根据 Top-K 输出目录生成 HTML 报告。
- 可以复跑 OCR。
- 可以查看每辆车的 Top-K plate、vehicle crop、OCR、分数、拒绝原因等。

#### `ocr_compare_topk.py`

路径：

```text
D:\YOLO_ALPR_Project\ocr_compare_topk.py
```

作用：

- 对已有 Top-K 输出结果跑不同 OCR 引擎。
- 用于比较 plate-rec、plate-rec-cv2、plate-rec-ort、HyperLPR3 等 OCR 效果。

### 5.2 RK3588 板端脚本

#### `rk3588_topk_capture.py`

路径：

```text
D:\YOLO_ALPR_Project\rk3588_topk_capture.py
```

板端对应路径通常为：

```bash
/root/alpr_topk_rk3588/rk3588_topk_capture.py
```

作用：

- RK3588 板端主推理脚本。
- 使用 RKNN 车辆模型和车牌 OBB 模型。
- 支持视频输入和 MIPI 摄像头输入。
- 支持发布实时帧到 `/tmp/frame.jpg`，由 `stream.py` 浏览器展示。
- 支持锁定车牌后跳过该 track 的车牌检测和 OCR。
- 当前优化重点。

当前状态：

- 仍处于实验优化状态。
- git 中显示 modified。
- 主要围绕 RK 端 tracking、OCR 投票、plate hit 增加和实时显示优化。

#### `rk3588_mipi_isp_probe.py`

路径：

```text
D:\YOLO_ALPR_Project\rk3588_mipi_isp_probe.py
```

作用：

- 排查 RK3588 MIPI 摄像头颜色异常。
- 用于检查不同 video node、pixel format、gray-world 白平衡、ISP/3A 状态。

### 5.3 OCR 封装

#### `hyperlpr3_ocr.py`

路径：

```text
D:\YOLO_ALPR_Project\hyperlpr3_ocr.py
```

作用：

- HyperLPR3 OCR 封装。
- 当前 OCR 效果相对最好。

#### `plate_rec_ocr.py`

路径：

```text
D:\YOLO_ALPR_Project\plate_rec_ocr.py
```

作用：

- plate-rec 系列 OCR 封装。
- 支持不同后端尝试。
- 当前 git 中显示 modified。
- 之前 plate-rec raw OCR 出现较多泛中文乱码，因此不是当前主推。

### 5.4 OBB 数据集和训练

#### `prepare_obb_finetune_dataset.py`

路径：

```text
D:\YOLO_ALPR_Project\prepare_obb_finetune_dataset.py
```

作用：

- 构建车牌 OBB 微调数据集。
- 整合 CCPD、CRPD 等数据。
- 输出 `plate_dataset_obb_finetune`。

#### `train_obb_colab.py`

路径：

```text
D:\YOLO_ALPR_Project\train_obb_colab.py
```

作用：

- Colab 上微调 `best_obb.pt`。
- 已根据需要改为先跑 20 轮。

#### `best_obb.pt`

路径：

```text
D:\YOLO_ALPR_Project\best_obb.pt
```

作用：

- 原始车牌 OBB 检测模型。

#### `best_obb_finetuned_e8.pt`

路径：

```text
D:\YOLO_ALPR_Project\best_obb_finetuned_e8.pt
```

作用：

- Colab 训练 8 轮后的 OBB 微调模型。

#### `best_obb_finetuned_e20.pt`

路径：

```text
D:\YOLO_ALPR_Project\best_obb_finetuned_e20.pt
```

作用：

- Colab 训练 20 轮后的 OBB 微调模型。
- 后续需要转换 RKNN 后和原始 `best_obb.rknn` 做 A/B 测试。

### 5.5 去模糊数据集和训练

#### `prepare_deblur_dataset.py`

路径：

```text
D:\YOLO_ALPR_Project\prepare_deblur_dataset.py
```

作用：

- 去模糊数据集 v1 构建脚本。

#### `prepare_deblur_dataset_v2.py`

路径：

```text
D:\YOLO_ALPR_Project\prepare_deblur_dataset_v2.py
```

作用：

- 去模糊数据集 v2 构建脚本。
- 使用 CCPD/CRPD/OBB 裁剪出的清晰车牌作为 sharp。
- 合成更贴近高速路监控视频的模糊退化。
- 输出训练、验证、测试数据，以及 manifest 和 preview。

#### `train_deblur_colab.py`

路径：

```text
D:\YOLO_ALPR_Project\train_deblur_colab.py
```

作用：

- Colab 上训练轻量车牌去模糊模型。
- 输出 PyTorch 权重和 ONNX。

#### `test_deblur_image.py`

路径：

```text
D:\YOLO_ALPR_Project\test_deblur_image.py
```

作用：

- 用现有去模糊模型测试静态图片。

#### `COLAB_DEBLUR_V2_E20_STEPS.md`

路径：

```text
D:\YOLO_ALPR_Project\COLAB_DEBLUR_V2_E20_STEPS.md
```

作用：

- Colab 训练去模糊 v2 模型 20 轮的详细步骤。

### 5.6 原始和辅助脚本

#### `test_image.py`

早期图片测试脚本。

#### `test_image2.py`

早期 TinyUNet 图片增强与识别脚本。

#### `alpr_sahi_snapshot.py`

早期视频识别脚本。

#### `alpr_sahi_snapshot2.py`

早期主要视频识别脚本，后续被 Top-K 方案替代。

#### `main.py`

项目中早期或辅助入口脚本。

#### `build_alpr_demo_report.py`

用于生成演示和汇报文档。

#### `annotate_obb_review.py`

用于 OBB 标注复查。

#### `export_obb_review_pack.py`

用于导出 OBB hardcase 复查包。

## 6. 数据集结构

数据集根目录：

```text
D:\YOLO_ALPR_Project\Dataset
```

当前重要数据集：

```text
Dataset
  CCPD2020
  CRPD_double
  CRPD_multi
  CRPD_single
  dataset
  MDLP_Mini
  obb_hardcase_review
  plate_dataset_mini
  plate_dataset_obb_finetune
  plate_deblur_dataset_v1
  plate_deblur_dataset_v2
  plate_deblur_dataset_v2_smoke
```

重要压缩包：

```text
Dataset\CCPD2020.zip
Dataset\CRPD_all.zip
Dataset\dataset.zip
Dataset\MDLP_Mini.zip
Dataset\MDLP_Standard.zip
Dataset\plate_dataset.zip
Dataset\plate_dataset_mini.zip
Dataset\plate_dataset_obb_finetune.zip
Dataset\plate_deblur_dataset_v1.zip
Dataset\plate_deblur_dataset_v2.zip
```

### 6.1 `dataset`

路径：

```text
D:\YOLO_ALPR_Project\Dataset\dataset
```

说明：

- 来源于 TinyUNet 相关论文。
- 适合论文中的 paired 场景。
- 对真实视频模糊不一定泛化。

### 6.2 `MDLP_Mini`

路径：

```text
D:\YOLO_ALPR_Project\Dataset\MDLP_Mini
```

说明：

- 来自论文 `4 LP-Diff_Towards_Improved_Restoration_of_Real-World_Degraded_License_Plate`。
- 论文中 blur 更像多种不同尺寸/退化版本，sharp 是原图。
- 不能简单理解为严格一一对应的 paired 数据。

### 6.3 `plate_dataset_obb_finetune`

路径：

```text
D:\YOLO_ALPR_Project\Dataset\plate_dataset_obb_finetune
```

说明：

- OBB 微调数据集。
- 整合了 CCPD、CRPD 等数据。
- 已生成 zip，方便上传 Colab。

### 6.4 `plate_deblur_dataset_v2`

路径：

```text
D:\YOLO_ALPR_Project\Dataset\plate_deblur_dataset_v2
```

说明：

- 当前推荐的去模糊训练数据集。
- 目标不是通用超分，而是贴近 `14.mp4` 的真实模糊车牌。
- 输出固定 `320x96`。
- 已生成 zip，可用于 Colab 训练。

## 7. 模型文件

### 7.1 Windows 模型

```text
D:\YOLO_ALPR_Project\yolo11n.pt
D:\YOLO_ALPR_Project\best_obb.pt
D:\YOLO_ALPR_Project\best_obb_finetuned_e8.pt
D:\YOLO_ALPR_Project\best_obb_finetuned_e20.pt
```

用途：

- `yolo11n.pt`：车辆检测。
- `best_obb.pt`：原始车牌 OBB。
- `best_obb_finetuned_e8.pt`：8 轮微调 OBB。
- `best_obb_finetuned_e20.pt`：20 轮微调 OBB。

### 7.2 RK3588 相关模型

路径：

```text
D:\YOLO_ALPR_Project\RK3588_dev
```

重要文件：

```text
vehicle.rknn
plate_obb.rknn
plate_rec.rknn
yolo11n.onnx
best_obb.onnx
plate_rec.onnx
```

说明：

- `vehicle.rknn`：板端车辆检测模型。
- `plate_obb.rknn`：板端车牌 OBB 模型。
- `plate_rec.rknn`：板端 OCR 相关模型。
- 后续需要把 `best_obb_finetuned_e20.pt` 转 ONNX 再转 RKNN，用于板端 A/B 测试。

## 8. 已做过的重要尝试

### 8.1 从单帧 fallback 改为 Top-K

问题：

- 单帧 fallback 的车牌经常糊。
- 如果只拿一帧识别，很容易错过视频里更清楚的瞬间。

尝试：

- 新建 `alpr_topk_capture.py`。
- 对每辆车维护 Top-K 候选。
- 保存 full frame、vehicle crop、plate crop、summary.json。

结论：

- Top-K 能找到比 fallback 更清楚的帧。
- 这是后续视频识别的基础。

### 8.2 质量评分

质量分包含：

- plate_area_score：车牌原始四边形面积。
- sharpness_score：Laplacian 方差。
- exposure_score：过曝/过暗比例。
- contrast_score：灰度标准差。
- obb_score：车牌检测置信度。

默认权重：

```text
0.35 * plate_area_score
0.30 * sharpness_score
0.15 * exposure_score
0.10 * contrast_score
0.10 * obb_score
```

结论：

- 视觉质量排序有帮助。
- 但清晰度分不一定等价于 OCR 正确率，后续需要结合 OCR 投票。

### 8.3 官方 tracker 和 lap

曾讨论 Ultralytics 官方 ByteTrack 需要 `lap` 依赖。

安装中遇到：

- `lap` 可安装。
- 但 pip dependency resolver 提示 PaddleOCR 和 OpenCV 版本冲突。

结论：

- 依赖可以装，但不优先作为当前 RK 主线。
- 当前采用轻量 tracker 是为了控制板端复杂度。

### 8.4 HyperLPR3 OCR

安装 HyperLPR3 后，发现：

- HyperLPR3 对中文车牌比 plate-rec 更靠谱。
- 有时多次识别结果不一致，需要投票。
- 全车 OCR 可以识别，但容易引入噪声。

结论：

- HyperLPR3 当前是 OCR 主推。
- 但需要“候选质量控制 + 投票”，不能只看单次识别。

### 8.5 投票机制

尝试过：

- exact text 投票。
- vote window。
- vote threshold。
- OCR confidence threshold。
- 字符级加权投票。
- vote_history 记录。

结论：

- 投票机制必要。
- 但当前仍存在一些车的 OCR 票数少、字符不稳定的问题。

### 8.6 locked-track re-association

曾尝试加入 locked-track re-association，用于断轨后重新绑定已锁定车辆。

问题：

- 效果不满意。
- 可能引入额外复杂性和错误关联。

当前处理：

- Windows 主线 `alpr_topk_capture.py` 已恢复。
- `alpr_topk_capture_demo.py` 也已恢复成主线干净副本。
- 后续如继续验证，应另开 demo 或只在 RK 脚本中谨慎做。

### 8.7 no-OCR 诊断模式

曾做过 `ocr-engine none` 和 `lock-on-plate-detect` 诊断。

目的：

- 判断如果不 OCR，只要检测到车牌后直接锁定，速度和跟随是否会变好。

结论：

- 这只是诊断。
- 它只能显示 `PLATE`，不是最终目标。
- 最终仍然要 OCR 到真实车牌号，然后锁定后停止 OCR。

### 8.8 OBB 微调

构建了 `plate_dataset_obb_finetune`。

已在 Colab 微调：

- 8 轮模型：`best_obb_finetuned_e8.pt`
- 20 轮模型：`best_obb_finetuned_e20.pt`

结论：

- 20 轮模型已经可用于 Windows A/B。
- 后续需要转换到 RKNN 后在板端对比。

### 8.9 去模糊模型

讨论并构建了去模糊数据集 v2。

当前策略：

- 先用 `plate_deblur_dataset_v2.zip` 在 Colab 训练 20 轮。
- 先做静态图片和 Top-K crop 对比。
- 不急着上板端实时推理。

原因：

- 板端实时算力有限。
- 如果 OBB 和 OCR 还不稳，过早加去模糊可能让链路更复杂。

### 8.10 MIPI 摄像头颜色问题

现象：

- MIPI 摄像头画面有时发绿，有时发紫。

判断：

- 不能简单判定 ISP 没运行。
- 更可能是 Bayer 顺序、IQ 文件、白平衡、曝光、video node 或 pixel format 解码不匹配。

已做：

- 新增 `rk3588_mipi_isp_probe.py`。
- 保留 gray-world 软件白平衡作为临时诊断。

后续：

- 用 `media-ctl -p`、`v4l2-ctl --all`、不同 video node 抓图对比。
- 优先确认真正的视频节点和格式。

## 9. 已跑过的重要测试结果

### 9.1 RK baseline，无 re-association

Windows 拉回目录：

```text
D:\YOLO_ALPR_Project\RK3588_dev\rk_baseline_no_reassoc
```

结论：

- 跑到 frame 1000。
- FPS 约 `11.75`。
- 第一辆车能锁定 `冀JC5210`。
- 第二辆车 OCR 票数不足，未稳定锁定。

### 9.2 RK tracker 参数调优

目录：

```text
D:\YOLO_ALPR_Project\RK3588_dev\rk_tracker_defaults
```

结论：

- 跑到 frame 1000。
- FPS 约 `11.82`。
- track 数减少。
- 第一辆车能锁定。
- 第二辆车仍不稳。

### 9.3 RK predicted plate 检测

目录：

```text
D:\YOLO_ALPR_Project\RK3588_dev\rk_plate_predicted_i1
```

结论：

- OBB 候选和 OCR 数增加。
- 第二辆车可锁定 `冀B6R9F9`。
- 第一辆车 OCR 噪声增加，反而不稳定。

说明：

- 更多 OCR 不一定更好。
- 需要候选质量控制，而不是盲目增加 OCR 次数。

### 9.4 RK HyperLPR3 pre OCR

目录：

```text
D:\YOLO_ALPR_Project\RK3588_dev\rk_hyperlpr_pre_i2
D:\YOLO_ALPR_Project\RK3588_dev\rk_hyperlpr_pre_dedup_i1
```

结论：

- 对第二辆车有帮助。
- 对第一辆车可能引入噪声。
- 不建议直接作为默认主线。

### 9.5 RK no-OCR plate-lock 诊断

目录：

```text
D:\YOLO_ALPR_Project\RK3588_dev\rk_noocr_plate_lock_ab
```

结论：

- 第一辆车和第二辆车都能较快锁定 `PLATE`。
- FPS 约 `12` 左右。
- 只证明“检测到车牌后跟踪显示”可行。
- 不能说明真实 OCR 已解决。

## 10. 常用命令

### 10.1 Windows 干净 demo 测试

```powershell
cd D:\YOLO_ALPR_Project

python alpr_topk_capture_demo.py `
  --video D:\YOLO_ALPR_Project\测试图\14.mp4 `
  --output D:\YOLO_ALPR_Project\captures_topk_demo_clean `
  --vehicle-model yolo11n.pt `
  --plate-model best_obb.pt `
  --vehicle-conf 0.55 `
  --plate-conf 0.25 `
  --vehicle-imgsz 640 `
  --plate-imgsz 320 `
  --tracker iou `
  --track-max-age 45 `
  --live-ocr `
  --ocr-engine hyperlpr3 `
  --vote-threshold 3 `
  --vote-window 10 `
  --min-char-vote-ratio 0.65 `
  --min-ocr-conf 0.75 `
  --max-frames 1000 `
  --progress-interval 100 `
  --show-window
```

### 10.2 Windows 生成报告

```powershell
cd D:\YOLO_ALPR_Project

python topk_report.py `
  --input D:\YOLO_ALPR_Project\captures_topk_demo_clean `
  --with-ocr `
  --ocr-engine hyperlpr3 `
  --overwrite-ocr
```

### 10.3 RK 端视频测试，正确主线

这个命令代表当前正确方向：未锁定时 OCR，锁定后只显示和跟踪。

```bash
cd /root/alpr_topk_rk3588

python3 rk3588_topk_capture.py \
  --video /root/deploy/144.mp4 \
  --vehicle-model /root/deploy/vehicle.rknn \
  --plate-model /root/deploy/best_obb.rknn \
  --ocr-engine hyperlpr3 \
  --output /root/alpr_topk_rk3588/runs \
  --max-frames 1000 \
  --vehicle-detect-interval 3 \
  --track-max-age 45 \
  --plate-on-predicted \
  --plate-attempt-interval 2 \
  --process-roi 0.20 0.20 0.85 1.00 \
  --draw-process-roi \
  --publish-frame /tmp/frame.jpg \
  --publish-interval 2 \
  --progress-interval 100
```

### 10.4 板端实时画面

```bash
cd /root/deploy
python3 stream.py
```

浏览器：

```text
http://192.168.137.168:8080
```

### 10.5 从 Windows SSH 板端

```powershell
ssh root@192.168.137.168
```

### 10.6 从 Windows SSH Ubuntu

```powershell
ssh apple@192.168.217.128
```

## 11. 当前 git 状态提示

截至本交接文档创建前，重要状态为：

```text
M  plate_rec_ocr.py
M  rk3588_topk_capture.py
?? alpr_topk_capture_demo.py
?? prepare_deblur_dataset_v2.py
?? rk3588_mipi_isp_probe.py
?? COLAB_DEBLUR_V2_E20_STEPS.md
?? RK3588_dev/rk_*
?? captures_topk_ab*
```

含义：

- `alpr_topk_capture.py` 当前不是 modified。
- `alpr_topk_capture_demo.py` 是未跟踪文件，但内容已恢复为主线干净副本。
- `rk3588_topk_capture.py` 是当前板端优化重点。
- `prepare_deblur_dataset_v2.py` 和 `rk3588_mipi_isp_probe.py` 是新增工具脚本。

## 12. 当前最重要的未解决问题

### 12.1 RK 端跟踪仍不够稳

表现：

- 车辆框可能跟不上。
- track 可能断。
- 锁定文字有时无法持续贴在车辆上方。

需要继续优化：

- 车辆框预测。
- 车辆框中心速度。
- 锁定后车牌相对车辆框位置锚点。
- 断轨后的谨慎重关联。

### 12.2 OBB 车牌命中次数少

表现：

- 有些车辆在最适合识别的时刻没有足够 plate hit。
- 导致 OCR 有效票数不足。

下一步：

- A/B 测试 `best_obb_finetuned_e20.pt`。
- 转 RKNN 后替换板端 OBB 模型。
- 分析 rejected plate 的原因。

### 12.3 OCR 有效票数少且噪声高

表现：

- 增加 OCR 次数会提高命中，但也会引入噪声。
- HyperLPR3 全车 OCR 对部分车辆有帮助，对部分车辆有副作用。

下一步：

- 做候选质量门控。
- 只对高质量 plate crop OCR。
- 继续改进投票策略。

### 12.4 MIPI 摄像头颜色异常

表现：

- 画面发绿或发紫。

下一步：

- 用 `rk3588_mipi_isp_probe.py` 检查 video node 和 pixel format。
- 查 `media-ctl -p`、`v4l2-ctl --all`、`rkaiq_3A_server`。
- 不要只靠 Python 软件调色作为最终方案。

### 12.5 板端 FPS 仍需优化

表现：

- 车辆还很远时 FPS 已经较低。

可能原因：

- 车辆检测仍占主要算力。
- 图像分辨率和预处理开销较大。
- 显示、写图、发布帧也有开销。

下一步：

- 合理设置 ROI。
- 调整 `vehicle-detect-interval`。
- 已锁定车辆跳过 plate/OCR。
- 检查是否还在对无效远处目标做过多处理。

## 13. 后续推荐路线

### 第一优先级：RK 端主链路稳定

目标：

- 对每辆车尽早得到正确车牌号。
- 锁定后停止 OCR 和 plate detection。
- 文本稳定跟随车辆。

建议：

1. 先继续用当前 `rk3588_topk_capture.py`。
2. 每次改动至少跑到 frame 1000。
3. 每次测试保存 run 目录并拉回 `RK3588_dev`。
4. 分析 summary、vote_history、rejected 记录。

### 第二优先级：微调 OBB 上板

目标：

- 将 `best_obb_finetuned_e20.pt` 转成 RKNN。
- 和当前 `best_obb.rknn` 在同一段 `144.mp4` 上 A/B。

关注指标：

- plate hit 数量。
- rejected 数量和原因。
- OCR 有效票数。
- 锁定帧号。
- FPS。

### 第三优先级：去模糊模型静态验证

目标：

- 用 `plate_deblur_dataset_v2.zip` 在 Colab 训练 20 轮。
- 用真实 Top-K crop 做静态测试。
- 判断去模糊是否真的提高 OCR，而不是只让图像视觉更锐。

注意：

- 不建议现在立刻接入板端实时推理。
- 先验证静态收益。

### 第四优先级：MIPI 实地摄像头修正

目标：

- 确定正确 video node、pixel format、ISP/IQ 设置。
- 解决发绿、发紫问题。

## 14. 交接给新对话时的关键提醒

新对话最应该记住这些：

1. 不要随便改 `alpr_topk_capture.py`。
2. Windows 验证请改 `alpr_topk_capture_demo.py`。
3. 板端优化主要改 `rk3588_topk_capture.py`。
4. 最终目标不是 no-OCR，而是 OCR 到锁定为止，锁定后停止 OCR。
5. RK 端每次视频测试至少跑到 frame 1000。
6. Codex 可以 SSH 远程控制 Ubuntu 和 RK3588。
7. 当前 OCR 主推 HyperLPR3。
8. 当前主要瓶颈是 OBB 命中少、OCR 票数少、tracking 不稳。
9. 微调 OBB 模型已经有 `best_obb_finetuned_e20.pt`，下一步需要转 RKNN A/B。
10. 去模糊数据集 v2 已准备好，适合 Colab 先训练 20 轮做静态验证。

