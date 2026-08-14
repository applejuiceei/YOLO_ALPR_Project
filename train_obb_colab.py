"""Run this in Google Colab after uploading the project OBB dataset and best_obb.pt."""

from pathlib import Path

from ultralytics import YOLO


DATASET_ROOT = Path("/content/plate_dataset_obb_finetune")
DATA_YAML = DATASET_ROOT / "plate_obb_finetune_colab.yaml"
BASE_MODEL = "/content/best_obb.pt"


def main() -> None:
    DATA_YAML.write_text(
        "\n".join(
            [
                f"path: {DATASET_ROOT.as_posix()}",
                "train: images/train",
                "val: images/val",
                "",
                "nc: 1",
                "names: ['license_plate']",
                "",
            ]
        ),
        encoding="utf-8",
    )
    model = YOLO(BASE_MODEL)
    model.train(
        data=str(DATA_YAML),
        task="obb",
        imgsz=640,
        epochs=20,
        batch=16,
        device=0,
        workers=2,
        optimizer="AdamW",
        lr0=0.001,
        lrf=0.01,
        patience=20,
        degrees=4.0,
        translate=0.05,
        scale=0.35,
        shear=1.0,
        perspective=0.0005,
        fliplr=0.5,
        mosaic=0.2,
        mixup=0.0,
        project="/content/runs/obb",
        name="alpr_finetune",
        exist_ok=True,
    )


if __name__ == "__main__":
    main()
