import os
from PIL import Image
import torch
from torch.utils.data import Dataset
from torchvision import transforms


class LPBlurDataset(Dataset):
    def __init__(self, root_dir, is_train=True):
        split = "train" if is_train else "test"
        self.blur_dir = os.path.join(root_dir, split, "blur")
        self.sharp_dir = os.path.join(root_dir, split, "sharp")

        # 过滤获取合法的图像文件名列表
        self.filenames = sorted([f for f in os.listdir(self.blur_dir) if f.endswith(('.jpg', '.png'))])
        self.is_train = is_train
        self.to_tensor = transforms.ToTensor()

    def __len__(self):
        return len(self.filenames)

    def __getitem__(self, idx):
        img_name = self.filenames[idx]
        blur_path = os.path.join(self.blur_dir, img_name)
        sharp_path = os.path.join(self.sharp_dir, img_name)

        blur_img = Image.open(blur_path).convert("RGB")
        sharp_img = Image.open(sharp_path).convert("RGB")

        # 强制缩放至标准宽 224 x 高 112 像素
        blur_img = blur_img.resize((224, 112), Image.BILINEAR)
        sharp_img = sharp_img.resize((224, 112), Image.BILINEAR)

        # 转换为张量，数值范围自动归一化至 [0.0, 1.0]
        blur_tensor = self.to_tensor(blur_img)
        sharp_tensor = self.to_tensor(sharp_img)

        # 训练期数据增强：50% 概率进行水平镜像翻转
        if self.is_train and torch.rand(1).item() > 0.5:
            blur_tensor = torch.flip(blur_tensor, dims=[2])
            sharp_tensor = torch.flip(sharp_tensor, dims=[2])

        return blur_tensor, sharp_tensor


if __name__ == "__main__":
    # 简单测试代码加载是否正常
    ds = LPBlurDataset("./dataset", is_train=True)
    print(f"训练集总样本数: {len(ds)}")
    b, s = ds[0]
    print(f"输出张量 Shape: {b.shape}")