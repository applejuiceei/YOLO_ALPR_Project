import os
import time
import torch
from torch.utils.data import DataLoader
from dataset import LPBlurDataset
from model import TinyUNet
from loss import CompositeLoss


def train_engine():
    # 基础超参数设定
    DATA_ROOT = "./dataset"
    BATCH_SIZE = 16
    EPOCHS = 100
    LR = 5e-4
    DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    os.makedirs("./weights", exist_ok=True)

    print(f"====== 启动轻量级去模糊定制训练引擎 | 计算设备: {DEVICE} ======")

    # 实例化数据流
    train_ds = LPBlurDataset(DATA_ROOT, is_train=True)
    test_ds = LPBlurDataset(DATA_ROOT, is_train=False)

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=4, pin_memory=True)
    test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=4, pin_memory=True)

    # 构建模型与损失调度
    model = TinyUNet().to(DEVICE)
    criterion = CompositeLoss(DEVICE, lambda_l1=1.0, lambda_p=0.05)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS, eta_min=1e-6)

    scaler = torch.cuda.amp.GradScaler()
    best_loss = float('inf')

    for epoch in range(1, EPOCHS + 1):
        start_time = time.time()
        model.train()
        train_loss = 0.0

        # 训练迭代
        for blur, sharp in train_loader:
            blur, sharp = blur.to(DEVICE), sharp.to(DEVICE)
            optimizer.zero_grad()

            # 开启自动混合精度加速
            with torch.cuda.amp.autocast():
                pred = model(blur)
                loss = criterion(pred, sharp)

            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()

            train_loss += loss.item() * blur.size(0)

        scheduler.step()
        train_loss /= len(train_ds)

        # 验证评估环节
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for blur, sharp in test_loader:
                blur, sharp = blur.to(DEVICE), sharp.to(DEVICE)
                with torch.cuda.amp.autocast():
                    pred = model(blur)
                    loss = criterion(pred, sharp)
                val_loss += loss.item() * blur.size(0)
        val_loss /= len(test_ds)

        cost_time = time.time() - start_time
        print(
            f"Epoch [{epoch}/{EPOCHS}]耗时: {cost_time:.1f}s | Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f}")

        # 保存最佳权重
        if val_loss < best_loss:
            best_loss = val_loss
            save_path = os.path.join("./weights", "tiny_unet_best.pth")
            torch.save(model.state_dict(), save_path)
            print(f"✅ 发现更优验证损失，权重已落盘至: {save_path}")


if __name__ == "__main__":
    train_engine()