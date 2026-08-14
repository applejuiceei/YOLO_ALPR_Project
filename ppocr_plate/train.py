from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = PACKAGE_ROOT / "configs" / "plate_PP-OCRv4_mobile_rec.yml"
DEFAULT_DICTIONARY = PACKAGE_ROOT / "plate_chars.txt"
PROJECT_ROOT = PACKAGE_ROOT.parent
FORMAL_DATA_GATES = (
    "public_or_synthetic_train_at_least_100000",
    "real_verified_train_at_least_2000",
    "real_verified_val_at_least_500",
    "real_verified_test_at_least_500",
    "no_group_leakage",
    "no_exact_image_hash_duplicates",
    "public_data_license_verified",
)


def locate_paddleocr_root(explicit: Path | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    configured = os.environ.get("PADDLEOCR_SOURCE_ROOT")
    if configured:
        candidates.append(Path(configured))
    candidates.extend((PROJECT_ROOT / "third_party" / "PaddleOCR", PROJECT_ROOT / "PaddleOCR"))
    for candidate in candidates:
        root = candidate.resolve()
        if (root / "tools" / "train.py").is_file() and (root / "ppocr").is_dir():
            return root
    try:
        import paddleocr

        candidates.append(Path(paddleocr.__file__).resolve().parent)
    except ImportError:
        pass
    if candidates:
        root = candidates[-1].resolve()
        if (root / "tools" / "train.py").is_file() and (root / "ppocr").is_dir():
            return root
    checked = "\n".join(f"  - {path.resolve()}" for path in candidates)
    raise FileNotFoundError(
        "PaddleOCR training source is required; the pip wheel normally contains inference "
        "only. Clone the official PaddleOCR repository and pass --paddleocr-root. Checked:\n"
        + checked
    )


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"invalid YAML config: {path}")
    return config


def resolve_checkpoint_prefix(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.suffix == ".pdparams" and resolved.is_file():
        return resolved.with_suffix("")
    params_file = Path(str(resolved) + ".pdparams")
    if params_file.is_file():
        return resolved
    raise FileNotFoundError(
        f"Paddle checkpoint not found: expected {resolved} or {params_file}"
    )


def validate_formal_data(splits: Path) -> dict[str, Any]:
    audit_path = splits / "audit.json"
    if not audit_path.is_file():
        raise FileNotFoundError(
            f"formal training requires a dataset audit: {audit_path}"
        )
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    gates = audit.get("quality_gates", {})
    failed = [name for name in FORMAL_DATA_GATES if gates.get(name) is not True]
    expected_dictionary_sha256 = hashlib.sha256(DEFAULT_DICTIONARY.read_bytes()).hexdigest()
    if (
        audit.get("dictionary_characters") != 76
        or audit.get("dictionary_sha256") != expected_dictionary_sha256
    ):
        failed.append("fixed_plate_dictionary_76_sha256")
    rows = audit.get("rows", {})
    if any(int(rows.get(name, 0)) < 1 for name in ("train", "val", "test")):
        failed.append("nonempty_train_val_test")
    if failed:
        raise ValueError(
            "formal training blocked by dataset audit gates: " + ", ".join(failed)
        )
    if not (splits / "canonical_manifest.tsv").is_file():
        raise FileNotFoundError(
            f"formal training requires canonical_manifest.tsv in {splits}"
        )
    return audit


def make_run_config(
    base_config: Path,
    splits: Path,
    data_root: Path,
    output_dir: Path,
    *,
    use_gpu: bool,
    epochs: int | None,
    batch_size: int | None,
    workers: int | None,
    pretrained: Path | None,
) -> Path:
    train_file = (splits / "train.txt").resolve()
    val_file = (splits / "val.txt").resolve()
    for path in (train_file, val_file):
        if not path.is_file():
            raise FileNotFoundError(path)
    config = load_config(base_config)
    global_config = config["Global"]
    global_config["use_gpu"] = use_gpu
    global_config["save_model_dir"] = output_dir.as_posix()
    global_config["character_dict_path"] = (PACKAGE_ROOT / "plate_chars.txt").as_posix()
    if epochs is not None:
        global_config["epoch_num"] = epochs
    if pretrained:
        global_config["pretrained_model"] = pretrained.resolve().as_posix()
    else:
        global_config.pop("pretrained_model", None)
    for section, label_file in (("Train", train_file), ("Eval", val_file)):
        dataset = config[section]["dataset"]
        dataset["data_dir"] = data_root.resolve().as_posix()
        dataset["label_file_list"] = [label_file.as_posix()]
        if workers is not None:
            config[section]["loader"]["num_workers"] = workers
        if sys.platform == "win32":
            # Paddle 2.6 can block indefinitely on the first batch when its
            # shared-memory reader is used from a Windows sandbox/service.
            config[section]["loader"]["use_shared_memory"] = False
        if batch_size is not None:
            config[section]["loader"]["batch_size_per_card"] = batch_size
    output_dir.mkdir(parents=True, exist_ok=False)
    generated = output_dir / "effective_config.yml"
    generated.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return generated


def run_paddle_tool(root: Path, script: str, config: Path, extra: list[str] | None = None) -> None:
    environment = os.environ.copy()
    python_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(root) + (os.pathsep + python_path if python_path else "")
    command = [sys.executable, str(root / "tools" / script), "-c", str(config)]
    command.extend(extra or [])
    print("running:", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=str(root), env=environment, check=True)


def command_smoke(args: argparse.Namespace) -> int:
    root = locate_paddleocr_root(args.paddleocr_root)
    splits = args.splits.resolve()
    train_count = sum(1 for line in (splits / "train.txt").read_text(encoding="utf-8").splitlines() if line)
    if train_count == 0:
        raise ValueError("smoke train split is empty")
    loader_batches = train_count // args.batch_size
    steps_per_epoch = loader_batches - (1 if sys.platform == "win32" else 0)
    if steps_per_epoch < 1:
        raise ValueError(
            "smoke split is too small for drop_last=True and this batch size; "
            "add samples or reduce --batch-size"
        )
    epochs = max(1, math.ceil(args.steps / steps_per_epoch))
    output = args.output.resolve() / f"smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    config = make_run_config(
        args.config.resolve(),
        splits,
        (args.data_root or splits.parent).resolve(),
        output,
        use_gpu=False,
        epochs=epochs,
        batch_size=args.batch_size,
        workers=0,
        pretrained=None,
    )
    run_paddle_tool(root, "train.py", config)
    export_dir = output / "inference"
    run_paddle_tool(
        root,
        "export_model.py",
        config,
        [
            "-o",
            f"Global.pretrained_model={(output / 'latest').as_posix()}",
            f"Global.save_inference_dir={export_dir.as_posix()}",
        ],
    )
    expected = [export_dir / "inference.pdmodel", export_dir / "inference.pdiparams"]
    missing = [str(path) for path in expected if not path.is_file()]
    if missing:
        raise RuntimeError(f"smoke export did not produce expected files: {missing}")
    print(
        f"smoke_steps_at_least={epochs * steps_per_epoch} output={output} "
        f"inference={export_dir}"
    )
    return 0


def command_train(args: argparse.Namespace) -> int:
    root = locate_paddleocr_root(args.paddleocr_root)
    splits = args.splits.resolve()
    validate_formal_data(splits)
    pretrained = resolve_checkpoint_prefix(args.pretrained)
    output = args.output.resolve() / f"train_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    config = make_run_config(
        args.config.resolve(),
        splits,
        (args.data_root or splits.parent).resolve(),
        output,
        use_gpu=args.device == "gpu",
        epochs=args.epochs,
        batch_size=args.batch_size,
        workers=args.workers,
        pretrained=pretrained,
    )
    run_paddle_tool(root, "train.py", config)
    return 0


def command_export(args: argparse.Namespace) -> int:
    root = locate_paddleocr_root(args.paddleocr_root)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    config = load_config(args.config.resolve())
    config["Global"]["character_dict_path"] = DEFAULT_DICTIONARY.as_posix()
    config["Global"]["pretrained_model"] = resolve_checkpoint_prefix(
        args.checkpoint
    ).as_posix()
    config["Global"]["save_inference_dir"] = output.as_posix()
    effective = output / "export_config.yml"
    effective.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    run_paddle_tool(root, "export_model.py", effective)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train and export the plate PP-OCR recognizer.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--paddleocr-root", type=Path)
    common.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    common.add_argument("--splits", type=Path, required=True)
    common.add_argument("--data-root", type=Path)

    smoke = subparsers.add_parser("smoke", parents=[common])
    smoke.add_argument("--output", type=Path, default=Path("runs_ppocr_plate_train"))
    smoke.add_argument("--steps", type=int, default=100)
    smoke.add_argument("--batch-size", type=int, default=4)
    smoke.set_defaults(function=command_smoke)

    train = subparsers.add_parser("train", parents=[common])
    train.add_argument("--pretrained", type=Path, required=True)
    train.add_argument("--output", type=Path, default=Path("runs_ppocr_plate_train"))
    train.add_argument("--device", choices=("cpu", "gpu"), default="gpu")
    train.add_argument("--epochs", type=int, default=100)
    train.add_argument("--batch-size", type=int, default=128)
    train.add_argument("--workers", type=int, default=8)
    train.set_defaults(function=command_train)

    export = subparsers.add_parser("export")
    export.add_argument("--paddleocr-root", type=Path)
    export.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    export.add_argument("--checkpoint", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.set_defaults(function=command_export)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if hasattr(args, "steps") and args.steps < 1:
            raise ValueError("--steps must be positive")
        if hasattr(args, "batch_size") and args.batch_size < 1:
            raise ValueError("--batch-size must be positive")
        if hasattr(args, "epochs") and args.epochs < 1:
            raise ValueError("--epochs must be positive")
        if hasattr(args, "workers") and args.workers < 0:
            raise ValueError("--workers must be non-negative")
        return int(args.function(args))
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
