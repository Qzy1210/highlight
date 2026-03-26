# 导入所需库
from ultralytics import YOLO
import cv2
import os


def detect_image(model_path, img_path, save_path="detected_image.jpg"):
    """
    YOLOv8 图片目标检测函数
    :param model_path: YOLOv8 模型路径（如 "yolov8n.pt"，自动下载）
    :param img_path: 待检测图片路径
    :param save_path: 检测结果保存路径
    """
    # 1. 检查图片文件是否存在
    if not os.path.exists(img_path):
        print(f"❌ 错误：图片文件不存在 → {img_path}")
        return

    # 2. 加载 YOLOv8 预训练模型（n=轻量版，s/m/l/x 精度依次提升）
    # 首次运行会自动下载权重文件（约6MB），后续直接加载本地缓存
    model = YOLO(model_path)

    # 3. 读取图片（OpenCV 格式）
    img = cv2.imread(img_path)
    if img is None:
        print(f"❌ 错误：无法读取图片 → {img_path}")
        return

    # 4. 执行目标检测（conf=0.25 表示置信度阈值，过滤低置信度结果）
    results = model(img, conf=0.25)

    # 5. 可视化检测结果（在图片上绘制框、类别、置信度）
    annotated_img = results[0].plot()

    # 6. 保存并显示结果
    cv2.imwrite(save_path, annotated_img)
    print(f"✅ 检测完成！结果已保存至 → {save_path}")

    # 显示结果（Mac 上如果弹窗不显示，可注释这部分，直接看保存的图片）
    cv2.imshow("YOLOv8 Image Detection", annotated_img)
    cv2.waitKey(0)  # 按任意键关闭窗口
    cv2.destroyAllWindows()


def detect_video(model_path, video_source=0, save_path="detected_video.mp4"):
    """
    YOLOv8 视频/摄像头目标检测函数
    :param model_path: YOLOv8 模型路径
    :param video_source: 视频源（0=电脑摄像头，也可填视频文件路径如 "test.mp4"）
    :param save_path: 检测结果视频保存路径
    """
    # 1. 加载模型
    model = YOLO(model_path)

    # 2. 打开视频源
    cap = cv2.VideoCapture(video_source)
    if not cap.isOpened():
        print(f"❌ 错误：无法打开视频源 → {video_source}")
        return

    # 3. 获取视频参数（用于保存结果）
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(save_path, fourcc, fps, (width, height))

    print("📹 开始检测（按 'q' 键退出）...")
    # 4. 逐帧检测
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        # 执行检测
        results = model(frame, conf=0.25)
        annotated_frame = results[0].plot()

        # 保存帧并显示
        out.write(annotated_frame)
        cv2.imshow("YOLOv8 Video Detection", annotated_frame)

        # 按 q 键退出
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    # 5. 释放资源
    cap.release()
    out.release()
    cv2.destroyAllWindows()
    print(f"✅ 视频检测完成！结果已保存至 → {save_path}")


# ---------------------- 主程序入口 ----------------------
if __name__ == "__main__":
    # 选择 YOLOv8 模型（推荐新手用 yolov8n.pt，轻量且快）
    YOLO_MODEL = "yolov8n.pt"  # 可选：yolov8s.pt/yolov8m.pt（精度更高，速度稍慢）

    # ========== 场景1：检测单张图片 ==========
    # 替换成你自己的图片路径（比如 "/Users/你的用户名/Desktop/test.jpg"）
    # IMG_PATH = "test.jpg"
    # detect_image(YOLO_MODEL, IMG_PATH)

    # ========== 场景2：检测摄像头/视频（注释掉上面的，打开下面的即可） ==========
    # VIDEO_SOURCE = 0  # 0=电脑摄像头
    VIDEO_SOURCE = "/Users/quzhengyang/www/360.cn/Python/highLight/IMG_1556.MOV"  # 替换成视频文件路径
    detect_video(YOLO_MODEL, VIDEO_SOURCE)