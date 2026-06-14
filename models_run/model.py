import torch
import torch.nn as nn


class ConvBlock(nn.Module):
    """基础双卷积单元：Conv -> BatchNorm -> ReLU 结构对端侧 INT8 量化极为友好"""

    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_ch, out_ch, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True)
        )

    def forward(self, x):
        return self.block(x)


class TinyUNet(nn.Module):
    def __init__(self, in_channels=3, out_channels=3):
        super().__init__()
        # 极简编码器通道设计：32 -> 64 -> 128，降低内存访存开销
        self.enc1 = ConvBlock(in_channels, 32)
        self.pool1 = nn.MaxPool2d(kernel_size=2, stride=2)

        self.enc2 = ConvBlock(32, 64)
        self.pool2 = nn.MaxPool2d(kernel_size=2, stride=2)

        self.enc3 = ConvBlock(64, 128)

        # 极简解码器：使用 ConvTranspose2d 保证空间无缝上采样
        self.up2 = nn.ConvTranspose2d(128, 64, kernel_size=2, stride=2)
        self.dec2 = ConvBlock(128, 64)

        self.up1 = nn.ConvTranspose2d(64, 32, kernel_size=2, stride=2)
        self.dec1 = ConvBlock(64, 32)

        # 尾部回归输出像素矩阵
        self.final_conv = nn.Conv2d(32, out_channels, kernel_size=1)

    def forward(self, x):
        # 编码路径
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool1(e1))
        e3 = self.enc3(self.pool2(e2))

        # 解码与长距离特征拼接路径
        d2 = self.dec2(torch.cat([self.up2(e3), e2], dim=1))
        d1 = self.dec1(torch.cat([self.up1(d2), e1], dim=1))

        out = self.final_conv(d1)
        # 通过 Sigmoid 将最终预测限制在合法的图像色彩空间内
        return torch.sigmoid(out)


if __name__ == "__main__":
    net = TinyUNet()
    dummy_input = torch.randn(1, 3, 112, 224)
    out = net(dummy_input)
    print("模型前向测试通过，输出尺寸:", out.shape)