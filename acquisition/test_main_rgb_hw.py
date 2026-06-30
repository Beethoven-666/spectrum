import sys
from pathlib import Path
from PIL import Image

# 确保能导入 spectrum_acq 包
sys.path.insert(0, str(Path(__file__).parent))

from spectrum_acq.devices.main_rgb import V4l2MainRgbCamera, discover_main_rgb_device
from spectrum_acq.models import MainRgbProfile, DeviceStatus

def run_test():
    print("=== 1. 扫描系统中的 V4L2 摄像头设备 ===")
    device_path = discover_main_rgb_device()
    if device_path:
        print(f"发现可用摄像头设备: {device_path}")
    else:
        print("未在 /dev/v4l/by-id 下发现主 RGB 摄像头设备。")
        print("您也可以手动指定设备路径进行测试，例如 /dev/video0")
        device_path = input("请输入摄像头设备路径 (默认直接尝试 /dev/video0): ").strip() or "/dev/video0"

    # 初始化配置
    # 单次抓图模式更容易排查物理连接问题
    #profile = MainRgbProfile(device_path=device_path, mode="single_shot", width=640, height=480)
    profile = MainRgbProfile(device_path=device_path, mode="persistent", width=640, height=480)

    print("\n=== 2. 初始化 V4l2MainRgbCamera 驱动 ===")
    camera = V4l2MainRgbCamera(profile)
    
    print(f"当前驱动状态 (status): {camera.status()}")
    
    print("\n=== 3. 尝试单帧捕获 (Single Shot Capture) ===")
    try:
        camera.open()
        capture = camera.read()
        print(f"捕获结果状态: {capture.status}")
        print(f"捕获元数据: {capture.metadata}")
        
        if capture.status == DeviceStatus.READY and capture.image_rgb is not None:
            print("图像获取成功！")
            img = Image.fromarray(capture.image_rgb)
            output_path = Path("test_main_rgb_output.jpg")
            img.save(output_path)
            print(f"已成功将测试帧图片保存至: {output_path.resolve()}")
        else:
            print("未能成功获取有效图像。")
    except Exception as e:
        print(f"捕获图像过程中发生异常: {e}")
    finally:
        camera.close()

if __name__ == "__main__":
    run_test()
