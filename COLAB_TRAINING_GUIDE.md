# Colab Training Guide

This guide trains two independent models:

1. `best_obb.pt` fine-tuning for plate localization.
2. `PlateRestoreNet-Lite` for paired plate deblurring.

Do not train both jobs at the same time in one runtime. Finish, back up, and download the OBB model before starting the deblurring job.

## 0. Local Files To Prepare

Required project files:

```text
best_obb.pt
train_obb_colab.py
train_deblur_colab.py
Dataset\plate_dataset_obb_finetune\
Dataset\plate_deblur_dataset_v1\
```

The OBB dataset is about 17.6 GB before compression. Make sure the Google Drive account used by Colab has at least 20 GB free before uploading its archive. The default free 15 GB Drive tier is often not enough. The deblurring dataset is about 0.39 GB.

### Create Archives

Use 7-Zip if it is installed. The commands below create archives containing the dataset folder itself, which is required by the Colab extraction commands.

```powershell
& "C:\Program Files\7-Zip\7z.exe" a -tzip -mx=1 D:\YOLO_ALPR_Project\upload\plate_dataset_obb_finetune.zip D:\YOLO_ALPR_Project\Dataset\plate_dataset_obb_finetune
& "C:\Program Files\7-Zip\7z.exe" a -tzip -mx=5 D:\YOLO_ALPR_Project\upload\plate_deblur_dataset_v1.zip D:\YOLO_ALPR_Project\Dataset\plate_deblur_dataset_v1
```

If the 7-Zip command path is different on the computer, use its graphical interface instead. Create this Drive folder in the browser and upload the two archives plus the three Python/model files into it:

```text
MyDrive/YOLO_ALPR_Colab/
  best_obb.pt
  train_obb_colab.py
  train_deblur_colab.py
  plate_dataset_obb_finetune.zip
  plate_deblur_dataset_v1.zip
```

For the large OBB archive, use Google Drive upload rather than the Colab file-upload widget. The browser widget is appropriate for small artifacts such as `best.pt`, ONNX files, or the deblurring archive.

## 1. Create A GPU Colab Runtime

1. Open a new Google Colab notebook.
2. Select `Runtime` -> `Change runtime type`.
3. Select `T4 GPU` or another GPU hardware accelerator, then save.
4. Run this cell. Training must not continue when `torch.cuda.is_available()` is `False`.

```python
import torch
print("Torch:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())
!nvidia-smi
```

5. Mount Drive and set a reusable path.

```python
from google.colab import drive
drive.mount("/content/drive")

DRIVE_ROOT = "/content/drive/MyDrive/YOLO_ALPR_Colab"
```

## 2. Fine-tune `best_obb.pt`

### 2.1 Install And Extract

Run this in a fresh GPU runtime:

```python
!pip -q install -U ultralytics
!cp "$DRIVE_ROOT/best_obb.pt" /content/best_obb.pt
!cp "$DRIVE_ROOT/train_obb_colab.py" /content/train_obb_colab.py
!rm -rf /content/plate_dataset_obb_finetune
!unzip -q "$DRIVE_ROOT/plate_dataset_obb_finetune.zip" -d /content
!find /content/plate_dataset_obb_finetune/images/train -type f | wc -l
!find /content/plate_dataset_obb_finetune/labels/train -type f | wc -l
```

The last two numbers should both be `30786`. If they do not match, stop and check that the archive extracted a single `plate_dataset_obb_finetune` root folder.

### 2.2 Start Training

```python
!python /content/train_obb_colab.py
```

The default configuration is `imgsz=640`, `epochs=20`, `batch=16`, and AdamW. If a CUDA out-of-memory error occurs, edit only `batch=16` in `/content/train_obb_colab.py` to `batch=8`, then run again. Do not reduce `imgsz` for the first experiment because small plates need the 640-pixel detector input.

Main outputs:

```text
/content/runs/obb/alpr_finetune/
  results.csv
  results.png
  weights/best.pt
  weights/last.pt
```

### 2.3 Resume An Interrupted OBB Job

If the runtime disconnected after at least one epoch, copy `last.pt` to Drive before the runtime expires. In a new runtime, restore data as above, then run:

```python
from ultralytics import YOLO

model = YOLO("/content/runs/obb/alpr_finetune/weights/last.pt")
model.train(resume=True)
```

### 2.4 Validate, Back Up, And Download

```python
from ultralytics import YOLO

best = YOLO("/content/runs/obb/alpr_finetune/weights/best.pt")
metrics = best.val(
    data="/content/plate_dataset_obb_finetune/plate_obb_finetune_colab.yaml",
    task="obb",
    imgsz=640,
)
print(metrics)

!mkdir -p "$DRIVE_ROOT/outputs"
!cp /content/runs/obb/alpr_finetune/weights/best.pt "$DRIVE_ROOT/outputs/best_obb_finetuned.pt"
!cp /content/runs/obb/alpr_finetune/weights/last.pt "$DRIVE_ROOT/outputs/last_obb_finetuned.pt"
!cp /content/runs/obb/alpr_finetune/results.csv "$DRIVE_ROOT/outputs/obb_results.csv"
```

Download `best_obb_finetuned.pt` and place it locally as:

```text
D:\YOLO_ALPR_Project\best_obb_finetuned.pt
```

Do not overwrite the baseline `best_obb.pt`. Compare the two models on the same video with unchanged thresholds:

```powershell
D:\miniconda\envs\alpr_env\python.exe alpr_topk_capture.py --video D:\YOLO_ALPR_Project\测试图\14.mp4 --plate-model D:\YOLO_ALPR_Project\best_obb.pt --output D:\YOLO_ALPR_Project\captures_topk\baseline_obb
D:\miniconda\envs\alpr_env\python.exe alpr_topk_capture.py --video D:\YOLO_ALPR_Project\测试图\14.mp4 --plate-model D:\YOLO_ALPR_Project\best_obb_finetuned.pt --output D:\YOLO_ALPR_Project\captures_topk\finetuned_obb
```

Compare false boxes, missed plates, plate crop placement, and the OCR-vote result. Retain the fine-tuned model only if the actual `14.mp4` result is better, not merely because the training metric is higher.

## 3. Train The Deblurring Model

Use a new GPU runtime after the OBB job has been backed up.

### 3.1 Install And Extract

```python
import torch
print(torch.cuda.is_available())
!pip -q install onnx
!cp "$DRIVE_ROOT/train_deblur_colab.py" /content/train_deblur_colab.py
!rm -rf /content/plate_deblur_dataset_v1
!unzip -q "$DRIVE_ROOT/plate_deblur_dataset_v1.zip" -d /content
!find /content/plate_deblur_dataset_v1/train/blur -type f | wc -l
!find /content/plate_deblur_dataset_v1/train/sharp -type f | wc -l
```

The last two values must both be `9340`.

### 3.2 Train

```python
!python /content/train_deblur_colab.py \
  --data /content/plate_deblur_dataset_v1 \
  --output /content/runs/deblur/plate_restore_lite \
  --epochs 80 \
  --batch-size 64 \
  --workers 2
```

The model has about 203k parameters and uses mixed precision on GPU. `batch-size=64` is appropriate for T4/L4 class GPUs. If CUDA runs out of memory, retry with `--batch-size 32`.

The model deliberately does not use diffusion. It predicts a residual correction over the original plate image, which reduces the risk of altering a Chinese character or number into a plausible but incorrect character.

### 3.3 Inspect During Training

```python
from IPython.display import Image, display

display(Image(filename="/content/runs/deblur/plate_restore_lite/samples/epoch_005.jpg"))
```

Inspect `blur | restored | sharp` in that order. A good result sharpens existing strokes while preserving the character identity. Reject a model that introduces extra strokes, changes a digit, or gives a visually sharp but structurally different character.

### 3.4 Resume An Interrupted Deblurring Job

At any time, copy `last.pt` to Drive:

```python
!mkdir -p "$DRIVE_ROOT/outputs"
!cp /content/runs/deblur/plate_restore_lite/last.pt "$DRIVE_ROOT/outputs/deblur_last.pt"
```

In a new runtime, extract the deblurring dataset and copy the checkpoint back. Use the same output path and epoch count:

```python
!cp "$DRIVE_ROOT/outputs/deblur_last.pt" /content/deblur_last.pt
!python /content/train_deblur_colab.py \
  --data /content/plate_deblur_dataset_v1 \
  --output /content/runs/deblur/plate_restore_lite \
  --epochs 80 \
  --batch-size 64 \
  --workers 2 \
  --resume /content/deblur_last.pt
```

### 3.5 Evaluate, Back Up, And Download

After training, the script writes:

```text
/content/runs/deblur/plate_restore_lite/
  best.pt
  last.pt
  plate_restore_lite_320x96.onnx
  metrics.csv
  test_metrics.json
  samples/epoch_*.jpg
```

`test_metrics.json` contains both the original blurred-input baseline and the restored result on the untouched 1,041-pair test set. The restored PSNR and SSIM must be higher than the identity baseline before the model is considered useful.

```python
!mkdir -p "$DRIVE_ROOT/outputs"
!cp /content/runs/deblur/plate_restore_lite/best.pt "$DRIVE_ROOT/outputs/plate_restore_lite_best.pt"
!cp /content/runs/deblur/plate_restore_lite/plate_restore_lite_320x96.onnx "$DRIVE_ROOT/outputs/plate_restore_lite_320x96.onnx"
!cp /content/runs/deblur/plate_restore_lite/test_metrics.json "$DRIVE_ROOT/outputs/deblur_test_metrics.json"
!cp /content/runs/deblur/plate_restore_lite/metrics.csv "$DRIVE_ROOT/outputs/deblur_metrics.csv"
```

Download the ONNX file to the project as:

```text
D:\YOLO_ALPR_Project\plate_restore_lite_320x96.onnx
```

The ONNX model has a fixed `1x3x96x320` BGR input and fixed BGR output. Keep this fixed shape for later RKNN INT8 calibration and deployment.

## 4. Decision Rule After Both Jobs

1. Select the OBB model by its `14.mp4` plate localization quality, not training loss alone.
2. Select the restoration model only when both held-out paired metrics and `14.mp4` visual/OCR checks improve.
3. Do not place the restoration model in the real-time path yet. First run it only on saved Top-K candidate crops; measure HyperLPR3 before/after and record which vehicle IDs genuinely improve.
4. If real video crops remain unreadable after this first model, add MDLP Standard and CRPD/CCPD synthetic degradation data for the second training stage.
