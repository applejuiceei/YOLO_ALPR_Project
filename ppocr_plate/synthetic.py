from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


PROVINCES = list("云京冀吉宁川新晋桂沪津浙渝湘琼甘皖粤苏蒙藏豫贵赣辽鄂闽陕青鲁黑")
LETTERS = list("ABCDEFGHJKLMNOPQRSTUVWXYZ")
ALNUM = list("0123456789ABCDEFGHJKLMNPQRSTUVWXYZ")
DEFAULT_FONTS = (
    Path(r"C:\Windows\Fonts\msyhbd.ttc"),
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path(r"C:\Windows\Fonts\msyh.ttc"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate deterministic synthetic plate crops.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--data-root",
        type=Path,
        help="Root used for manifest-relative paths (default: output parent).",
    )
    parser.add_argument("--count", type=int, default=100000)
    parser.add_argument("--seed", type=int, default=20260807)
    parser.add_argument("--font", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.count <= 0:
        parser.error("--count must be positive")
    return args


def choose_font(path: Path | None, size: int = 58) -> ImageFont.FreeTypeFont:
    candidates = [path] if path else list(DEFAULT_FONTS)
    for candidate in candidates:
        if candidate and candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    raise FileNotFoundError("no CJK font found; pass --font explicitly")


def make_label(rng: random.Random) -> tuple[str, str]:
    kind = rng.choices(["blue", "yellow", "green"], weights=[0.58, 0.17, 0.25])[0]
    province = rng.choice(PROVINCES)
    city = rng.choice(LETTERS)
    if kind == "green":
        marker = rng.choice("DF")
        if rng.random() < 0.5:
            label = province + city + marker + "".join(rng.choices(ALNUM, k=5))
        else:
            label = province + city + "".join(rng.choices(ALNUM, k=5)) + marker
    else:
        label = province + city + "".join(rng.choices(ALNUM, k=5))
    return label, kind


def render_plate(label: str, kind: str, font: ImageFont.FreeTypeFont) -> np.ndarray:
    # PIL expects RGB tuples.  Keep these values in RGB order; the rendered
    # image is converted to OpenCV BGR only when leaving this function.
    backgrounds = {"blue": (15, 70, 190), "yellow": (245, 210, 15), "green": (120, 215, 135)}
    foregrounds = {"blue": (255, 255, 255), "yellow": (15, 15, 15), "green": (10, 10, 10)}
    canvas = Image.new("RGB", (320, 96), backgrounds[kind])
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((3, 3, 316, 92), radius=7, outline=foregrounds[kind], width=3)
    count = len(label)
    left, right = 13, 307
    cell_width = (right - left) / count
    for index, character in enumerate(label):
        box = draw.textbbox((0, 0), character, font=font, stroke_width=0)
        width = box[2] - box[0]
        height = box[3] - box[1]
        center_x = left + (index + 0.5) * cell_width
        draw.text(
            (center_x - width / 2 - box[0], 48 - height / 2 - box[1]),
            character,
            font=font,
            fill=foregrounds[kind],
        )
    dot_x = int(left + 2 * cell_width - cell_width * 0.10)
    draw.ellipse((dot_x - 3, 45, dot_x + 3, 51), fill=foregrounds[kind])
    return cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR)


def augment(image: np.ndarray, rng: random.Random, np_rng: np.random.Generator) -> np.ndarray:
    height, width = image.shape[:2]
    jitter = 5.0
    source = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    target = source + np.asarray(
        [[rng.uniform(-jitter, jitter), rng.uniform(-jitter, jitter)] for _ in range(4)],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(source, target)
    result = cv2.warpPerspective(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )

    if rng.random() < 0.45:
        kernel_size = rng.choice([3, 5, 7])
        if rng.random() < 0.55:
            kernel = np.zeros((kernel_size, kernel_size), dtype=np.float32)
            kernel[kernel_size // 2, :] = 1.0 / kernel_size
            result = cv2.filter2D(result, -1, kernel)
        else:
            result = cv2.GaussianBlur(result, (kernel_size, kernel_size), 0)

    gain = rng.uniform(0.55, 1.35)
    bias = rng.uniform(-22.0, 22.0)
    result = np.clip(result.astype(np.float32) * gain + bias, 0, 255)
    cast = np.asarray(
        [rng.uniform(0.88, 1.12), rng.uniform(0.88, 1.12), rng.uniform(0.88, 1.12)],
        dtype=np.float32,
    )
    result = np.clip(result * cast, 0, 255)
    if rng.random() < 0.35:
        noise = np_rng.normal(0.0, rng.uniform(2.0, 10.0), result.shape)
        result = np.clip(result + noise, 0, 255)
    result = result.astype(np.uint8)

    if rng.random() < 0.30:
        overlay = result.copy()
        center = (rng.randint(0, width - 1), rng.randint(0, height - 1))
        axes = (rng.randint(25, 85), rng.randint(8, 28))
        cv2.ellipse(overlay, center, axes, rng.randint(0, 180), 0, 360, (255, 255, 255), -1)
        result = cv2.addWeighted(overlay, rng.uniform(0.08, 0.28), result, 1.0, 0)

    quality = rng.randint(45, 96)
    ok, encoded = cv2.imencode(".jpg", result, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG augmentation failed")
    decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if decoded is None:
        raise RuntimeError("JPEG augmentation decode failed")
    return decoded


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    data_root = (args.data_root or output.parent).resolve()
    try:
        output.relative_to(data_root)
    except ValueError as exc:
        raise ValueError("--output must be inside --data-root") from exc
    if output.exists() and any(output.iterdir()):
        if not args.overwrite:
            raise FileExistsError(
                f"output is not empty; use a new path or --overwrite: {output}"
            )
        existing = {
            path.name for path in (output / "images").glob("plate_*.jpg")
        }
        expected = {f"plate_{index:07d}.jpg" for index in range(args.count)}
        if existing != expected:
            raise FileExistsError(
                "safe overwrite only permits regenerating the exact same indexed set; "
                "use a new output directory when --count changes"
            )
    images_dir = output / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    font = choose_font(args.font)
    rng = random.Random(args.seed)
    np_rng = np.random.default_rng(args.seed)
    rows: list[dict[str, str | int]] = []
    for index in range(args.count):
        label, kind = make_label(rng)
        image = augment(render_plate(label, kind, font), rng, np_rng)
        image_path = images_dir / f"plate_{index:07d}.jpg"
        encoded, buffer = cv2.imencode(".jpg", image)
        if not encoded:
            raise RuntimeError(f"failed to write {image_path}")
        buffer.tofile(str(image_path))
        rows.append(
            {
                "image_path": image_path.relative_to(data_root).as_posix(),
                "label": label,
                "group_id": f"synthetic_{index:07d}",
                "source": "synthetic",
                "readable": 1,
            }
        )
    manifest_path = output / "manifest.tsv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    print(f"generated={len(rows)} manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
