"""Build a YOLO-OBB fine-tuning dataset from CCPD, CRPD, and reviewed video hard cases."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CCPD_ROOT = PROJECT_DIR / "Dataset" / "plate_dataset_mini"
DEFAULT_OUTPUT = PROJECT_DIR / "Dataset" / "plate_dataset_obb_finetune"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def find_ccpd_quad(filename: str) -> np.ndarray:
    """Read the four CCPD plate vertices embedded in the filename."""
    for part in Path(filename).stem.split("-"):
        entries = part.split("_")
        if len(entries) != 4 or not all("&" in entry for entry in entries):
            continue
        try:
            points = np.array([[float(value) for value in entry.split("&")] for entry in entries], dtype=np.float32)
        except ValueError:
            continue
        if points.shape == (4, 2):
            return order_quad(points)
    raise ValueError(f"Could not find CCPD quadrilateral in filename: {filename}")


def order_quad(points: np.ndarray) -> np.ndarray:
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    ordered = points[np.argsort(angles)]
    start = np.argmin(ordered.sum(axis=1))
    return np.roll(ordered, -start, axis=0)


def yolo_obb_line(points: np.ndarray, width: int, height: int) -> str:
    normalized = points.copy()
    normalized[:, 0] = np.clip(normalized[:, 0] / width, 0.0, 1.0)
    normalized[:, 1] = np.clip(normalized[:, 1] / height, 0.0, 1.0)
    values = " ".join(f"{value:.6f}" for point in normalized for value in point)
    return f"0 {values}\n"


def split_for_name(name: str, val_ratio: float) -> str:
    value = int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "val" if value < val_ratio else "train"


def prepare_dirs(output_root: Path) -> None:
    for split in ("train", "val"):
        (output_root / "images" / split).mkdir(parents=True, exist_ok=True)
        (output_root / "labels" / split).mkdir(parents=True, exist_ok=True)


def place_image(source: Path, destination: Path, file_mode: str) -> None:
    """Avoid duplicating a large local dataset when all paths are on the same volume."""
    if file_mode == "hardlink":
        try:
            os.link(source, destination)
            return
        except OSError:
            # Copying keeps the command usable when sources live on another drive.
            pass
    shutil.copy2(source, destination)


def read_image_size(image_path: Path) -> tuple[int, int] | None:
    """Read JPEG/PNG headers without decoding high-resolution image pixels."""
    try:
        with Image.open(image_path) as image:
            return image.size
    except OSError:
        return None


def source_tag(root: Path) -> str:
    """Create a stable prefix so source files with equal names cannot collide."""
    return "".join(character if character.isalnum() else "_" for character in root.name)


def find_ccpd_split_dir(ccpd_root: Path, split: str) -> Path | None:
    """Support the mini CCPD layout and CCPD2020/ccpd_green layout."""
    candidates = (
        ccpd_root / "images" / split,
        ccpd_root / "ccpd_green" / split,
        ccpd_root / split,
    )
    return next((candidate for candidate in candidates if candidate.is_dir()), None)


def copy_ccpd(ccpd_root: Path, output_root: Path, file_mode: str, resume: bool) -> dict[str, int]:
    counts = {"train": 0, "val": 0, "invalid": 0, "existing": 0}
    for split in ("train", "val"):
        split_dir = find_ccpd_split_dir(ccpd_root, split)
        if split_dir is None:
            continue
        for image_path in sorted(split_dir.glob("*")):
            if image_path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            size = read_image_size(image_path)
            if size is None:
                counts["invalid"] += 1
                continue
            try:
                quad = find_ccpd_quad(image_path.name)
            except ValueError:
                counts["invalid"] += 1
                continue
            width, height = size
            target_name = f"{source_tag(ccpd_root)}__{image_path.name}"
            target_image = output_root / "images" / split / target_name
            target_label = output_root / "labels" / split / f"{Path(target_name).stem}.txt"
            if resume and target_image.is_file() and target_label.is_file():
                counts[split] += 1
                counts["existing"] += 1
                continue
            place_image(image_path, target_image, file_mode)
            target_label.write_text(yolo_obb_line(quad, width, height), encoding="utf-8")
            counts[split] += 1
    return counts


def read_crpd_quads(label_path: Path) -> tuple[list[np.ndarray], int]:
    """Read CRPD's absolute-pixel quadrilaterals; later fields are plate type/text."""
    quads: list[np.ndarray] = []
    invalid_lines = 0
    for line in label_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        fields = line.split()
        if len(fields) < 8:
            invalid_lines += 1
            continue
        try:
            points = np.array([float(value) for value in fields[:8]], dtype=np.float32).reshape(4, 2)
        except ValueError:
            invalid_lines += 1
            continue
        if cv2.contourArea(points) < 4.0:
            invalid_lines += 1
            continue
        quads.append(order_quad(points))
    return quads, invalid_lines


def copy_crpd(crpd_root: Path, output_root: Path, file_mode: str, resume: bool) -> dict[str, int]:
    """Convert CRPD full-frame annotations to single-class YOLO-OBB labels."""
    counts = {"train": 0, "val": 0, "invalid_images": 0, "invalid_labels": 0, "empty_labels": 0, "existing": 0}
    for split in ("train", "val"):
        image_dir = crpd_root / split / "images"
        label_dir = crpd_root / split / "labels"
        if not image_dir.is_dir() or not label_dir.is_dir():
            continue
        for image_path in sorted(image_dir.glob("*")):
            if image_path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            label_path = label_dir / f"{image_path.stem}.txt"
            if not label_path.is_file():
                counts["invalid_labels"] += 1
                continue
            size = read_image_size(image_path)
            if size is None:
                counts["invalid_images"] += 1
                continue
            quads, invalid_lines = read_crpd_quads(label_path)
            counts["invalid_labels"] += invalid_lines
            if not quads:
                counts["empty_labels"] += 1
                continue
            width, height = size
            target_name = f"{source_tag(crpd_root)}__{image_path.name}"
            target_image = output_root / "images" / split / target_name
            target_label = output_root / "labels" / split / f"{Path(target_name).stem}.txt"
            if resume and target_image.is_file() and target_label.is_file():
                counts[split] += 1
                counts["existing"] += 1
                continue
            place_image(image_path, target_image, file_mode)
            target_label.write_text("".join(yolo_obb_line(quad, width, height) for quad in quads), encoding="utf-8")
            counts[split] += 1
    return counts


def merge_reviewed_hard_cases(review_root: Path, output_root: Path, val_ratio: float) -> dict[str, int]:
    counts = {"train": 0, "val": 0, "negative_train": 0, "negative_val": 0, "unreviewed": 0}
    image_dir = review_root / "images"
    label_dir = review_root / "labels"
    skipped_dir = review_root / "skipped"
    if not image_dir.exists() or not label_dir.exists():
        return counts

    for image_path in sorted(image_dir.glob("*")):
        if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        label_path = label_dir / f"{image_path.stem}.txt"
        negative_marker = skipped_dir / f"{image_path.stem}.skip"
        has_positive_label = label_path.exists() and bool(label_path.read_text(encoding="utf-8").strip())
        if not has_positive_label and not negative_marker.exists():
            counts["unreviewed"] += 1
            continue
        split = split_for_name(image_path.name, val_ratio)
        target_name = f"hard_{image_path.name}"
        shutil.copy2(image_path, output_root / "images" / split / target_name)
        target_label = output_root / "labels" / split / f"hard_{image_path.stem}.txt"
        if has_positive_label:
            shutil.copy2(label_path, target_label)
            counts[split] += 1
        else:
            target_label.write_text("", encoding="utf-8")
            counts[f"negative_{split}"] += 1
    return counts


def write_yaml(output_root: Path) -> Path:
    yaml_path = output_root / "plate_obb_finetune.yaml"
    yaml_path.write_text(
        "\n".join(
            [
                f"path: {output_root.as_posix()}",
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
    return yaml_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a YOLO-OBB fine-tuning dataset from CCPD, CRPD, and reviewed hard cases.")
    parser.add_argument(
        "--ccpd-root",
        type=Path,
        action="append",
        default=None,
        help="CCPD root. Repeat for multiple sources; supports mini CCPD and CCPD2020 layouts.",
    )
    parser.add_argument(
        "--crpd-root",
        type=Path,
        action="append",
        default=[],
        help="CRPD root with train/val/images and train/val/labels. Repeat for single, double, and multi.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--file-mode",
        choices=("hardlink", "copy"),
        default="hardlink",
        help="How to place source images. hardlink avoids duplicating data on the same drive (default).",
    )
    parser.add_argument("--review-root", type=Path, help="Optional reviewed hard-case directory from export_obb_review_pack.py.")
    parser.add_argument("--hard-val-ratio", type=float, default=0.2)
    parser.add_argument("--clean", action="store_true", help="Delete the output dataset before rebuilding it.")
    parser.add_argument("--resume", action="store_true", help="Skip image/label pairs that are already complete in the output dataset.")
    args = parser.parse_args()

    if args.clean and args.output.exists():
        shutil.rmtree(args.output)
    prepare_dirs(args.output)
    ccpd_roots = args.ccpd_root or [DEFAULT_CCPD_ROOT]
    ccpd_counts = {str(root): copy_ccpd(root, args.output, args.file_mode, args.resume) for root in ccpd_roots}
    crpd_counts = {str(root): copy_crpd(root, args.output, args.file_mode, args.resume) for root in args.crpd_root}
    hard_counts = merge_reviewed_hard_cases(args.review_root, args.output, args.hard_val_ratio) if args.review_root else {}
    yaml_path = write_yaml(args.output)

    print(f"CCPD: {ccpd_counts}")
    if crpd_counts:
        print(f"CRPD: {crpd_counts}")
    if hard_counts:
        print(f"Reviewed hard cases: {hard_counts}")
    print(f"Dataset YAML: {yaml_path}")


if __name__ == "__main__":
    main()
