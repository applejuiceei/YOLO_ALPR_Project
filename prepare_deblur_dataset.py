"""Build a fixed-size paired license-plate deblurring dataset for Colab training."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import cv2
from PIL import Image


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = PROJECT_DIR / "Dataset" / "plate_deblur_dataset_v1"
CANONICAL_WIDTH = 320
CANONICAL_HEIGHT = 96
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


@dataclass(frozen=True)
class PairSource:
    name: str
    root: Path
    train_dir: Path
    test_dir: Path | None = None


def split_for_name(source_name: str, filename: str, val_ratio: float) -> str:
    value = int(hashlib.sha1(f"{source_name}:{filename}".encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "val" if value < val_ratio else "train"


def read_color_image(path: Path) -> cv2.typing.MatLike | None:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        return None
    return image


def read_image_size(path: Path) -> list[int] | None:
    try:
        with Image.open(path) as image:
            width, height = image.size
            return [width, height]
    except OSError:
        return None


def resize_pair_image(image: cv2.typing.MatLike, is_target: bool) -> cv2.typing.MatLike:
    interpolation = cv2.INTER_LANCZOS4 if is_target else cv2.INTER_CUBIC
    return cv2.resize(image, (CANONICAL_WIDTH, CANONICAL_HEIGHT), interpolation=interpolation)


def output_name(source_name: str, image_path: Path) -> str:
    return f"{source_name}__{image_path.stem}.jpg"


def prepare_dirs(output_root: Path) -> None:
    for split in ("train", "val", "test"):
        (output_root / split / "blur").mkdir(parents=True, exist_ok=True)
        (output_root / split / "sharp").mkdir(parents=True, exist_ok=True)


def discover_pairs(pair_dir: Path) -> list[Path]:
    blur_dir = pair_dir / "blur"
    sharp_dir = pair_dir / "sharp"
    if not blur_dir.is_dir() or not sharp_dir.is_dir():
        raise FileNotFoundError(f"Expected blur/sharp directories under: {pair_dir}")
    return [
        blur_path
        for blur_path in sorted(blur_dir.iterdir())
        if blur_path.is_file()
        and blur_path.suffix.lower() in IMAGE_SUFFIXES
        and (sharp_dir / blur_path.name).is_file()
    ]


def build_dataset(output_root: Path, sources: list[PairSource], val_ratio: float, resume: bool) -> dict[str, object]:
    manifests = {
        split: (output_root / f"manifest_{split}.jsonl").open("w", encoding="utf-8")
        for split in ("train", "val", "test")
    }
    counts: Counter[str] = Counter()
    invalid: list[str] = []

    try:
        for source in sources:
            source_parts = [("train_source", source.train_dir)]
            if source.test_dir is not None:
                source_parts.append(("test_source", source.test_dir))

            for source_split, pair_dir in source_parts:
                for blur_path in discover_pairs(pair_dir):
                    sharp_path = pair_dir / "sharp" / blur_path.name
                    split = "test" if source_split == "test_source" else split_for_name(source.name, blur_path.name, val_ratio)
                    name = output_name(source.name, blur_path)
                    blur_output = output_root / split / "blur" / name
                    sharp_output = output_root / split / "sharp" / name

                    existing_pair = resume and blur_output.is_file() and sharp_output.is_file()
                    if existing_pair:
                        original_blur_size = read_image_size(blur_path)
                        original_sharp_size = read_image_size(sharp_path)
                        if original_blur_size is None or original_sharp_size is None:
                            invalid.append(str(blur_path))
                            continue
                    else:
                        blur_image = read_color_image(blur_path)
                        sharp_image = read_color_image(sharp_path)
                        if blur_image is None or sharp_image is None:
                            invalid.append(str(blur_path))
                            continue
                        original_blur_size = [int(blur_image.shape[1]), int(blur_image.shape[0])]
                        original_sharp_size = [int(sharp_image.shape[1]), int(sharp_image.shape[0])]
                        ok_blur = cv2.imwrite(
                            str(blur_output),
                            resize_pair_image(blur_image, is_target=False),
                            [cv2.IMWRITE_JPEG_QUALITY, 100],
                        )
                        ok_sharp = cv2.imwrite(
                            str(sharp_output),
                            resize_pair_image(sharp_image, is_target=True),
                            [cv2.IMWRITE_JPEG_QUALITY, 100],
                        )
                        if not ok_blur or not ok_sharp:
                            invalid.append(str(blur_path))
                            continue

                    record = {
                        "id": f"{source.name}__{blur_path.stem}",
                        "source": source.name,
                        "source_split": source_split,
                        "split": split,
                        "blur": f"{split}/blur/{name}",
                        "sharp": f"{split}/sharp/{name}",
                        "original_blur_size": original_blur_size,
                        "original_sharp_size": original_sharp_size,
                        "size": [CANONICAL_WIDTH, CANONICAL_HEIGHT],
                    }
                    manifests[split].write(json.dumps(record, ensure_ascii=False) + "\n")
                    counts[f"{split}:{source.name}"] += 1
    finally:
        for manifest in manifests.values():
            manifest.close()

    return {"counts": dict(sorted(counts.items())), "invalid": invalid}


def write_metadata(output_root: Path, result: dict[str, object], val_ratio: float) -> None:
    metadata = {
        "format": "paired license plate deblurring",
        "size": [CANONICAL_WIDTH, CANONICAL_HEIGHT],
        "color": "BGR on OpenCV load; stored as JPEG",
        "split_policy": {
            "dataset_test": "kept as final test set",
            "dataset_train": f"deterministic hash split with val_ratio={val_ratio}",
            "mdlp_mini_train": f"deterministic hash split with val_ratio={val_ratio}",
        },
        "counts": result["counts"],
        "invalid_pairs": result["invalid"],
    }
    (output_root / "dataset_info.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_root / "README.txt").write_text(
        "Paired license plate deblurring dataset.\n"
        "Each split contains blur/ and sharp/ images with identical file names.\n"
        "All images are preprocessed to 320x96. dataset/test is held out as final test data.\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Colab-ready paired 320x96 deblurring dataset.")
    parser.add_argument("--dataset-root", type=Path, default=PROJECT_DIR / "Dataset" / "dataset")
    parser.add_argument("--mdlp-root", type=Path, default=PROJECT_DIR / "Dataset" / "MDLP_Mini")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--val-ratio", type=float, default=0.10)
    parser.add_argument("--clean", action="store_true", help="Delete the generated output before building.")
    parser.add_argument("--resume", action="store_true", help="Keep complete output pairs and rebuild manifests.")
    args = parser.parse_args()

    if not 0.0 < args.val_ratio < 1.0:
        raise ValueError("--val-ratio must be between 0 and 1")
    if args.clean and args.output.exists():
        shutil.rmtree(args.output)
    if args.output.exists() and not args.clean and not args.resume and any(args.output.iterdir()):
        raise FileExistsError(f"Output already exists. Use --clean or --resume: {args.output}")

    sources = [
        PairSource("tinyunet", args.dataset_root, args.dataset_root / "train", args.dataset_root / "test"),
        PairSource("mdlp_mini", args.mdlp_root, args.mdlp_root / "train"),
    ]
    prepare_dirs(args.output)
    result = build_dataset(args.output, sources, args.val_ratio, args.resume)
    write_metadata(args.output, result, args.val_ratio)

    print("Build complete.")
    for key, value in result["counts"].items():
        print(f"  {key}: {value}")
    print(f"  invalid_pairs: {len(result['invalid'])}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
