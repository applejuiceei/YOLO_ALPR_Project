import argparse
import csv
import html
import json
import os
import site
from pathlib import Path
from typing import Any

import cv2


DEFAULT_BASE = r"D:\YOLO_ALPR_Project\captures_topk"
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(Path(__file__).resolve().parent / "PaddleCache"))
PROJECT_DIR = Path(__file__).resolve().parent
for local_deps in (PROJECT_DIR / "python_deps", PROJECT_DIR / "python_deps_ocr"):
    if local_deps.exists():
        site.addsitedir(str(local_deps))


def find_latest_run(base_dir: Path) -> Path:
    runs = sorted([p for p in base_dir.glob("run_*") if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
    if not runs:
        raise FileNotFoundError(f"No run_* directories found under {base_dir}")
    return runs[0]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_ocr_engine(engine: str) -> tuple[Any, Any, Any, bool]:
    is_plate_like = None
    use_vehicle_first = False
    if engine in ("plate-rec", "plate-rec-ort", "plate-rec-cv2"):
        from plate_rec_ocr import PlateRecONNX

        backend = {
            "plate-rec": "auto",
            "plate-rec-ort": "onnxruntime",
            "plate-rec-cv2": "cv2",
        }[engine]
        ocr = PlateRecONNX(backend=backend)
        return ocr, ocr.recognize, ocr.is_plate_like, use_vehicle_first

    if engine == "hyperlpr3":
        from hyperlpr3_ocr import HyperLPR3OCR
        from plate_rec_ocr import PlateRecONNX

        ocr = HyperLPR3OCR()
        use_vehicle_first = True
        return ocr, ocr.recognize, PlateRecONNX.is_plate_like, use_vehicle_first

    from paddleocr import PaddleOCR

    try:
        ocr = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False)
    except ValueError:
        ocr = PaddleOCR(use_textline_orientation=False, lang="ch")

    def recognize(image: Any) -> tuple[str | None, float | None]:
        return parse_ocr_result(ocr_image(ocr, image))

    return ocr, recognize, is_plate_like, use_vehicle_first


def run_ocr_on_report(
    run_dir: Path,
    track_summaries: list[tuple[Path, dict[str, Any]]],
    engine: str,
    overwrite: bool,
) -> None:
    print(f"Loading {engine} OCR for saved Top-K plates...")
    try:
        _ocr, recognize, is_plate_like, use_vehicle_first = build_ocr_engine(engine)
    except Exception as exc:
        print(f"WARNING: OCR could not be initialized. Report will be generated without OCR. Error: {exc}")
        return

    for track_dir, summary in track_summaries:
        changed = False
        for candidate in summary.get("candidates", []):
            if overwrite:
                candidate.pop("ocr", None)
                candidate.pop("ocr_raw", None)
                candidate.pop("ocr_error", None)
                changed = True
            elif "ocr" in candidate or "ocr_raw" in candidate:
                continue
            try:
                text = None
                confidence = None
                file_order = ["vehicle", "plate"] if use_vehicle_first else ["plate"]
                for file_key in file_order:
                    rel_path = candidate.get("files", {}).get(file_key)
                    if not rel_path:
                        continue
                    image = cv2.imread(str(track_dir / rel_path))
                    if image is None:
                        continue
                    text, confidence = recognize(image)
                    if text:
                        break
            except Exception as exc:
                candidate["ocr_error"] = str(exc)
                changed = True
                continue
            if text:
                ocr_payload = {
                    "text": text,
                    "confidence": confidence,
                    "engine": engine,
                }
                if is_plate_like is None or is_plate_like(text):
                    candidate["ocr"] = ocr_payload
                    candidate.pop("ocr_error", None)
                    candidate.pop("ocr_raw", None)
                else:
                    candidate["ocr_raw"] = ocr_payload
                changed = True
        if changed:
            save_json(track_dir / "summary.json", summary)


def ocr_image(ocr: Any, image: Any) -> Any:
    try:
        return ocr.ocr(image, cls=False)
    except TypeError:
        return ocr.ocr(image)


def parse_ocr_result(result: Any) -> tuple[str | None, float | None]:
    if not result:
        return None, None

    # Old PaddleOCR format: [[[[box], (text, score)], ...]]
    try:
        if isinstance(result, list) and result and isinstance(result[0], list) and result[0]:
            first = result[0][0]
            if isinstance(first, (list, tuple)) and len(first) >= 2:
                text_score = first[1]
                if isinstance(text_score, (list, tuple)) and len(text_score) >= 2:
                    return str(text_score[0]), float(text_score[1])
    except Exception:
        pass

    # New PaddleOCR/PaddleX format: [{'rec_texts': [...], 'rec_scores': [...], ...}]
    try:
        first = result[0] if isinstance(result, list) else result
        getter = first.get if hasattr(first, "get") else None
        if getter:
            texts = getter("rec_texts") or getter("texts") or getter("text")
            scores = getter("rec_scores") or getter("scores") or getter("confidence")
            if isinstance(texts, list) and texts:
                score = scores[0] if isinstance(scores, list) and scores else None
                return str(texts[0]), float(score) if score is not None else None
            if isinstance(texts, str):
                return texts, float(scores) if isinstance(scores, (float, int)) else None
    except Exception:
        pass

    return None, None


def flatten_candidate(run_dir: Path, track_dir: Path, summary: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    files = candidate.get("files", {})
    subscores = candidate.get("subscores", {})
    metrics = candidate.get("raw_metrics", {})
    geometry = candidate.get("geometry", {})
    ocr = candidate.get("ocr", {})
    ocr_raw = candidate.get("ocr_raw", {})
    plate_path = track_dir / files.get("plate", "")
    vehicle_path = track_dir / files.get("vehicle", "")
    full_path = track_dir / files.get("full", "")
    return {
        "track_id": summary.get("track_id"),
        "rank": candidate.get("rank"),
        "frame_idx": candidate.get("frame_idx"),
        "score": candidate.get("score"),
        "ocr_text": ocr.get("text", ""),
        "ocr_confidence": ocr.get("confidence", ""),
        "ocr_raw_text": ocr_raw.get("text", ""),
        "ocr_raw_confidence": ocr_raw.get("confidence", ""),
        "ocr_error": candidate.get("ocr_error", ""),
        "plate_area_score": subscores.get("plate_area_score"),
        "sharpness_score": subscores.get("sharpness_score"),
        "exposure_score": subscores.get("exposure_score"),
        "contrast_score": subscores.get("contrast_score"),
        "obb_score": subscores.get("obb_score"),
        "plate_area": metrics.get("plate_area"),
        "laplacian_variance": metrics.get("laplacian_variance"),
        "gray_std": metrics.get("gray_std"),
        "clipped_ratio": metrics.get("clipped_ratio"),
        "obb_confidence": metrics.get("obb_confidence"),
        "plate_aspect": geometry.get("aspect"),
        "vehicle_overlap": geometry.get("vehicle_overlap"),
        "plate_path": str(plate_path),
        "vehicle_path": str(vehicle_path),
        "full_path": str(full_path),
        "track_dir": str(track_dir),
        "run_dir": str(run_dir),
    }


def collect_rows(run_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for track_dir in sorted(run_dir.glob("track_*"), key=lambda p: int(p.name.split("_")[-1])):
        summary_path = track_dir / "summary.json"
        if not summary_path.exists():
            continue
        summary = load_json(summary_path)
        for candidate in summary.get("candidates", []):
            rows.append(flatten_candidate(run_dir, track_dir, summary, candidate))
    return rows


def write_csv(rows: list[dict[str, Any]], out_path: Path) -> None:
    if not rows:
        out_path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def rel_path(path: str, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def write_html(
    rows: list[dict[str, Any]],
    run_dir: Path,
    out_path: Path,
    track_summaries: list[tuple[Path, dict[str, Any]]],
) -> None:
    summaries_by_track = {int(summary["track_id"]): (track_dir, summary) for track_dir, summary in track_summaries}
    track_ids = sorted(summaries_by_track)
    parts = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'>",
        "<title>Top-K ALPR Report</title>",
        "<style>",
        "body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f6f7f8;color:#1f2933}",
        "h1{font-size:22px;margin-bottom:4px}.meta{color:#5b6673;margin-bottom:18px}",
        "section{margin:20px 0;padding:16px;background:white;border:1px solid #d7dde3;border-radius:8px}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:14px}",
        ".card{border:1px solid #d7dde3;border-radius:8px;padding:10px;background:#fff}",
        ".rejected{border-color:#f0b8b2;background:#fffafa}.rejected h3{color:#b42318;font-size:15px;margin:0 0 8px}",
        ".plate{width:320px;height:96px;object-fit:contain;background:#111;display:block;margin-bottom:8px}",
        ".vehicle{max-width:320px;max-height:180px;object-fit:contain;background:#eee;display:block;margin-top:6px}",
        "table{border-collapse:collapse;font-size:13px}td{padding:2px 8px 2px 0;vertical-align:top}",
        ".ocr{font-size:18px;font-weight:700;color:#0f766e}.bad{color:#b42318}.score{font-weight:700}",
        "a{color:#1d4ed8;text-decoration:none}",
        "</style></head><body>",
        "<h1>Top-K ALPR Report</h1>",
        f"<div class='meta'>Run: {html.escape(str(run_dir))} | tracks: {len(track_ids)} | candidates: {len(rows)}</div>",
    ]

    for track_id in track_ids:
        track_dir, summary = summaries_by_track[track_id]
        track_rows = [row for row in rows if row["track_id"] == track_id]
        best = track_rows[0] if track_rows else {}
        parts.append(f"<section><h2>Track {track_id}</h2>")
        locked_text = summary.get("locked_text") or "(not locked)"
        locked_frame = summary.get("locked_frame")
        parts.append(
            f"<div class='meta'>Locked: <span class='ocr'>{html.escape(str(locked_text))}</span>"
            f" | frame: {html.escape(str(locked_frame if locked_frame is not None else '-'))}"
            f" | plate hits: {html.escape(str(summary.get('plate_hits', 0)))}"
            f" | rejected: {html.escape(str(summary.get('rejected_count', 0)))}</div>"
        )
        if best:
            ocr_text = best.get("ocr_text") or "(no OCR)"
            parts.append(
                f"<div class='meta'>Best score: {float(best['score']):.4f} | "
                f"Best OCR: <span class='ocr'>{html.escape(str(ocr_text))}</span></div>"
            )
        vote_events = summary.get("vote_events", [])
        if vote_events:
            parts.append("<table><tr><th>Vote frame</th><th>Text</th><th>Confidence</th><th>Source</th><th>Weight</th></tr>")
            for event in vote_events:
                confidence = event.get("confidence")
                weight = event.get("weight")
                confidence_text = f"{float(confidence):.3f}" if confidence is not None else ""
                weight_text = f"{float(weight):.3f}" if weight is not None else ""
                parts.append(
                    "<tr>"
                    f"<td>{html.escape(str(event.get('frame_idx', '')))}</td>"
                    f"<td>{html.escape(str(event.get('text', '')))}</td>"
                    f"<td>{confidence_text}</td>"
                    f"<td>{html.escape(str(event.get('source', '')))}</td>"
                    f"<td>{weight_text}</td>"
                    "</tr>"
                )
            parts.append("</table>")
        parts.append("<div class='grid'>")
        for row in track_rows:
            plate_rel = rel_path(row["plate_path"], run_dir)
            vehicle_rel = rel_path(row["vehicle_path"], run_dir)
            ocr_text = row.get("ocr_text") or ""
            ocr_conf = row.get("ocr_confidence")
            raw_text = row.get("ocr_raw_text") or ""
            raw_conf = row.get("ocr_raw_confidence")
            ocr_error = row.get("ocr_error") or ""
            ocr_label = html.escape(str(ocr_text)) if ocr_text else "<span class='bad'>(no OCR)</span>"
            if ocr_conf != "":
                ocr_label += f" ({float(ocr_conf):.3f})"
            if raw_text:
                ocr_label += f"<br><span>raw: {html.escape(str(raw_text))}"
                if raw_conf != "":
                    ocr_label += f" ({float(raw_conf):.3f})"
                ocr_label += "</span>"
            if ocr_error:
                ocr_label += f"<br><span class='bad'>{html.escape(str(ocr_error)[:160])}</span>"
            parts.extend(
                [
                    "<div class='card'>",
                    f"<img class='plate' src='{html.escape(plate_rel)}'>",
                    "<table>",
                    f"<tr><td>Rank</td><td>{row['rank']}</td></tr>",
                    f"<tr><td>Frame</td><td>{row['frame_idx']}</td></tr>",
                    f"<tr><td>Score</td><td class='score'>{float(row['score']):.4f}</td></tr>",
                    f"<tr><td>OCR</td><td>{ocr_label}</td></tr>",
                    f"<tr><td>Sharpness</td><td>{float(row['sharpness_score']):.3f}</td></tr>",
                    f"<tr><td>OBB</td><td>{float(row['obb_score']):.3f}</td></tr>",
                    f"<tr><td>Area</td><td>{float(row['plate_area']):.1f}</td></tr>",
                    f"<tr><td>Aspect</td><td>{float(row['plate_aspect']):.2f}</td></tr>",
                    f"<tr><td>Overlap</td><td>{float(row['vehicle_overlap']):.2f}</td></tr>",
                    "</table>",
                    f"<img class='vehicle' src='{html.escape(vehicle_rel)}'>",
                    f"<div><a href='{html.escape(plate_rel)}'>plate</a> | <a href='{html.escape(vehicle_rel)}'>vehicle</a></div>",
                    "</div>",
                ]
            )
        parts.append("</div></section>")

        rejected = summary.get("rejected_candidates", [])
        if rejected:
            parts.append(f"<section><h2>Track {track_id} Rejected OBBs</h2><div class='grid'>")
            for item in rejected:
                files = item.get("files", {})
                plate_rel = rel_path(str(track_dir / files.get("plate", "")), run_dir)
                vehicle_rel = rel_path(str(track_dir / files.get("vehicle", "")), run_dir)
                full_rel = rel_path(str(track_dir / files.get("full", "")), run_dir)
                reason = html.escape(str(item.get("reason", "")))
                parts.extend(
                    [
                        "<div class='card rejected'>",
                        f"<h3>Rejected: {reason}</h3>",
                        f"<img class='plate' src='{html.escape(plate_rel)}'>",
                        "<table>",
                        f"<tr><td>Frame</td><td>{html.escape(str(item.get('frame_idx', '')))}</td></tr>",
                        f"<tr><td>OBB</td><td>{float(item.get('obb_score', 0.0)):.3f}</td></tr>",
                        f"<tr><td>Area</td><td>{float(item.get('plate_area', 0.0)):.1f}</td></tr>",
                        "</table>",
                        f"<img class='vehicle' src='{html.escape(vehicle_rel)}'>",
                        f"<div><a href='{html.escape(plate_rel)}'>plate</a> | <a href='{html.escape(vehicle_rel)}'>vehicle</a> | <a href='{html.escape(full_rel)}'>full</a></div>",
                        "</div>",
                    ]
                )
            parts.append("</div></section>")

    parts.append("</body></html>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


def write_best_text_summary(rows: list[dict[str, Any]], out_path: Path) -> None:
    lines = []
    for track_id in sorted({row["track_id"] for row in rows}):
        track_rows = [row for row in rows if row["track_id"] == track_id]
        best = track_rows[0]
        text = best.get("ocr_text") or "(no OCR)"
        conf = best.get("ocr_confidence")
        conf_text = f"{float(conf):.3f}" if conf != "" else ""
        lines.append(
            f"track_{track_id}: rank{best['rank']} frame={best['frame_idx']} "
            f"score={float(best['score']):.4f} ocr={text} conf={conf_text} plate={best['plate_path']}"
        )
    out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a CSV/HTML report for a Top-K ALPR capture run.")
    parser.add_argument("--run-dir", help="Run directory. Defaults to latest run under --base.")
    parser.add_argument("--base", default=DEFAULT_BASE, help="Base captures_topk directory.")
    parser.add_argument("--with-ocr", action="store_true", help="Run OCR for candidates missing OCR.")
    parser.add_argument(
        "--ocr-engine",
        choices=["plate-rec", "plate-rec-ort", "plate-rec-cv2", "hyperlpr3", "paddle"],
        default="hyperlpr3",
        help="OCR engine used with --with-ocr.",
    )
    parser.add_argument("--overwrite-ocr", action="store_true", help="Refresh existing OCR/ocr_raw fields.")
    parser.add_argument("--csv-name", default="topk_report.csv", help="CSV filename written under run dir.")
    parser.add_argument("--html-name", default="topk_report.html", help="HTML filename written under run dir.")
    parser.add_argument("--text-name", default="best_ocr_summary.txt", help="Plain text summary filename.")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    run_dir = Path(args.run_dir) if args.run_dir else find_latest_run(Path(args.base))
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    track_summaries = []
    for track_dir in sorted(run_dir.glob("track_*"), key=lambda p: int(p.name.split("_")[-1])):
        summary_path = track_dir / "summary.json"
        if summary_path.exists():
            track_summaries.append((track_dir, load_json(summary_path)))

    if args.with_ocr:
        run_ocr_on_report(run_dir, track_summaries, args.ocr_engine, args.overwrite_ocr)

    rows = collect_rows(run_dir)
    rows.sort(key=lambda row: (int(row["track_id"]), int(row["rank"])))
    write_csv(rows, run_dir / args.csv_name)
    write_html(rows, run_dir, run_dir / args.html_name, track_summaries)
    write_best_text_summary(rows, run_dir / args.text_name)

    print(f"Report written for: {run_dir}")
    print(f"CSV : {run_dir / args.csv_name}")
    print(f"HTML: {run_dir / args.html_name}")
    print(f"TXT : {run_dir / args.text_name}")


if __name__ == "__main__":
    main()
