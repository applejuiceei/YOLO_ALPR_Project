# OBB Fine-tuning

## 1. Build the OBB base dataset locally

```powershell
cd D:\YOLO_ALPR_Project
D:\miniconda\envs\alpr_env\python.exe prepare_obb_finetune_dataset.py --clean `
  --ccpd-root D:\YOLO_ALPR_Project\Dataset\CCPD2020 `
  --crpd-root D:\YOLO_ALPR_Project\Dataset\CRPD_single `
  --crpd-root D:\YOLO_ALPR_Project\Dataset\CRPD_double `
  --crpd-root D:\YOLO_ALPR_Project\Dataset\CRPD_multi
```

This uses only each source's original `train` and `val` splits. CCPD quadrilaterals are read from file names; CRPD quadrilaterals are read from its label text files. Both become one YOLO-OBB class: `license_plate`.

`test` is intentionally excluded from the generated dataset. Keep it untouched for the final comparison. Image files are hard-linked by default, so the generated dataset does not duplicate the local image data while it remains on `D:`. Use `--file-mode copy` only when an output location is on a different drive.

## 2. Export video hard cases for manual review

Use a completed Top-K run. The example below uses the latest validation run.

```powershell
D:\miniconda\envs\alpr_env\python.exe export_obb_review_pack.py --run-dir D:\YOLO_ALPR_Project\captures_topk\run_YYYYMMDD_HHMMSS --clean
```

## 3. Review the hard cases

```powershell
D:\miniconda\envs\alpr_env\python.exe annotate_obb_review.py
```

Controls:

- `a`: load the suggested four-point OBB.
- Left mouse: click the four true plate corners.
- `r`: clear the current points.
- `u`: undo the last clicked point.
- `s`: save a four-point label and continue.
- `n`: mark a frame with no visible/labellable plate as a reviewed negative sample.
- `p`: go back one frame.
- `q` or `Esc`: quit.

For rejected examples, do not accept the suggested false box. Clear it, then annotate the true plate only if it is visible. If no true plate is visible, press `n`; the frame will be added as an empty-label hard negative during training.

## 4. Merge reviewed hard cases into the training dataset

```powershell
D:\miniconda\envs\alpr_env\python.exe prepare_obb_finetune_dataset.py --clean `
  --ccpd-root D:\YOLO_ALPR_Project\Dataset\CCPD2020 `
  --crpd-root D:\YOLO_ALPR_Project\Dataset\CRPD_single `
  --crpd-root D:\YOLO_ALPR_Project\Dataset\CRPD_double `
  --crpd-root D:\YOLO_ALPR_Project\Dataset\CRPD_multi `
  --review-root D:\YOLO_ALPR_Project\Dataset\obb_hardcase_review
```

The result is:

```text
Dataset\plate_dataset_obb_finetune\
  images\train
  images\val
  labels\train
  labels\val
  plate_obb_finetune.yaml
```

## 5. Train on Colab GPU

1. Upload `Dataset\plate_dataset_obb_finetune` to `/content/plate_dataset_obb_finetune`.
2. Upload `best_obb.pt` to `/content/best_obb.pt`.
3. In a GPU Colab notebook run:

```python
!pip install -U ultralytics
!python /content/train_obb_colab.py
```

4. Download the resulting model:

```text
/content/runs/obb/alpr_finetune/weights/best.pt
```

5. Copy it to the project as a new file, for example `best_obb_finetuned.pt`, and compare it against `best_obb.pt` using the same `14.mp4` Top-K workflow. Do not overwrite the current baseline until the comparison is clearly better.
