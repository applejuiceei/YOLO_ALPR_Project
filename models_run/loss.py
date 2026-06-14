import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision.models import vgg16, VGG16_Weights


class CompositeLoss(nn.Module):
    def __init__(self, device, lambda_l1=1.0, lambda_p=0.1):
        super().__init__()
        self.l1_loss = nn.L1Loss()
        self.lambda_l1 = lambda_l1
        self.lambda_p = lambda_p

        # 加载官方 VGG16 并冻结所有梯度计算
        vgg = vgg16(weights=VGG16_Weights.DEFAULT).features.to(device)
        vgg.eval()
        for param in vgg.parameters():
            param.requires_grad = False

        # 截取关键的激活层作为特征对比锚点：relu1_2, relu2_2, relu3_3
        self.slice1 = vgg[:4]
        self.slice2 = vgg[4:9]
        self.slice3 = vgg[9:16]

        # 注册标准 ImageNet 归一化常量缓冲区
        self.register_buffer("mean", torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1).to(device))
        self.register_buffer("std", torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1).to(device))

    def forward(self, pred, target):
        # 基础像素级 L1 损失
        loss_l1 = self.l1_loss(pred, target)

        # 将张量转换至 VGG 预训练域计算感知特征
        pred_norm = (pred - self.mean) / self.std
        target_norm = (target - self.mean) / self.std

        p1 = self.slice1(pred_norm)
        t1 = self.slice1(target_norm)

        p2 = self.slice2(p1)
        t2 = self.slice2(t1)

        p3 = self.slice3(p2)
        t3 = self.slice3(t2)

        loss_p = F.l1_loss(p1, t1) + F.l1_loss(p2, t2) + F.l1_loss(p3, t3)

        return self.lambda_l1 * loss_l1 + self.lambda_p * loss_p