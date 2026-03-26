import cv2
import os
import subprocess
import numpy as np
import time
from ultralytics import YOLO
from tqdm import tqdm  # 用于进度条显示

# ===================== 核心配置（新手只需改这里） =====================
VIDEO_PATH = "/Users/quzhengyang/www/360.cn/Python/highLight/IMG_1556.MOV"  # 待剪辑的篮球视频路径
OUTPUT_DIR = "goal_clips_v2"  # 进球片段保存目录
SCREENSHOT_PATH = "hoop_detection_v2.png"  # 篮筐位置截图保存路径
GOAL_BEFORE_SEC = 3.5  # 进球前保留的秒数
GOAL_AFTER_SEC = 2.0  # 进球后保留的秒数
CONF_THRESHOLD = 0.3  # YOLO 检测置信度阈值
HOOP_CONF_THRESHOLD = 0.1  # YOLO 检测置信度阈值
SCAN_SECONDS = 8  # 扫描前N秒画面定位篮筐（建议3-5秒）
HOOP_AREA_SCALE = 1.5  # 篮筐区域扩大倍数（1.5倍足够覆盖进球范围）


# ====================================================================

def init_yolo_model():
    """初始化 YOLOv8 模型（自动下载轻量版权重）"""
    #model = YOLO("yolov8n.pt")  # 支持检测 basketball hoop (72) / sports ball (32)
    model = YOLO("yolov8s.pt")  # 支持检测 basketball hoop (72) / sports ball (32)
    return model


def get_video_info(video_path):
    """获取视频基本信息：帧率、总帧数、宽高"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"无法打开视频文件：{video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_seconds = total_frames / fps  # 视频总时长（秒）

    cap.release()
    return fps, total_frames, width, height, total_seconds


def auto_detect_hoop_area(model, video_path, fps):
    """自动检测篮筐位置，返回篮筐核心检测区域 + 保存篮筐位置截图"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"无法打开视频文件：{video_path}")

    # 计算需要扫描的帧数（前 SCAN_SECONDS 秒）
    scan_frames = int(fps * SCAN_SECONDS)
    hoop_boxes = []  # 存储检测到的篮筐框坐标
    hoop_screenshot_frame = None  # 用于保存截图的帧
    best_hoop_box = None  # 最佳篮筐框（用于截图标注）

    print(f"\n🔍 正在扫描前 {SCAN_SECONDS} 秒画面，自动定位篮筐...")
    # 加进度条显示扫描进度
    for frame_idx in tqdm(range(scan_frames), desc="篮筐定位进度", unit="帧"):
        ret, frame = cap.read()
        if not ret:
            break

        # 每2帧检测一次（提速）
        if frame_idx % 2 == 0:
            # 只检测篮筐（class 72）
            results = model(frame, conf=HOOP_CONF_THRESHOLD, classes=[72])
            for r in results:
                for box in r.boxes:
                    # 提取篮筐框的坐标（x1,y1,x2,y2）
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    hoop_boxes.append([x1, y1, x2, y2])
                    # 保存第一个清晰的篮筐框作为截图标注用
                    if best_hoop_box is None:
                        best_hoop_box = [int(x1), int(y1), int(x2), int(y2)]
                        hoop_screenshot_frame = frame.copy()

    # 获取视频宽高信息（在释放前获取）
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    cap.release()

    if not hoop_boxes:
        # 未检测到篮筐，降级使用默认区域（右上侧）
        print("⚠️ 未检测到篮筐，使用默认右上侧区域")
        x1 = int(0.6 * width)
        x2 = int(0.9 * width)
        y1 = int(0.1 * height)
        y2 = int(0.5 * height)

        # 截图标注默认区域
        if hoop_screenshot_frame is None:
            # 重新读取第一帧作为截图
            cap_temp = cv2.VideoCapture(video_path)
            ret, hoop_screenshot_frame = cap_temp.read()
            cap_temp.release()
        # 画红色框标注默认篮筐区域（线宽3）
        cv2.rectangle(hoop_screenshot_frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
        # 添加文字说明
        cv2.putText(hoop_screenshot_frame, "Default Hoop Area", (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    else:
        # 计算所有篮筐框的平均值，作为篮筐核心位置
        hoop_boxes = np.array(hoop_boxes)
        avg_x1 = np.mean(hoop_boxes[:, 0])
        avg_y1 = np.mean(hoop_boxes[:, 1])
        avg_x2 = np.mean(hoop_boxes[:, 2])
        avg_y2 = np.mean(hoop_boxes[:, 3])

        # 计算篮筐中心坐标
        center_x = (avg_x1 + avg_x2) / 2
        center_y = (avg_y1 + avg_y2) / 2

        # 计算篮筐框的宽度和高度
        hoop_width = avg_x2 - avg_x1
        hoop_height = avg_y2 - avg_y1

        # 以中心为基准，扩大 HOOP_AREA_SCALE 倍作为检测区域
        expand_w = hoop_width * HOOP_AREA_SCALE / 2
        expand_h = hoop_height * HOOP_AREA_SCALE / 2

        # 确定最终检测区域（避免超出视频边界）
        x1 = max(0, int(center_x - expand_w))
        x2 = min(width, int(center_x + expand_w))
        y1 = max(0, int(center_y - expand_h))
        y2 = min(height, int(center_y + expand_h))

        print(f"✅ 自动定位篮筐完成！检测区域：x1={x1}, x2={x2}, y1={y1}, y2={y2}")

        # 截图标注自动检测的篮筐区域
        if hoop_screenshot_frame is None:
            cap_temp = cv2.VideoCapture(video_path)
            ret, hoop_screenshot_frame = cap_temp.read()
            cap_temp.release()
        # 画红色框标注实际篮筐位置（线宽3）
        if best_hoop_box is not None:
            cv2.rectangle(hoop_screenshot_frame, (best_hoop_box[0], best_hoop_box[1]),
                          (best_hoop_box[2], best_hoop_box[3]), (0, 0, 255), 3)
            cv2.putText(hoop_screenshot_frame, "Detected Hoop", (best_hoop_box[0], best_hoop_box[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        # 画红色实线框标注扩大后的检测区域（使用实线而不是虚线，更清晰）
        cv2.rectangle(hoop_screenshot_frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
        cv2.putText(hoop_screenshot_frame, "Detection Area", (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

    # 保存篮筐位置截图
    cv2.imwrite(SCREENSHOT_PATH, hoop_screenshot_frame)
    print(f"📸 篮筐位置截图已保存至：{os.path.abspath(SCREENSHOT_PATH)}")

    return (x1, x2, y1, y2)


def detect_goal_frames(model, video_path, fps, hoop_area, total_frames):
    """检测视频中进球的关键帧（带进度显示）"""
    cap = cv2.VideoCapture(video_path)
    goal_frames = []  # 存储进球的关键帧编号
    frame_idx = 0
    x1, x2, y1, y2 = hoop_area  # 自动定位的篮筐检测区域

    print("\n🎯 正在检测进球画面...")
    # 加进度条显示检测进度
    with tqdm(total=total_frames, desc="进球检测进度", unit="帧") as pbar:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            # 每5帧检测一次（提速）
            if frame_idx % 5 == 0:
                # 检测篮球（class 32）
                results = model(frame, conf=CONF_THRESHOLD, classes=[32])

                # 解析检测结果
                ball_boxes = []  # 篮球的检测框
                for r in results:
                    for box in r.boxes:
                        cls = int(box.cls[0])
                        if cls == 32:  # sports ball
                            ball_boxes.append(box.xyxy[0].cpu().numpy())

                # 判断进球：篮球出现在篮筐检测区域内
                if ball_boxes:
                    for ball in ball_boxes:
                        ball_center_x = (ball[0] + ball[2]) / 2
                        ball_center_y = (ball[1] + ball[3]) / 2
                        # 篮球中心在篮筐区域内，判定为进球
                        if (x1 < ball_center_x < x2) and (y1 < ball_center_y < y2):
                            goal_frames.append(frame_idx)
                            print(f"\n检测到进球：第 {frame_idx} 帧（{frame_idx / fps:.2f} 秒）")
                            break  # 避免同一帧多次判定

            frame_idx += 1
            pbar.update(1)  # 更新进度条

    cap.release()
    # 去重：相邻帧只保留一个
    goal_frames = sorted(list(set(goal_frames)))
    return goal_frames


def clip_goal_segments(video_path, goal_frames, fps):
    """根据进球关键帧，用 FFmpeg 剪辑进球片段（带进度显示）"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"\n✂️ 正在剪辑 {len(goal_frames)} 个进球片段...")
    # 加进度条显示剪辑进度
    for i, frame in enumerate(tqdm(goal_frames, desc="剪辑进度", unit="片段")):
        goal_sec = frame / fps
        start_sec = max(0, goal_sec - GOAL_BEFORE_SEC)
        end_sec = goal_sec + GOAL_AFTER_SEC

        output_path = os.path.join(OUTPUT_DIR, f"goal_{i + 1}.mp4")

        # FFmpeg 剪辑命令
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_sec),
            "-to", str(end_sec),
            "-i", video_path,
            "-c:v", "copy",
            "-c:a", "copy",
            output_path
        ]

        try:
            subprocess.run(ffmpeg_cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            print(f"\n❌ 剪辑失败：{output_path}，错误：{e}")


# ===================== 主程序 =====================
if __name__ == "__main__":
    # 记录总耗时
    total_start_time = time.time()

    # 1. 初始化模型
    model = init_yolo_model()

    # 2. 获取视频信息
    fps, total_frames, width, height, total_seconds = get_video_info(VIDEO_PATH)
    print(f"\n📹 视频信息：")
    print(f"   - 分辨率：{width}x{height}")
    print(f"   - 帧率：{fps} FPS")
    print(f"   - 总帧数：{total_frames} 帧")
    print(f"   - 总时长：{total_seconds:.2f} 秒 ({total_seconds / 60:.2f} 分钟)")

    # 3. 自动检测篮筐位置（核心优化）
    hoop_start_time = time.time()
    hoop_area = auto_detect_hoop_area(model, VIDEO_PATH, fps)
    hoop_cost_time = time.time() - hoop_start_time
    print(f"⏱️  篮筐定位耗时：{hoop_cost_time:.2f} 秒")

    # 4. 检测进球关键帧
    detect_start_time = time.time()
    goal_frames = detect_goal_frames(model, VIDEO_PATH, fps, hoop_area, total_frames)
    detect_cost_time = time.time() - detect_start_time
    if not goal_frames:
        print("❌ 未检测到任何进球画面")
    else:
        print(f"✅ 共检测到 {len(goal_frames)} 个进球关键帧")
        print(f"⏱️  进球检测耗时：{detect_cost_time:.2f} 秒")

    # 5. 剪辑进球片段
    if goal_frames:
        clip_start_time = time.time()
        clip_goal_segments(VIDEO_PATH, goal_frames, fps)
        clip_cost_time = time.time() - clip_start_time
        print(f"⏱️  视频剪辑耗时：{clip_cost_time:.2f} 秒")

    # 6. 统计总耗时
    total_cost_time = time.time() - total_start_time
    print(f"\n🎉 全部处理完成！")
    print(f"⏱️  总耗时：{total_cost_time:.2f} 秒 ({total_cost_time / 60:.2f} 分钟)")
    if goal_frames:
        print(f"📁 进球片段保存至：{os.path.abspath(OUTPUT_DIR)}")
    print(f"📸 篮筐位置截图：{os.path.abspath(SCREENSHOT_PATH)}")