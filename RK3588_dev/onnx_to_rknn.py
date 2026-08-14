import os
from rknn.api import RKNN

def convert_model(onnx_path, rknn_path, dataset_path, is_ocr=False):
    print(f"\n🚀 开始处理模型: {onnx_path}")
    rknn = RKNN(verbose=False)
    
    # 【核心魔法】：配置 NPU 硬件级预处理参数
    # target_platform: 必须指定为 rk3588
    # mean_values 和 std_values 会固化进芯片硬件电路中。
    # 当设置为 mean=0, std=255 时，硬件会自动把 [0, 255] 的像素值除以 255，完美对接 YOLO 的归一化，C++ 代码里可以直接塞原始画面！
    rknn.config(
        mean_values=[[0, 0, 0]],
        std_values=[[255, 255, 255]],
        target_platform='rk3588'
    )
    
    # 1. 加载 ONNX
    if is_ocr:
        # 【OCR 专属魔法】：强行锁死输入尺寸，解决动态维度 (Dynamic Shape) 导致的量化失败
        print("--> 检测到 OCR 模型，已激活静态尺寸锁定 [1, 3, 48, 320]...")
        ret = rknn.load_onnx(model=onnx_path, inputs=['x'], input_size_list=[[1, 3, 48, 320]])
    else:
        # YOLO 模型本身就是固定尺寸，正常加载即可
        ret = rknn.load_onnx(model=onnx_path)
        
    if ret != 0:
        print(f'❌ 加载 {onnx_path} 失败！')
        return
        
    # 2. 构建模型并注入量化校准集
    print('--> 正在进行异构层融合与 INT8 密集量化（预计需要 3-5 分钟，请耐心等待）...')
    ret = rknn.build(do_quantization=True, dataset=dataset_path)
    if ret != 0:
        print('❌ 模型量化构建失败！')
        return
        
    # 3. 导出 RKNN 模型
    ret = rknn.export_rknn(rknn_path)
    if ret != 0:
        print('❌ 导出 RKNN 模型失败！')
        return
        
    print(f'🎉 成功导出硬件加速模型: {rknn_path}')
    rknn.release()

if __name__ == '__main__':
    # 检查校准集是否存在
    dataset = './dataset.txt'
    if not os.path.exists(dataset):
        print(f"⚠️ 找不到校准文件 {dataset}，请确认第一步已完成！")
    else:
        # 1. 转换车辆检测模型 (YOLOv11)
        convert_model('yolo11n.onnx', 'vehicle.rknn', dataset)
        
        # 2. 转换车牌旋转框检测模型 (YOLO-OBB)
        convert_model('best_obb.onnx', 'plate_obb.rknn', dataset)
        
        # 3. 转换车牌字符识别模型 (PaddleOCR) -> 激活 is_ocr 标志
        convert_model('plate_rec_sim.onnx', 'plate_rec.rknn', dataset, is_ocr=True)
        
        print("\n🏆 三大核心模型已全部完成 INT8 量化！现在可以把 .rknn 文件和 dict.txt 拷给开发板跑 C++ 推理了！")