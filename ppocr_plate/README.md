# Plate-specific PP-OCRv4 Mobile workspace

This directory is intentionally separate from the Windows and RK3588 ALPR mainlines. It prepares and validates a single-line, 7/8-character plate recognizer before any runtime integration.

## Fixed contract

- API input: one rectified OpenCV BGR plate crop.
- Model tensor: RGB `float32 NCHW [1, 3, 48, 160]`, Paddle normalization `(pixel / 255 - 0.5) / 0.5`.
- Output: CTC time-step scores for the 76 entries in `plate_chars.txt` plus one blank class (77 classes total).
- Public API: `recognize(image) -> (text, confidence)`.
- Promotion gates: readable real-plate exact accuracy `>= 98%`, character accuracy `>= 99.5%`, INT8 loss `<= 0.5` percentage points, and end-to-end OCR `P95 < 20 ms` over 1000 calls on both Windows CPU and RK3588 NPU.

## Local smoke workflow

```powershell
D:\miniconda\envs\alpr_env\python.exe -m ppocr_plate.synthetic `
  --output ppocr_plate\data\synthetic_smoke --count 128

D:\miniconda\envs\alpr_env\python.exe -m ppocr_plate.dataset `
  build --data-root ppocr_plate\data `
  --manifest ppocr_plate\data\synthetic_smoke\manifest.tsv `
  --output ppocr_plate\data\splits_smoke --split-all-sources

D:\miniconda\envs\alpr_env\python.exe -m ppocr_plate.train `
  smoke --paddleocr-root third_party\PaddleOCR `
  --splits ppocr_plate\data\splits_smoke --data-root ppocr_plate\data
```

The smoke run verifies data loading, the 76-character dictionary, forward/backward computation, checkpoint writing and export compatibility. It is not an accuracy training run. Raw labels are limited to eight characters; the training-only NRTR auxiliary branch uses ten sequence slots so it can add BOS/EOS tokens. The exported model contains only the CTC branch.

## Full data policy

- Public/synthetic train set: at least 100,000 readable crops.
- Manually verified project crops: at least 3,000, split 2,000/500/500.
- `manifest.tsv` columns are `image_path`, `label`, `group_id`, `source`, `readable`.
- Paths are relative to `--data-root`. The same `group_id` can never cross train/validation/test splits.
- Only `source=real_verified` counts as manually verified real data. Annotation templates start with `source=real_unverified` and `readable=0`.
- Exact duplicate files are checked by SHA256. The audit also binds the fixed 76-character dictionary by SHA256, so a split audited with another dictionary cannot start formal training. Public rows require `--public-license-note` before the formal gate can pass.
- HyperLPR3 and historical summaries may propose labels but do not count as ground truth until manually reviewed.
- Double-line plates are outside v1 and must not be silently folded into the single-line dataset.

Build the formal split only after labels and vehicle/video group IDs have been manually checked:

```powershell
D:\miniconda\envs\alpr_env\python.exe -m ppocr_plate.dataset build `
  --data-root ppocr_plate\data `
  --manifest ppocr_plate\data\synthetic\manifest.tsv `
  --manifest ppocr_plate\data\real_verified\manifest.tsv `
  --output ppocr_plate\data\splits_formal --decode-images `
  --public-license-note "CCPD license checked: <license URL>"
```

Formal `train` refuses to start unless `audit.json` proves at least 100,000 public/synthetic train crops, 2,000/500/500 `real_verified` crops, non-empty splits, no group leakage, exact-file duplicate checking and public-license review.

## Fine-tuning

The pip PaddleOCR wheel on this machine contains inference code only. Use the official 2.7 training source and the official PP-OCRv4 recognition training checkpoint:

```powershell
git clone --depth 1 --branch release/2.7 `
  https://github.com/PaddlePaddle/PaddleOCR.git third_party\PaddleOCR

# Download and extract:
# https://paddleocr.bj.bcebos.com/PP-OCRv4/chinese/ch_PP-OCRv4_rec_train.tar

D:\miniconda\envs\alpr_env\python.exe -m ppocr_plate.train train `
  --paddleocr-root third_party\PaddleOCR `
  --splits ppocr_plate\data\splits_formal --data-root ppocr_plate\data `
  --pretrained pretrain_models\ch_PP-OCRv4_rec_train\best_accuracy `
  --device gpu --epochs 100 --batch-size 128 --workers 8
```

`--pretrained` accepts either the checkpoint prefix or its `.pdparams` file. The 76-character CTC output layer is reinitialized when its shape differs; the compatible PP-OCRv4 backbone/CTC-neck weights are loaded. Full training remains pending until a GPU environment and the audited dataset are available.

## Deployment artifacts

The expected artifacts are a fixed-shape Paddle inference model, an ONNX FP32 model, an OpenVINO FP32/INT8 model and RKNN FP16/INT8 models. Conversion scripts fail with an actionable dependency message when the corresponding external toolkit is unavailable.

```powershell
# Paddle checkpoint -> Paddle inference model
D:\miniconda\envs\alpr_env\python.exe -m ppocr_plate.train export `
  --paddleocr-root third_party\PaddleOCR `
  --checkpoint runs_ppocr_plate_train\train_xxx\best_accuracy `
  --output ppocr_plate\artifacts\paddle

# Paddle -> ONNX, with real-crop Paddle/ONNX parity validation
D:\miniconda\envs\alpr_env\python.exe -m ppocr_plate.export_onnx `
  --model-dir ppocr_plate\artifacts\paddle `
  --output ppocr_plate\artifacts\plate_ppocrv4.onnx `
  --image-dir ppocr_plate\data\real_verified\images --parity-samples 16

# ONNX Runtime: warmup 50, measured 1000, disk I/O excluded
D:\miniconda\envs\alpr_env\python.exe -m ppocr_plate.benchmark `
  --model ppocr_plate\artifacts\plate_ppocrv4.onnx `
  --dictionary ppocr_plate\plate_chars.txt `
  --labels ppocr_plate\data\splits_formal\test.txt `
  --data-root ppocr_plate\data --warmup 50 --iterations 1000

# OpenVINO FP32 and INT8
D:\miniconda\envs\alpr_env\python.exe -m ppocr_plate.openvino_tools convert `
  --model ppocr_plate\artifacts\plate_ppocrv4.onnx `
  --output ppocr_plate\artifacts\openvino_fp32\model.xml

D:\miniconda\envs\alpr_env\python.exe -m ppocr_plate.openvino_tools quantize `
  --model ppocr_plate\artifacts\openvino_fp32\model.xml `
  --output ppocr_plate\artifacts\openvino_int8\model.xml `
  --manifest ppocr_plate\data\splits_formal\canonical_manifest.tsv `
  --data-root ppocr_plate\data --min-samples 1000 --max-samples 2000
```

On a compatible x86 Linux RKNN-Toolkit2 host, create FP16/INT8 RKNN files; then run the benchmark on RK3588:

```bash
python -m ppocr_plate.rknn_tools convert \
  --onnx ppocr_plate/artifacts/plate_ppocrv4.onnx \
  --output ppocr_plate/artifacts/plate_ppocrv4_fp16.rknn --precision fp16

python -m ppocr_plate.rknn_tools convert \
  --onnx ppocr_plate/artifacts/plate_ppocrv4.onnx \
  --output ppocr_plate/artifacts/plate_ppocrv4_int8.rknn --precision int8 \
  --calibration-manifest ppocr_plate/data/splits_formal/canonical_manifest.tsv \
  --calibration-data-root ppocr_plate/data --calibration-count 2000

python -m ppocr_plate.rknn_tools benchmark \
  --model ppocr_plate/artifacts/plate_ppocrv4_int8.rknn \
  --images ppocr_plate/data/splits_formal/test.txt \
  --data-root ppocr_plate/data --core-mode triple --warmup 50 --iterations 1000
```

Use `compare_backends.py` on transferred `results.json` files to check identical sample coverage/text and the INT8 exact-accuracy drop (`<= 0.5` percentage points). No backend is eligible for the realtime program until both real-test accuracy gates and `P95 < 20 ms` pass.
