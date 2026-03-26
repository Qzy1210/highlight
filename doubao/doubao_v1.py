import cv2
import os
import subprocess
import time
from ultralytics import YOLO

# ===================== 核心配置（新手只需改这里） =====================
VIDEO_PATH = "/Users/quzhengyang/www/360.cn/Python/highLight/IMG_1556.MOV"  # 待剪辑的篮球视频路径
OUTPUT_DIR = "goal_clips"  # 进球片段保存目录
GOAL_BEFORE_SEC = 4.5  # 进球前保留的秒数
GOAL_AFTER_SEC = 2.0  # 进球后保留的秒数
CONF_THRESHOLD = 0.3  # YOLO 检测置信度阈值


# ====================================================================

def init_yolo_model():
    """初始化 YOLOv8 模型（自动下载轻量版权重）"""
    model = YOLO("yolov8n.pt")  # yolov8n 轻量版，速度快，支持检测 sports ball/basketball hoop
    return model


def get_video_info(video_path):
    """获取视频基本信息：帧率、总帧数、宽高"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"无法打开视频文件：{video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)  # 视频帧率
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))  # 总帧数
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  # 视频宽度
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))  # 视频高度

    cap.release()
    return fps, total_frames, width, height


def detect_goal_frames(model, video_path, fps):
    """检测视频中进球的关键帧（篮球出现在篮筐区域）"""
    cap = cv2.VideoCapture(video_path)
    goal_frames = []  # 存储进球的关键帧编号
    frame_idx = 0
    start_time = time.time()

    # 获取视频总帧数
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # 篮筐区域判定：取视频右侧上半部分（根据实际视频可调整）
    hoop_area_x1 = int(0.6 * cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    hoop_area_x2 = int(0.9 * cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    hoop_area_y1 = int(0.1 * cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    hoop_area_y2 = int(0.5 * cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # 创建截图保存目录
    screenshot_dir = "goal_screenshots"
    os.makedirs(screenshot_dir, exist_ok=True)

    print("正在检测进球画面...")
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        # 显示进度
        progress = (frame_idx / total_frames) * 100
        if frame_idx % 50 == 0:
            print(f"检测进度：{progress:.1f}%（第 {frame_idx} 帧）")

        # 每5帧检测一次（提速，避免逐帧检测卡顿）
        if frame_idx % 5 == 0:
            # YOLO 检测：只关注 32（sports ball）和 72（basketball hoop）类
            results = model(frame, conf=CONF_THRESHOLD, classes=[32, 72])

            # 解析检测结果
            ball_boxes = []  # 篮球的检测框 [x1,y1,x2,y2]
            hoop_boxes = []  # 篮筐的检测框 [x1,y1,x2,y2]
            for r in results:
                for box in r.boxes:
                    cls = int(box.cls[0])
                    if cls == 32:  # sports ball
                        ball_boxes.append(box.xyxy[0].cpu().numpy())
                    elif cls == 72:  # basketball hoop
                        hoop_boxes.append(box.xyxy[0].cpu().numpy())

            # 判断进球：篮球出现在篮筐区域 或 同时检测到篮球+篮筐且重叠
            if ball_boxes and (hoop_boxes or any(
                    (hoop_area_x1 < b[0] < hoop_area_x2) and (hoop_area_y1 < b[1] < hoop_area_y2)
                    for b in ball_boxes
            )):
                goal_frames.append(frame_idx)
                print(f"检测到进球：第 {frame_idx} 帧（{frame_idx / fps:.2f} 秒）")
                
                # 在原帧上绘制篮框区域红色框
                frame_with_hoop = frame.copy()
                cv2.rectangle(frame_with_hoop, (hoop_area_x1, hoop_area_y1), (hoop_area_x2, hoop_area_y2), (0, 0, 255), 2)
                
                # 保存带有红色框的完整帧截图
                full_frame_path = os.path.join(screenshot_dir, f"goal_full_{frame_idx}.jpg")
                cv2.imwrite(full_frame_path, frame_with_hoop)
                
                # 保存篮框区域截图
                hoop_region = frame[hoop_area_y1:hoop_area_y2, hoop_area_x1:hoop_area_x2]
                screenshot_path = os.path.join(screenshot_dir, f"goal_hoop_{frame_idx}.jpg")
                cv2.imwrite(screenshot_path, hoop_region)
                print(f"已保存篮框区域截图：{screenshot_path}")
                print(f"已保存带红色框的完整帧：{full_frame_path}")

        frame_idx += 1

    cap.release()
    # 计算耗时
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"检测完成，耗时：{elapsed_time:.2f} 秒")
    
    # 去重：相邻帧只保留一个（避免同一进球被多次检测）
    goal_frames = sorted(list(set(goal_frames)))
    return goal_frames


def clip_goal_segments(video_path, goal_frames, fps):
    """根据进球关键帧，用 FFmpeg 剪辑进球片段"""
    # 创建输出目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 计算每段剪辑的起始/结束秒数
    for i, frame in enumerate(goal_frames):
        # 关键帧对应的秒数
        goal_sec = frame / fps
        # 剪辑起始秒数（不能小于0）
        start_sec = max(0, goal_sec - GOAL_BEFORE_SEC)
        # 剪辑结束秒数
        end_sec = goal_sec + GOAL_AFTER_SEC

        # 输出文件路径
        output_path = os.path.join(OUTPUT_DIR, f"goal_{i + 1}.mp4")

        # FFmpeg 剪辑命令（精确剪辑，保留原画质）
        ffmpeg_cmd = [
            "ffmpeg", "-y",  # -y 覆盖已存在的文件
            "-ss", str(start_sec),  # 起始时间
            "-to", str(end_sec),  # 结束时间
            "-i", video_path,  # 输入视频
            "-c:v", "copy",  # 视频流直接复制（不重新编码，速度快）
            "-c:a", "copy",  # 音频流直接复制
            output_path
        ]

        # 执行 FFmpeg 命令
        try:
            subprocess.run(ffmpeg_cmd, check=True, capture_output=True)
            print(f"✅ 剪辑完成：{output_path}")
        except subprocess.CalledProcessError as e:
            print(f"❌ 剪辑失败：{output_path}，错误：{e}")


# ===================== 主程序 =====================
if __name__ == "__main__":
    # 1. 初始化模型
    model = init_yolo_model()

    # 2. 获取视频信息
    fps, total_frames, width, height = get_video_info(VIDEO_PATH)
    print(f"视频信息：帧率={fps}, 总帧数={total_frames}, 分辨率={width}x{height}")

    # 3. 检测进球关键帧
    goal_frames = detect_goal_frames(model, VIDEO_PATH, fps)
    if not goal_frames:
        print("❌ 未检测到任何进球画面")
        exit()
    print(f"✅ 共检测到 {len(goal_frames)} 个进球关键帧")

    # 4. 剪辑进球片段
    clip_goal_segments(VIDEO_PATH, goal_frames, fps)
    print(f"\n🎉 所有进球片段已保存至：{os.path.abspath(OUTPUT_DIR)}")