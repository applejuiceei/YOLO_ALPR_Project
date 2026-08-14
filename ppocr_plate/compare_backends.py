from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _sample_key(raw_path: str) -> str:
    parts = Path(raw_path.replace("\\", "/")).parts
    return "/".join(parts[-2:]).lower()


def _load_result(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "samples" in payload:
        samples = payload["samples"]
        summary = (
            payload["summary"]
            if isinstance(payload.get("summary"), dict)
            else payload
        )
    else:
        raise ValueError(f"result has no samples array: {path}")
    rows: dict[str, dict[str, Any]] = {}
    for row in samples:
        raw_path = row.get("image") or row.get("sample_path")
        if not raw_path:
            raise ValueError(f"sample row has no image path: {path}")
        key = _sample_key(str(raw_path))
        if key in rows:
            raise ValueError(
                f"sample key collision {key!r} in {path}; preserve at least parent/name"
            )
        rows[key] = row
    quality = summary.get("quality") or summary.get("accuracy")
    if quality is None and isinstance(payload.get("summary"), dict):
        quality = payload["summary"].get("accuracy")
    return {"path": str(path.resolve()), "rows": rows, "quality": quality or {}}


def _parse_candidate(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("candidate must be NAME=results.json")
    name, raw_path = value.split("=", 1)
    if not name.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("candidate must be NAME=results.json")
    return name.strip(), Path(raw_path.strip())


def _exact_accuracy(result: dict[str, Any]) -> float | None:
    value = result["quality"].get("exact_accuracy")
    return float(value) if value is not None else None


def compare(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    reference_rows = reference["rows"]
    candidate_rows = candidate["rows"]
    common = sorted(reference_rows.keys() & candidate_rows.keys())
    disagreements = []
    for key in common:
        reference_text = str(reference_rows[key].get("text") or "")
        candidate_text = str(candidate_rows[key].get("text") or "")
        if reference_text != candidate_text:
            disagreements.append(
                {
                    "sample": key,
                    "reference_text": reference_text,
                    "candidate_text": candidate_text,
                }
            )
    reference_accuracy = _exact_accuracy(reference)
    candidate_accuracy = _exact_accuracy(candidate)
    accuracy_drop = (
        reference_accuracy - candidate_accuracy
        if reference_accuracy is not None and candidate_accuracy is not None
        else None
    )
    return {
        "reference_samples": len(reference_rows),
        "candidate_samples": len(candidate_rows),
        "common_samples": len(common),
        "missing_from_candidate": sorted(reference_rows.keys() - candidate_rows.keys()),
        "extra_in_candidate": sorted(candidate_rows.keys() - reference_rows.keys()),
        "text_agreement": (
            (len(common) - len(disagreements)) / len(common) if common else None
        ),
        "text_disagreement_count": len(disagreements),
        "text_disagreements": disagreements,
        "reference_exact_accuracy": reference_accuracy,
        "candidate_exact_accuracy": candidate_accuracy,
        "exact_accuracy_drop_points": (
            accuracy_drop * 100.0 if accuracy_drop is not None else None
        ),
        "gates": {
            "same_sample_set": (
                len(common) == len(reference_rows) == len(candidate_rows)
            ),
            "all_decoded_text_equal": bool(common) and not disagreements,
            "accuracy_drop_at_most_0_5_points": (
                accuracy_drop is not None and accuracy_drop <= 0.005
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare decoded text and quality across ONNX/OpenVINO/RKNN results."
    )
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument(
        "--candidate", type=_parse_candidate, action="append", required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite: {args.output}")
    reference = _load_result(args.reference.resolve())
    comparisons = {
        name: compare(reference, _load_result(path.resolve()))
        for name, path in args.candidate
    }
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "reference": reference["path"],
        "candidates": comparisons,
        "all_backends_same_samples": all(
            result["gates"]["same_sample_set"] for result in comparisons.values()
        ),
        "all_backends_text_consistent": all(
            result["gates"]["all_decoded_text_equal"]
            for result in comparisons.values()
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
