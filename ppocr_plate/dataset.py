from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .runtime import load_characters


REQUIRED_COLUMNS = ("image_path", "label", "group_id", "source", "readable")


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing columns {missing}")
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def image_decodes(path: Path) -> bool:
    if not path.is_file():
        return False
    encoded = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR) is not None


def audit_rows(
    rows: list[dict[str, str]],
    data_root: Path,
    characters: set[str],
    decode_images: bool,
    hash_images: bool,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    valid: list[dict[str, str]] = []
    errors: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    seen_hashes: dict[str, tuple[str, str]] = {}
    group_labels: dict[str, set[str]] = defaultdict(set)
    for index, row in enumerate(rows, start=2):
        reasons: list[str] = []
        relative = Path(row["image_path"])
        if relative.is_absolute() or ".." in relative.parts:
            reasons.append("image_path must be relative and stay inside data_root")
        normalized_path = relative.as_posix()
        if normalized_path in seen_paths:
            reasons.append("duplicate image_path")
        seen_paths.add(normalized_path)
        try:
            readable = int(row["readable"])
        except ValueError:
            readable = -1
        if readable not in (0, 1):
            reasons.append("readable must be 0 or 1")
        label = row["label"]
        if readable == 1:
            if len(label) not in (7, 8):
                reasons.append("readable plate label must have length 7 or 8")
            unknown = sorted(set(label) - characters)
            if unknown:
                reasons.append(f"label contains characters outside dictionary: {unknown}")
        if not row["group_id"]:
            reasons.append("group_id is empty")
        if not row["source"]:
            reasons.append("source is empty")
        if readable == 1 and row["source"].lower().startswith("real") and row[
            "source"
        ].lower() != "real_verified":
            reasons.append(
                "readable real captures must use source=real_verified after manual review"
            )
        image_path = data_root / relative
        if not image_path.is_file():
            reasons.append("image file missing")
        elif decode_images and not image_decodes(image_path):
            reasons.append("image cannot be decoded")
        if image_path.is_file() and hash_images:
            digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
            previous = seen_hashes.get(digest)
            if previous is not None:
                reasons.append(
                    "duplicate image content: "
                    f"{previous[0]} (previous group_id={previous[1]})"
                )
            else:
                seen_hashes[digest] = (normalized_path, row["group_id"])
        group_labels[row["group_id"]].add(label)
        if reasons:
            errors.append({"manifest_line": index, "row": row, "reasons": reasons})
        else:
            valid.append(row)
    for group_id, labels in group_labels.items():
        nonempty = {label for label in labels if label}
        if len(nonempty) > 1:
            errors.append(
                {
                    "group_id": group_id,
                    "reasons": [f"group has conflicting labels: {sorted(nonempty)}"],
                }
            )
    return valid, errors


def split_groups(
    rows: list[dict[str, str]], seed: int, split_all_sources: bool
) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["group_id"]].append(row)
    real_groups: list[str] = []
    train_only_groups: list[str] = []
    for group_id, members in grouped.items():
        is_real = any(member["source"].lower().startswith("real") for member in members)
        if split_all_sources or is_real:
            real_groups.append(group_id)
        else:
            train_only_groups.append(group_id)
    rng = random.Random(seed)
    rng.shuffle(real_groups)
    total = len(real_groups)
    train_end = int(round(total * (2.0 / 3.0)))
    val_end = train_end + int(round(total * (1.0 / 6.0)))
    if total >= 3:
        train_end = min(max(1, train_end), total - 2)
        val_end = min(max(train_end + 1, val_end), total - 1)
    assignments = {group_id: "train" for group_id in train_only_groups}
    assignments.update({group_id: "train" for group_id in real_groups[:train_end]})
    assignments.update({group_id: "val" for group_id in real_groups[train_end:val_end]})
    assignments.update({group_id: "test" for group_id in real_groups[val_end:]})
    splits = {"train": [], "val": [], "test": []}
    for row in rows:
        if row["readable"] == "1":
            splits[assignments[row["group_id"]]].append(row)
    return splits


def write_paddle_split(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(f"{row['image_path']}\t{row['label']}\n")


def command_build(args: argparse.Namespace) -> int:
    data_root = args.data_root.resolve()
    dictionary_path = args.dictionary.resolve()
    characters = set(load_characters(dictionary_path))
    dictionary_sha256 = hashlib.sha256(dictionary_path.read_bytes()).hexdigest()
    rows: list[dict[str, str]] = []
    for manifest in args.manifest:
        rows.extend(read_manifest(manifest.resolve()))
    valid, errors = audit_rows(
        rows,
        data_root,
        characters,
        args.decode_images,
        not args.skip_image_hash,
    )
    if errors:
        report = {"valid_rows": len(valid), "error_count": len(errors), "errors": errors}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()) and not args.overwrite:
        raise FileExistsError(f"output is not empty; use a new path or --overwrite: {output}")
    output.mkdir(parents=True, exist_ok=True)
    splits = split_groups(valid, args.seed, args.split_all_sources)
    for name, split_rows in splits.items():
        write_paddle_split(output / f"{name}.txt", split_rows)
    with (output / "canonical_manifest.tsv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS, delimiter="\t")
        writer.writeheader()
        writer.writerows(valid)
    group_sets = {
        name: {row["group_id"] for row in split_rows} for name, split_rows in splits.items()
    }
    leakage = {
        "train_val": sorted(group_sets["train"] & group_sets["val"]),
        "train_test": sorted(group_sets["train"] & group_sets["test"]),
        "val_test": sorted(group_sets["val"] & group_sets["test"]),
    }
    source_counts = {
        name: dict(Counter(row["source"] for row in split_rows))
        for name, split_rows in splits.items()
    }
    public_rows = sum(
        1 for row in valid if row["source"].lower().startswith("public")
    )
    report = {
        "data_root": str(data_root),
        "dictionary": str(dictionary_path),
        "dictionary_characters": len(characters),
        "dictionary_sha256": dictionary_sha256,
        "rows": {name: len(split_rows) for name, split_rows in splits.items()},
        "groups": {name: len(group_sets[name]) for name in splits},
        "sources": source_counts,
        "public_license_note": args.public_license_note,
        "group_leakage": leakage,
        "quality_gates": {
            "public_or_synthetic_train_at_least_100000": sum(
                count
                for source, count in source_counts["train"].items()
                if source.lower().startswith(("public", "synthetic"))
            )
            >= 100000,
            "real_verified_train_at_least_2000": sum(
                count
                for source, count in source_counts["train"].items()
                if source.lower() == "real_verified"
            )
            >= 2000,
            "real_verified_val_at_least_500": sum(
                count
                for source, count in source_counts["val"].items()
                if source.lower() == "real_verified"
            )
            >= 500,
            "real_verified_test_at_least_500": sum(
                count
                for source, count in source_counts["test"].items()
                if source.lower() == "real_verified"
            )
            >= 500,
            "no_group_leakage": not any(leakage.values()),
            "no_exact_image_hash_duplicates": not args.skip_image_hash,
            "public_data_license_verified": (
                public_rows == 0 or bool(args.public_license_note.strip())
            ),
        },
    }
    (output / "audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def command_template(args: argparse.Namespace) -> int:
    image_root = args.image_root.resolve()
    rows = []
    for pattern in ("*.jpg", "*.jpeg", "*.png", "*.bmp"):
        for path in image_root.rglob(pattern):
            rows.append(
                {
                    "image_path": path.relative_to(args.data_root.resolve()).as_posix(),
                    "label": "",
                    "group_id": "",
                    "source": args.source,
                    "readable": 0,
                }
            )
    rows.sort(key=lambda row: row["image_path"])
    if args.output.exists() and not args.overwrite:
        raise FileExistsError(f"refusing to overwrite: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    print(f"template_rows={len(rows)} output={args.output}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and audit leak-free PP-OCR plate datasets.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--data-root", type=Path, required=True)
    build.add_argument("--manifest", type=Path, action="append", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument(
        "--dictionary", type=Path, default=Path(__file__).resolve().parent / "plate_chars.txt"
    )
    build.add_argument("--seed", type=int, default=20260807)
    build.add_argument("--decode-images", action="store_true")
    build.add_argument(
        "--skip-image-hash",
        action="store_true",
        help="Skip exact-content SHA256 duplicate detection (not allowed for final audits).",
    )
    build.add_argument(
        "--public-license-note",
        default="",
        help="License name/URL verified for public rows; required by the formal-training gate.",
    )
    build.add_argument(
        "--split-all-sources",
        action="store_true",
        help="Use the 2/3,1/6,1/6 group split for synthetic/public data too (smoke tests only).",
    )
    build.add_argument("--overwrite", action="store_true")
    build.set_defaults(function=command_build)

    template = subparsers.add_parser("template")
    template.add_argument("--data-root", type=Path, required=True)
    template.add_argument("--image-root", type=Path, required=True)
    template.add_argument("--output", type=Path, required=True)
    template.add_argument("--source", default="real_unverified")
    template.add_argument("--overwrite", action="store_true")
    template.set_defaults(function=command_template)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return int(args.function(args))


if __name__ == "__main__":
    raise SystemExit(main())
