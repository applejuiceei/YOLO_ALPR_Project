"""Train and export a lightweight paired license-plate deblurring model in Colab."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import Tensor, nn
from torch.nn import functional as F
from torch.utils.data import DataLoader, Dataset


CANONICAL_HEIGHT = 96
CANONICAL_WIDTH = 320


class PairedPlateDataset(Dataset[tuple[Tensor, Tensor]]):
    """Loads the manifest produced by prepare_deblur_dataset.py."""

    def __init__(self, root: Path, split: str, augment_lq: bool = False) -> None:
        self.root = root
        self.augment_lq = augment_lq
        manifest_path = root / f"manifest_{split}.jsonl"
        self.records = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not self.records:
            raise ValueError(f"No records found in {manifest_path}")

    def __len__(self) -> int:
        return len(self.records)

    @staticmethod
    def _load_image(path: Path) -> np.ndarray:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"Could not read image: {path}")
        if image.shape[:2] != (CANONICAL_HEIGHT, CANONICAL_WIDTH):
            raise ValueError(f"Unexpected image size {image.shape[:2]}: {path}")
        return image.astype(np.float32) / 255.0

    @staticmethod
    def _augment_lq(image: np.ndarray) -> np.ndarray:
        """Small LQ-only perturbations improve compression/noise tolerance without changing the target."""
        if random.random() < 0.30:
            gain = random.uniform(0.90, 1.10)
            bias = random.uniform(-0.03, 0.03)
            image = np.clip(image * gain + bias, 0.0, 1.0)
        if random.random() < 0.25:
            sigma = random.uniform(0.003, 0.012)
            image = np.clip(image + np.random.normal(0.0, sigma, image.shape).astype(np.float32), 0.0, 1.0)
        if random.random() < 0.20:
            quality = random.randint(45, 85)
            encoded_ok, encoded = cv2.imencode(".jpg", (image * 255.0).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, quality])
            if encoded_ok:
                decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
                if decoded is not None:
                    image = decoded.astype(np.float32) / 255.0
        return image

    def __getitem__(self, index: int) -> tuple[Tensor, Tensor]:
        record = self.records[index]
        blur = self._load_image(self.root / record["blur"])
        sharp = self._load_image(self.root / record["sharp"])
        if self.augment_lq:
            blur = self._augment_lq(blur)
        return torch.from_numpy(blur.transpose(2, 0, 1)), torch.from_numpy(sharp.transpose(2, 0, 1))


class DepthwiseResidualBlock(nn.Module):
    """Quantization-friendly residual block using only Conv, BN, and ReLU."""

    def __init__(self, channels: int, expansion: int = 2) -> None:
        super().__init__()
        hidden = channels * expansion
        self.layers = nn.Sequential(
            nn.Conv2d(channels, channels, 3, padding=1, groups=channels, bias=False),
            nn.BatchNorm2d(channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(channels, hidden, 1, bias=False),
            nn.BatchNorm2d(hidden),
            nn.ReLU(inplace=True),
            nn.Conv2d(hidden, channels, 1, bias=False),
            nn.BatchNorm2d(channels),
        )
        self.activation = nn.ReLU(inplace=True)

    def forward(self, x: Tensor) -> Tensor:
        return self.activation(x + self.layers(x))


class Downsample(nn.Module):
    def __init__(self, in_channels: int, out_channels: int) -> None:
        super().__init__()
        self.layers = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: Tensor) -> Tensor:
        return self.layers(x)


class UpsampleFuse(nn.Module):
    def __init__(self, in_channels: int, skip_channels: int, out_channels: int, blocks: int) -> None:
        super().__init__()
        self.project = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
        )
        self.fuse = nn.Sequential(
            nn.Conv2d(out_channels + skip_channels, out_channels, 1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            *[DepthwiseResidualBlock(out_channels) for _ in range(blocks)],
        )

    def forward(self, x: Tensor, skip: Tensor) -> Tensor:
        x = F.interpolate(x, size=skip.shape[-2:], mode="nearest")
        x = self.project(x)
        return self.fuse(torch.cat([x, skip], dim=1))


class PlateRestoreNetLite(nn.Module):
    """Small residual U-Net for 320x96 plate restoration; input and output are BGR tensors."""

    def __init__(self, base_channels: int = 32) -> None:
        super().__init__()
        c1, c2, c3 = base_channels, base_channels + 16, base_channels + 32
        self.stem = nn.Sequential(
            nn.Conv2d(3, c1, 3, padding=1, bias=False),
            nn.BatchNorm2d(c1),
            nn.ReLU(inplace=True),
        )
        self.encoder1 = nn.Sequential(DepthwiseResidualBlock(c1), DepthwiseResidualBlock(c1))
        self.down1 = Downsample(c1, c2)
        self.encoder2 = nn.Sequential(DepthwiseResidualBlock(c2), DepthwiseResidualBlock(c2))
        self.down2 = Downsample(c2, c3)
        self.bottleneck = nn.Sequential(DepthwiseResidualBlock(c3), DepthwiseResidualBlock(c3), DepthwiseResidualBlock(c3))
        self.up2 = UpsampleFuse(c3, c2, c2, blocks=2)
        self.up1 = UpsampleFuse(c2, c1, c1, blocks=2)
        self.head = nn.Conv2d(c1, 3, 3, padding=1)
        nn.init.zeros_(self.head.weight)
        nn.init.zeros_(self.head.bias)

    def forward(self, x: Tensor) -> Tensor:
        skip1 = self.encoder1(self.stem(x))
        skip2 = self.encoder2(self.down1(skip1))
        features = self.bottleneck(self.down2(skip2))
        features = self.up2(features, skip2)
        features = self.up1(features, skip1)
        return torch.clamp(x + self.head(features), 0.0, 1.0)


def charbonnier_loss(prediction: Tensor, target: Tensor, epsilon: float = 1e-3) -> Tensor:
    return torch.sqrt((prediction - target).square() + epsilon * epsilon).mean()


def gradient_loss(prediction: Tensor, target: Tensor) -> Tensor:
    pred_dx = prediction[:, :, :, 1:] - prediction[:, :, :, :-1]
    pred_dy = prediction[:, :, 1:, :] - prediction[:, :, :-1, :]
    target_dx = target[:, :, :, 1:] - target[:, :, :, :-1]
    target_dy = target[:, :, 1:, :] - target[:, :, :-1, :]
    return F.l1_loss(pred_dx, target_dx) + F.l1_loss(pred_dy, target_dy)


def ssim_value(prediction: Tensor, target: Tensor) -> Tensor:
    """A compact differentiable SSIM implementation for the loss and validation metric."""
    mu_x = F.avg_pool2d(prediction, 7, stride=1, padding=3)
    mu_y = F.avg_pool2d(target, 7, stride=1, padding=3)
    sigma_x = F.avg_pool2d(prediction * prediction, 7, stride=1, padding=3) - mu_x.square()
    sigma_y = F.avg_pool2d(target * target, 7, stride=1, padding=3) - mu_y.square()
    sigma_xy = F.avg_pool2d(prediction * target, 7, stride=1, padding=3) - mu_x * mu_y
    c1, c2 = 0.01**2, 0.03**2
    value = ((2 * mu_x * mu_y + c1) * (2 * sigma_xy + c2)) / ((mu_x.square() + mu_y.square() + c1) * (sigma_x + sigma_y + c2))
    return value.clamp(0.0, 1.0).mean()


def restoration_loss(prediction: Tensor, target: Tensor) -> Tensor:
    return 0.75 * charbonnier_loss(prediction, target) + 0.15 * gradient_loss(prediction, target) + 0.10 * (1.0 - ssim_value(prediction, target))


def psnr(prediction: Tensor, target: Tensor) -> Tensor:
    mse = F.mse_loss(prediction, target).clamp_min(1e-10)
    return -10.0 * torch.log10(mse)


def run_epoch(
    model: nn.Module,
    loader: DataLoader[tuple[Tensor, Tensor]],
    optimizer: torch.optim.Optimizer | None,
    scaler: torch.amp.GradScaler,
    device: torch.device,
) -> dict[str, float]:
    training = optimizer is not None
    model.train(training)
    totals = {"loss": 0.0, "psnr": 0.0, "ssim": 0.0, "items": 0}
    autocast_enabled = device.type == "cuda"

    for blur, sharp in loader:
        blur, sharp = blur.to(device, non_blocking=True), sharp.to(device, non_blocking=True)
        if training:
            optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=autocast_enabled):
            restored = model(blur)
            loss = restoration_loss(restored, sharp)
        if training:
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            scaler.step(optimizer)
            scaler.update()

        count = blur.shape[0]
        totals["loss"] += float(loss.detach()) * count
        totals["psnr"] += float(psnr(restored.detach(), sharp)) * count
        totals["ssim"] += float(ssim_value(restored.detach(), sharp)) * count
        totals["items"] += count

    return {key: value / totals["items"] for key, value in totals.items() if key != "items"}


@torch.no_grad()
def identity_metrics(loader: DataLoader[tuple[Tensor, Tensor]], device: torch.device) -> dict[str, float]:
    """Report the blurred-input baseline so restoration gains are measurable."""
    totals = {"loss": 0.0, "psnr": 0.0, "ssim": 0.0, "items": 0}
    for blur, sharp in loader:
        blur, sharp = blur.to(device, non_blocking=True), sharp.to(device, non_blocking=True)
        count = blur.shape[0]
        totals["loss"] += float(restoration_loss(blur, sharp)) * count
        totals["psnr"] += float(psnr(blur, sharp)) * count
        totals["ssim"] += float(ssim_value(blur, sharp)) * count
        totals["items"] += count
    return {key: value / totals["items"] for key, value in totals.items() if key != "items"}


@torch.no_grad()
def save_preview(model: nn.Module, loader: DataLoader[tuple[Tensor, Tensor]], device: torch.device, path: Path) -> None:
    model.eval()
    blur, sharp = next(iter(loader))
    restored = model(blur.to(device)).cpu()
    rows = []
    for index in range(min(4, blur.shape[0])):
        images = [blur[index], restored[index], sharp[index]]
        tiles = [(image.permute(1, 2, 0).numpy().clip(0, 1) * 255).astype(np.uint8) for image in images]
        row = cv2.hconcat(tiles)
        cv2.putText(row, "blur", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(row, "restored", (CANONICAL_WIDTH + 6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(row, "sharp", (CANONICAL_WIDTH * 2 + 6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
        rows.append(row)
    cv2.imwrite(str(path), cv2.vconcat(rows))


def save_checkpoint(
    path: Path,
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    scheduler: torch.optim.lr_scheduler.LRScheduler,
    scaler: torch.amp.GradScaler,
    epoch: int,
    metrics: dict[str, float],
    best_val_loss: float,
    args: argparse.Namespace,
) -> None:
    serializable_args = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    torch.save(
        {
            "epoch": epoch,
            "metrics": metrics,
            "best_val_loss": best_val_loss,
            "model_state": model.state_dict(),
            "optimizer_state": optimizer.state_dict(),
            "scheduler_state": scheduler.state_dict(),
            "scaler_state": scaler.state_dict(),
            "model_config": {"base_channels": args.base_channels},
            "input_size": [1, 3, CANONICAL_HEIGHT, CANONICAL_WIDTH],
            "args": serializable_args,
        },
        path,
    )


def export_onnx(checkpoint_path: Path, output_path: Path, device: torch.device) -> None:
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    model = PlateRestoreNetLite(**checkpoint["model_config"]).to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    dummy = torch.zeros((1, 3, CANONICAL_HEIGHT, CANONICAL_WIDTH), device=device)
    torch.onnx.export(
        model,
        dummy,
        output_path,
        input_names=["image_bgr"],
        output_names=["restored_bgr"],
        opset_version=12,
        do_constant_folding=True,
        dynamic_axes=None,
        dynamo=False,
        external_data=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Train PlateRestoreNet-Lite on a prepared paired dataset.")
    parser.add_argument("--data", type=Path, default=Path("/content/plate_deblur_dataset_v1"))
    parser.add_argument("--output", type=Path, default=Path("/content/runs/deblur/plate_restore_lite"))
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--base-channels", type=int, default=32)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resume", type=Path, help="Path to last.pt from an interrupted run.")
    parser.add_argument("--no-augment", action="store_true", help="Disable small LQ-only augmentation for an exact paired baseline.")
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
        torch.backends.cudnn.benchmark = True

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "samples").mkdir(exist_ok=True)
    (args.output / "training_config.json").write_text(json.dumps(vars(args), default=str, indent=2), encoding="utf-8")

    train_set = PairedPlateDataset(args.data, "train", augment_lq=not args.no_augment)
    val_set = PairedPlateDataset(args.data, "val")
    test_set = PairedPlateDataset(args.data, "test")
    loader_args = {"num_workers": args.workers, "pin_memory": device.type == "cuda"}
    if args.workers > 0:
        loader_args["persistent_workers"] = True
    train_loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=True, drop_last=False, **loader_args)
    val_loader = DataLoader(val_set, batch_size=args.batch_size, shuffle=False, **loader_args)
    test_loader = DataLoader(test_set, batch_size=args.batch_size, shuffle=False, **loader_args)

    model = PlateRestoreNetLite(args.base_channels).to(device)
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs, eta_min=args.lr * 0.05)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    best_val_loss = math.inf
    start_epoch = 1
    if args.resume is not None:
        checkpoint = torch.load(args.resume, map_location=device, weights_only=False)
        model.load_state_dict(checkpoint["model_state"])
        optimizer.load_state_dict(checkpoint["optimizer_state"])
        scheduler.load_state_dict(checkpoint["scheduler_state"])
        scaler.load_state_dict(checkpoint["scaler_state"])
        best_val_loss = float(checkpoint["best_val_loss"])
        start_epoch = int(checkpoint["epoch"]) + 1
        print(f"Resuming from {args.resume} at epoch {start_epoch}", flush=True)
    metrics_path = args.output / "metrics.csv"

    print(f"device={device} parameters={parameter_count:,} train={len(train_set)} val={len(val_set)} test={len(test_set)}", flush=True)
    with metrics_path.open("w", newline="", encoding="utf-8") as metrics_file:
        writer = csv.DictWriter(metrics_file, fieldnames=["epoch", "lr", "train_loss", "train_psnr", "train_ssim", "val_loss", "val_psnr", "val_ssim"])
        writer.writeheader()
        for epoch in range(start_epoch, args.epochs + 1):
            train_metrics = run_epoch(model, train_loader, optimizer, scaler, device)
            val_metrics = run_epoch(model, val_loader, None, scaler, device)
            row = {
                "epoch": epoch,
                "lr": optimizer.param_groups[0]["lr"],
                **{f"train_{key}": value for key, value in train_metrics.items()},
                **{f"val_{key}": value for key, value in val_metrics.items()},
            }
            writer.writerow(row)
            metrics_file.flush()
            print(" ".join(f"{key}={value:.5f}" if isinstance(value, float) else f"{key}={value}" for key, value in row.items()), flush=True)
            if val_metrics["loss"] < best_val_loss:
                best_val_loss = val_metrics["loss"]
                save_checkpoint(args.output / "best.pt", model, optimizer, scheduler, scaler, epoch, val_metrics, best_val_loss, args)
            save_checkpoint(args.output / "last.pt", model, optimizer, scheduler, scaler, epoch, val_metrics, best_val_loss, args)
            if epoch == 1 or epoch % 5 == 0 or epoch == args.epochs:
                save_preview(model, val_loader, device, args.output / "samples" / f"epoch_{epoch:03d}.jpg")
            scheduler.step()

    best_checkpoint = args.output / "best.pt"
    checkpoint = torch.load(best_checkpoint, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model_state"])
    test_metrics = run_epoch(model, test_loader, None, scaler, device)
    baseline_metrics = identity_metrics(test_loader, device)
    (args.output / "test_metrics.json").write_text(
        json.dumps({"identity_blur_baseline": baseline_metrics, "restored": test_metrics}, indent=2),
        encoding="utf-8",
    )
    export_onnx(best_checkpoint, args.output / "plate_restore_lite_320x96.onnx", device)
    print(f"best_val_loss={best_val_loss:.6f} baseline={baseline_metrics} restored={test_metrics}", flush=True)
    print(f"Artifacts: {args.output}", flush=True)


if __name__ == "__main__":
    main()
