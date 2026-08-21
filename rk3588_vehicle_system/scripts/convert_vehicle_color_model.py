from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Convert the official PP-Vehicle attribute model to ONNX.")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=project_root / "models" / "vehicle_color" / "vehicle_attribute_model",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "models" / "vehicle_color" / "vehicle_attribute_pp_lcnet.onnx",
    )
    parser.add_argument(
        "--conversion-deps",
        type=Path,
        default=project_root / "third_party" / "python_conversion",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(args.conversion_deps.resolve()))
    import onnx  # type: ignore
    import paddle2onnx  # type: ignore

    model_file = args.model_dir / "model.pdmodel"
    params_file = args.model_dir / "model.pdiparams"
    if not model_file.is_file() or not params_file.is_file():
        raise FileNotFoundError(f"Official PP-Vehicle Paddle model is incomplete: {args.model_dir}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    paddle2onnx.export(
        model_filename=str(model_file),
        params_filename=str(params_file),
        save_file=str(args.output),
        opset_version=14,
        auto_upgrade_opset=False,
        verbose=True,
        enable_onnx_checker=True,
        enable_experimental_op=True,
        enable_optimize=True,
        deploy_backend="onnxruntime",
    )
    model = onnx.load(str(args.output))
    onnx.checker.check_model(model)
    print(f"ONNX check passed: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
