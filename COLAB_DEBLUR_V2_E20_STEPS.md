# Colab 训练 plate_deblur_dataset_v2 去模糊模型 20 轮

本文档用于把 `D:\YOLO_ALPR_Project\Dataset\plate_deblur_dataset_v2.zip` 上传到 Colab，并用现有 `train_deblur_colab.py` 先训练 20 轮，得到 `best.pt`、`last.pt`、`plate_restore_lite_320x96.onnx` 和测试指标。

## 1. Windows 端准备文件

确认这两个文件存在：

```powershell
Test-Path D:\YOLO_ALPR_Project\Dataset\plate_deblur_dataset_v2.zip
Test-Path D:\YOLO_ALPR_Project\train_deblur_colab.py
```

建议上传到 Google Drive：

```text
MyDrive/YOLO_ALPR_Colab/plate_deblur_dataset_v2.zip
MyDrive/YOLO_ALPR_Colab/train_deblur_colab.py
```

## 2. Colab 选择运行环境

在 Colab 顶部菜单：

```text
运行时 -> 更改运行时类型 -> 硬件加速器 -> T4 GPU
```

然后按下面单元格依次运行。

## 3. 挂载 Google Drive

```python
from google.colab import drive
drive.mount("/content/drive")
```

## 4. 安装依赖

```python
!pip install -q opencv-python-headless tqdm onnx onnxscript
```

说明：

- Colab 通常已经自带 PyTorch + CUDA，不需要单独安装 `torch`。
- `onnx` 和 `onnxscript` 用于训练结束后导出 `plate_restore_lite_320x96.onnx`。

## 5. 解压数据集

```python
from pathlib import Path
import shutil

DRIVE_ROOT = Path("/content/drive/MyDrive/YOLO_ALPR_Colab")
ZIP_PATH = DRIVE_ROOT / "plate_deblur_dataset_v2.zip"
DATA_ROOT = Path("/content/plate_deblur_dataset_v2")

assert ZIP_PATH.exists(), f"找不到数据集压缩包: {ZIP_PATH}"

if DATA_ROOT.exists():
    shutil.rmtree(DATA_ROOT)
DATA_ROOT.mkdir(parents=True, exist_ok=True)

!unzip -q "{ZIP_PATH}" -d "{DATA_ROOT}"

# 兼容两种压缩结构：
# A. zip 里面直接是 train/val/test
# B. zip 里面还有一层 plate_deblur_dataset_v2/train
if not (DATA_ROOT / "train").exists() and (DATA_ROOT / "plate_deblur_dataset_v2" / "train").exists():
    DATA_ROOT = DATA_ROOT / "plate_deblur_dataset_v2"

print("DATA_ROOT =", DATA_ROOT)
print("train exists:", (DATA_ROOT / "train").exists())
print("val exists:", (DATA_ROOT / "val").exists())
print("test exists:", (DATA_ROOT / "test").exists())
```

## 6. 检查数据数量和尺寸

```python
from pathlib import Path
import cv2
import random

for split in ["train", "val", "test"]:
    blur_files = sorted((DATA_ROOT / split / "blur").glob("*.jpg"))
    sharp_files = sorted((DATA_ROOT / split / "sharp").glob("*.jpg"))
    print(split, "blur:", len(blur_files), "sharp:", len(sharp_files))
    assert len(blur_files) == len(sharp_files), f"{split} blur/sharp 数量不一致"

sample = random.choice(sorted((DATA_ROOT / "train" / "blur").glob("*.jpg")))
img = cv2.imread(str(sample))
print("sample:", sample.name, "shape:", img.shape)
assert img.shape[:2] == (96, 320), "样本尺寸应为 320x96，对应 OpenCV shape 为 (96, 320, 3)"
```

## 7. 拷贝训练脚本到 Colab 本地

```python
SCRIPT_PATH = DRIVE_ROOT / "train_deblur_colab.py"
assert SCRIPT_PATH.exists(), f"找不到训练脚本: {SCRIPT_PATH}"

!cp "{SCRIPT_PATH}" /content/train_deblur_colab.py
```

## 8. 开始训练 20 轮

```python
RUN_DIR = Path("/content/runs/deblur/plate_restore_lite_v2_e20")

!python /content/train_deblur_colab.py \
  --data "{DATA_ROOT}" \
  --output "{RUN_DIR}" \
  --epochs 20 \
  --batch-size 64 \
  --workers 2 \
  --lr 0.001
```

如果显存不足，把 `--batch-size 64` 改成：

```text
--batch-size 32
```

如果训练中断，可以用 `last.pt` 继续：

```python
!python /content/train_deblur_colab.py \
  --data "{DATA_ROOT}" \
  --output "{RUN_DIR}" \
  --epochs 20 \
  --batch-size 64 \
  --workers 2 \
  --lr 0.001 \
  --resume "{RUN_DIR}/last.pt"
```

注意：`--resume` 会从 `last.pt` 记录的下一轮继续跑，`--epochs 20` 表示最终跑到第 20 轮。

## 9. 查看训练过程输出

训练目录：

```python
!find "{RUN_DIR}" -maxdepth 2 -type f | sort
```

关键文件：

```text
best.pt
last.pt
metrics.csv
test_metrics.json
training_config.json
plate_restore_lite_320x96.onnx
samples/epoch_001.jpg
samples/epoch_005.jpg
samples/epoch_010.jpg
samples/epoch_015.jpg
samples/epoch_020.jpg
```

查看预览图：

```python
from IPython.display import Image, display
display(Image(filename=str(RUN_DIR / "samples" / "epoch_020.jpg")))
```

查看指标：

```python
import json
print((RUN_DIR / "test_metrics.json").read_text())
```

重点看：

- `identity_blur_baseline`: 不恢复，直接拿 blur 和 sharp 对比。
- `restored`: 模型恢复结果和 sharp 对比。
- 如果 `restored.psnr` 高于 baseline，说明模型至少在合成退化数据上学到了恢复。
- 如果真实 Top-K 车牌上出现字符被修坏，要回头调退化策略或训练损失。

## 10. 保存结果到 Google Drive

```python
OUT_DIR = DRIVE_ROOT / "outputs" / "deblur_v2_e20"
OUT_DIR.mkdir(parents=True, exist_ok=True)

!cp "{RUN_DIR}/best.pt" "{OUT_DIR}/plate_restore_lite_v2_e20_best.pt"
!cp "{RUN_DIR}/last.pt" "{OUT_DIR}/plate_restore_lite_v2_e20_last.pt"
!cp "{RUN_DIR}/plate_restore_lite_320x96.onnx" "{OUT_DIR}/plate_restore_lite_v2_e20_320x96.onnx"
!cp "{RUN_DIR}/metrics.csv" "{OUT_DIR}/metrics.csv"
!cp "{RUN_DIR}/test_metrics.json" "{OUT_DIR}/test_metrics.json"
!cp "{RUN_DIR}/training_config.json" "{OUT_DIR}/training_config.json"
!cp -r "{RUN_DIR}/samples" "{OUT_DIR}/samples"

print("saved to:", OUT_DIR)
```

下载到 Windows 后建议放到：

```text
D:\YOLO_ALPR_Project\blur models\plate_restore_lite_v2_e20_320x96.onnx
D:\YOLO_ALPR_Project\blur models\plate_restore_lite_v2_e20_best.pt
```

## 11. 训练完成后本地静态测试建议

优先拿这些真实车牌 crop 测：

```text
D:\YOLO_ALPR_Project\captures_topk\...\track_*\plate_rank*.jpg
D:\YOLO_ALPR_Project\RK3588_dev\rk_reassoc_vote2\run_20260625_102556\track_*\plate_rank*.jpg
```

判断标准不是单看图像更锐，而是：

1. 汉字和字母边缘是否更可读。
2. OCR 是否更稳定。
3. 是否出现错误纹理、伪字符、把 `G/6/9` 等字符修坏。

20 轮只是验证版。如果效果有希望，再训练 60 到 100 轮，并把真实 Top-K crop 作为测试集固定下来做 A/B。
