"""Build a synthetic license-plate deblurring dataset from paired and OBB sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
from PIL import Image


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = PROJECT_DIR / "Dataset" / "plate_deblur_dataset_v2"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
DEFAULT_WIDTH = 320
DEFAULT_HEIGHT = 96


@dataclass(frozen=True)
class SharpSample:
    source: str
    split: str
    image_path: Path
    label_path: Path | None
    quad: np.ndarray | None
    sample_id: str


def stable_unit(value: str) -> float:
    return int(hashlib.sha1(value.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF


def order_quad(points: np.ndarray) -> np.ndarray:
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    ordered = points[np.argsort(angles)]
    start = np.argmin(ordered.sum(axis=1))
    return np.roll(ordered, -start, axis=0).astype(np.float32)


def read_size(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as image:
            return image.size
    except OSError:
        return None


def read_image(path: Path) -> np.ndarray | None:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        return None
    return image


def resize_plate(image: np.ndarray, size: tuple[int, int], target: bool) -> np.ndarray:
    interpolation = cv2.INTER_LANCZOS4 if target else cv2.INTER_CUBIC
    return cv2.resize(image, size, interpolation=interpolation)


def warp_plate(image: np.ndarray, quad: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    width, height = size
    rect = order_quad(quad)
    dst = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, matrix, (width, height), flags=cv2.INTER_LANCZOS4)


def parse_yolo_obb(label_path: Path, image_size: tuple[int, int]) -> list[np.ndarray]:
    width, height = image_size
    quads: list[np.ndarray] = []
    for line in label_path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) < 9:
            continue
        try:
            values = [float(value) for value in fields[1:9]]
        except ValueError:
            continue
        points = np.asarray(values, dtype=np.float32).reshape(4, 2)
        points[:, 0] *= width
        points[:, 1] *= height
        if cv2.contourArea(points) >= 8.0:
            quads.append(order_quad(points))
    return quads


def iter_obb_samples(obb_root: Path) -> Iterable[SharpSample]:
    for source_split in ("train", "val"):
        image_dir = obb_root / "images" / source_split
        label_dir = obb_root / "labels" / source_split
        if not image_dir.is_dir() or not label_dir.is_dir():
            continue
        for image_path in sorted(path for path in image_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES):
            label_path = label_dir / f"{image_path.stem}.txt"
            if not label_path.is_file():
                continue
            size = read_size(image_path)
            if size is None:
                continue
            quads = parse_yolo_obb(label_path, size)
            split = "train"
            if source_split == "val":
                split = "test" if stable_unit(f"obb-test:{image_path.name}") < 0.5 else "val"
            for index, quad in enumerate(quads):
                sample_id = f"obb_{source_split}_{image_path.stem}_{index}"
                yield SharpSample("obb_finetune", split, image_path, label_path, quad, sample_id)


def iter_paired_samples(root: Path, source: str) -> Iterable[SharpSample]:
    for source_split in ("train", "test"):
        pair_dir = root / source_split
        blur_dir = pair_dir / "blur"
        sharp_dir = pair_dir / "sharp"
        if not blur_dir.is_dir() or not sharp_dir.is_dir():
            continue
        split = "test" if source_split == "test" else ("val" if stable_unit(f"{source}:{source_split}") < 0.1 else "train")
        for blur_path in sorted(path for path in blur_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES):
            sharp_path = sharp_dir / blur_path.name
            if sharp_path.is_file():
                yield SharpSample(source, split, sharp_path, blur_path, None, f"{source}_{source_split}_{blur_path.stem}")


def split_paired_train(sample: SharpSample, val_ratio: float) -> str:
    if sample.split != "train":
        return sample.split
    return "val" if stable_unit(f"{sample.source}:{sample.sample_id}") < val_ratio else "train"


def motion_kernel(length: int, angle: float) -> np.ndarray:
    length = max(1, int(length) | 1)
    kernel = np.zeros((length, length), dtype=np.float32)
    kernel[length // 2, :] = 1.0
    matrix = cv2.getRotationMatrix2D((length / 2 - 0.5, length / 2 - 0.5), angle, 1.0)
    kernel = cv2.warpAffine(kernel, matrix, (length, length))
    total = float(kernel.sum())
    return kernel / total if total > 0 else kernel


def jpeg_roundtrip(image: np.ndarray, quality: int) -> np.ndarray:
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        return image
    decoded = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    return decoded if decoded is not None else image


def apply_color_shift(image: np.ndarray, rng: random.Random) -> np.ndarray:
    data = image.astype(np.float32)
    contrast = rng.uniform(0.72, 1.08)
    brightness = rng.uniform(-18.0, 10.0)
    gamma = rng.uniform(0.85, 1.25)
    data = np.clip((data - 127.5) * contrast + 127.5 + brightness, 0, 255)
    data = 255.0 * np.power(np.clip(data / 255.0, 0, 1), gamma)
    return np.clip(data, 0, 255).astype(np.uint8)


def degrade_far_plate(sharp: np.ndarray, rng: random.Random) -> tuple[np.ndarray, dict[str, object]]:
    height, width = sharp.shape[:2]
    scale = rng.uniform(0.18, 0.42)
    small_w, small_h = max(12, int(width * scale)), max(4, int(height * scale))
    image = cv2.resize(sharp, (small_w, small_h), interpolation=cv2.INTER_AREA)
    image = cv2.resize(image, (width, height), interpolation=cv2.INTER_CUBIC)
    blur_length = rng.choice([3, 5, 7, 9])
    angle = rng.uniform(-8.0, 8.0)
    image = cv2.filter2D(image, -1, motion_kernel(blur_length, angle))
    if rng.random() < 0.55:
        image = cv2.GaussianBlur(image, (3, 3), rng.uniform(0.2, 0.8))
    image = apply_color_shift(image, rng)
    quality = rng.randint(28, 62)
    image = jpeg_roundtrip(image, quality)
    return image, {
        "profile": "far_small_plate",
        "scale": round(scale, 4),
        "motion_length": blur_length,
        "motion_angle": round(angle, 3),
        "jpeg_quality": quality,
    }


def degrade_fast_plate(sharp: np.ndarray, rng: random.Random) -> tuple[np.ndarray, dict[str, object]]:
    image = sharp.copy()
    blur_length = rng.choice([5, 7, 9, 11, 13, 15])
    angle = rng.uniform(-14.0, 14.0)
    image = cv2.filter2D(image, -1, motion_kernel(blur_length, angle))
    if rng.random() < 0.7:
        noise = np.random.default_rng(rng.randint(0, 2**31 - 1)).normal(0.0, rng.uniform(1.0, 4.5), image.shape)
        image = np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    image = apply_color_shift(image, rng)
    if rng.random() < 0.45:
        small = cv2.resize(image, (max(16, image.shape[1] // 2), max(8, image.shape[0] // 2)), interpolation=cv2.INTER_AREA)
        image = cv2.resize(small, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_CUBIC)
    quality = rng.randint(35, 78)
    image = jpeg_roundtrip(image, quality)
    return image, {
        "profile": "fast_surveillance",
        "motion_length": blur_length,
        "motion_angle": round(angle, 3),
        "jpeg_quality": quality,
    }


def load_sharp(sample: SharpSample, size: tuple[int, int]) -> np.ndarray | None:
    image = read_image(sample.image_path)
    if image is None:
        return None
    if sample.quad is not None:
        return warp_plate(image, sample.quad, size)
    return resize_plate(image, size, target=True)


def load_paired_blur(sample: SharpSample, size: tuple[int, int]) -> np.ndarray | None:
    if sample.label_path is None:
        return None
    image = read_image(sample.label_path)
    if image is None:
        return None
    return resize_plate(image, size, target=False)


def prepare_dirs(output: Path) -> None:
    for split in ("train", "val", "test"):
        (output / split / "blur").mkdir(parents=True, exist_ok=True)
        (output / split / "sharp").mkdir(parents=True, exist_ok=True)


def write_pair(
    output: Path,
    split: str,
    name: str,
    blur: np.ndarray,
    sharp: np.ndarray,
) -> tuple[str, str]:
    blur_rel = f"{split}/blur/{name}.jpg"
    sharp_rel = f"{split}/sharp/{name}.jpg"
    cv2.imwrite(str(output / blur_rel), blur, [cv2.IMWRITE_JPEG_QUALITY, 95])
    cv2.imwrite(str(output / sharp_rel), sharp, [cv2.IMWRITE_JPEG_QUALITY, 98])
    return blur_rel, sharp_rel


def make_preview(output: Path, records: list[dict[str, object]], size: tuple[int, int], count: int) -> None:
    if count <= 0 or not records:
        return
    width, height = size
    selected = records[:count]
    columns = 4
    rows = math.ceil(len(selected) / columns)
    tile = np.full((rows * height * 2, columns * width, 3), 255, dtype=np.uint8)
    for index, record in enumerate(selected):
        row, col = divmod(index, columns)
        blur = read_image(output / str(record["blur"]))
        sharp = read_image(output / str(record["sharp"]))
        if blur is None or sharp is None:
            continue
        x = col * width
        y = row * height * 2
        tile[y : y + height, x : x + width] = sharp
        tile[y + height : y + height * 2, x : x + width] = blur
    cv2.imwrite(str(output / "preview_grid.jpg"), tile, [cv2.IMWRITE_JPEG_QUALITY, 95])


def cap_split(records: list[SharpSample], split: str, max_pairs: int, variants_per_image: int) -> list[SharpSample]:
    if max_pairs <= 0:
        return records
    max_samples = max(1, math.ceil(max_pairs / max(1, variants_per_image)))
    return records[:max_samples]


def build_dataset(args: argparse.Namespace) -> dict[str, object]:
    rng = random.Random(args.seed)
    size = (args.size[0], args.size[1])
    prepare_dirs(args.output)

    samples = list(iter_obb_samples(args.obb_root))
    samples.extend(split_paired_train(sample, args.val_ratio) and sample for sample in iter_paired_samples(args.paired_root, "tinyunet"))
    samples.extend(split_paired_train(sample, args.val_ratio) and sample for sample in iter_paired_samples(args.mdlp_root, "mdlp_mini"))
    normalized_samples = [
        SharpSample(sample.source, split_paired_train(sample, args.val_ratio), sample.image_path, sample.label_path, sample.quad, sample.sample_id)
        for sample in samples
        if sample is not None
    ]
    rng.shuffle(normalized_samples)

    by_split: dict[str, list[SharpSample]] = {"train": [], "val": [], "test": []}
    for sample in normalized_samples:
        by_split.setdefault(sample.split, []).append(sample)
    by_split["train"] = cap_split(by_split["train"], "train", args.max_train_pairs, args.variants_per_image)
    by_split["val"] = cap_split(by_split["val"], "val", args.max_val_pairs, args.variants_per_image)
    by_split["test"] = cap_split(by_split["test"], "test", args.max_test_pairs, args.variants_per_image)

    manifests = {split: (args.output / f"manifest_{split}.jsonl").open("w", encoding="utf-8") for split in ("train", "val", "test")}
    preview_records: list[dict[str, object]] = []
    counts: Counter[str] = Counter()
    invalid: list[str] = []
    profiles = [degrade_far_plate, degrade_fast_plate]

    try:
        for split, split_samples in by_split.items():
            for sample in split_samples:
                sharp = load_sharp(sample, size)
                if sharp is None:
                    invalid.append(str(sample.image_path))
                    continue

                paired_blur = load_paired_blur(sample, size) if sample.quad is None else None
                variants: list[tuple[np.ndarray, dict[str, object]]] = []
                if paired_blur is not None:
                    variants.append((paired_blur, {"profile": "paired_original"}))
                for variant_index in range(args.variants_per_image):
                    profile = profiles[variant_index % len(profiles)]
                    local_rng = random.Random(f"{args.seed}:{sample.sample_id}:{variant_index}")
                    variants.append(profile(sharp, local_rng))

                for variant_index, (blur, degradation) in enumerate(variants[: args.variants_per_image]):
                    name = f"{sample.source}__{sample.sample_id}__v{variant_index}"
                    blur_rel, sharp_rel = write_pair(args.output, split, name, blur, sharp)
                    record = {
                        "id": name,
                        "source": sample.source,
                        "split": split,
                        "blur": blur_rel,
                        "sharp": sharp_rel,
                        "source_image": str(sample.image_path),
                        "source_label": str(sample.label_path) if sample.label_path is not None else None,
                        "quad": sample.quad.tolist() if sample.quad is not None else None,
                        "size": [size[0], size[1]],
                        "degradation": degradation,
                    }
                    manifests[split].write(json.dumps(record, ensure_ascii=False) + "\n")
                    counts[f"{split}:{sample.source}"] += 1
                    if len(preview_records) < args.preview:
                        preview_records.append(record)
    finally:
        for manifest in manifests.values():
            manifest.close()

    info = {
        "format": "synthetic paired license plate deblurring",
        "size": [size[0], size[1]],
        "seed": args.seed,
        "variants_per_image": args.variants_per_image,
        "sources": {
            "obb_root": str(args.obb_root),
            "paired_root": str(args.paired_root),
            "mdlp_root": str(args.mdlp_root),
        },
        "counts": dict(sorted(counts.items())),
        "invalid": invalid,
        "notes": [
            "OBB samples are perspective-warped to sharp plates.",
            "Synthetic blur profiles target small far-away plates and fast surveillance motion blur.",
        ],
    }
    (args.output / "dataset_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "README.txt").write_text(
        "plate_deblur_dataset_v2\n"
        "Each split contains blur/ and sharp/ images with matching file names.\n"
        "Sharp OBB samples are cropped from plate_dataset_obb_finetune and synthetic degradations are generated at 320x96.\n",
        encoding="utf-8",
    )
    make_preview(args.output, preview_records, size, args.preview)
    return info


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Colab-ready synthetic 320x96 deblurring dataset.")
    parser.add_argument("--obb-root", type=Path, default=PROJECT_DIR / "Dataset" / "plate_dataset_obb_finetune")
    parser.add_argument("--paired-root", type=Path, default=PROJECT_DIR / "Dataset" / "dataset")
    parser.add_argument("--mdlp-root", type=Path, default=PROJECT_DIR / "Dataset" / "MDLP_Mini")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--size", type=int, nargs=2, default=[DEFAULT_WIDTH, DEFAULT_HEIGHT], metavar=("WIDTH", "HEIGHT"))
    parser.add_argument("--variants-per-image", type=int, default=2)
    parser.add_argument("--max-train-pairs", type=int, default=70000)
    parser.add_argument("--max-val-pairs", type=int, default=8000)
    parser.add_argument("--max-test-pairs", type=int, default=8000)
    parser.add_argument("--val-ratio", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=20260625)
    parser.add_argument("--preview", type=int, default=64)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--zip", action="store_true", help="Create a zip archive next to the output directory.")
    args = parser.parse_args()

    if args.variants_per_image < 1:
        raise ValueError("--variants-per-image must be at least 1")
    if args.clean and args.output.exists():
        shutil.rmtree(args.output)
    if args.output.exists() and any(args.output.iterdir()) and not args.clean:
        raise FileExistsError(f"Output already exists. Use --clean to rebuild: {args.output}")

    info = build_dataset(args)
    if args.zip:
        archive_base = args.output.with_suffix("")
        archive_path = shutil.make_archive(str(archive_base), "zip", args.output)
        print(f"Zip: {archive_path}")

    print("Build complete.")
    for key, value in info["counts"].items():
        print(f"  {key}: {value}")
    print(f"  invalid: {len(info['invalid'])}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
