import os
from rknn.api import RKNN


ONNX_PATH = "best_obb_640.onnx"
RKNN_PATH = "plate_obb_640.rknn"
DATASET_PATH = "./dataset.txt"


def main():
    if not os.path.exists(ONNX_PATH):
        raise FileNotFoundError(
            f"{ONNX_PATH} not found. Export it first with: "
            "yolo export model=best_obb.pt format=onnx imgsz=640 opset=12 simplify=True"
        )
    if not os.path.exists(DATASET_PATH):
        raise FileNotFoundError(f"{DATASET_PATH} not found")

    rknn = RKNN(verbose=True)
    rknn.config(
        mean_values=[[0, 0, 0]],
        std_values=[[255, 255, 255]],
        target_platform="rk3588",
    )

    print(f"Loading ONNX: {ONNX_PATH}")
    ret = rknn.load_onnx(model=ONNX_PATH)
    if ret != 0:
        raise RuntimeError("load_onnx failed")

    print("Building RKNN with INT8 quantization...")
    ret = rknn.build(do_quantization=True, dataset=DATASET_PATH)
    if ret != 0:
        raise RuntimeError("rknn build failed")

    print(f"Exporting RKNN: {RKNN_PATH}")
    ret = rknn.export_rknn(RKNN_PATH)
    if ret != 0:
        raise RuntimeError("export_rknn failed")

    rknn.release()
    print(f"Done: {RKNN_PATH}")


if __name__ == "__main__":
    main()
