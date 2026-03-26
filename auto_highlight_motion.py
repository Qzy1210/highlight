import cv2
import numpy as np
import subprocess
import os
import time
from ultralytics import YOLO

# 耗时 time: 857.80 seconds (14.30 minutes)
# 优化每3帧检测一次后  time: 335.55 seconds (5.59 minutes)

VIDEO_PATH = "IMG_1556.MOV"
OUTPUT_DIR = "highlights"
PRE_SECONDS = 8
POST_SECONDS = 2

# ⚠️ 根据你的截图大致估算的篮框区域（调整为更精确的篮网区域）
HOOP_REGION = {
    "x1": 830,
    "y1": 300,
    "x2": 900,
    "y2": 400
}

# 篮筐上方区域（用于检测篮球经过）
HOOP_ABOVE_REGION = {
    "x1": 800,
    "y1": 200,
    "x2": 930,
    "y2": 300
}

MOTION_THRESHOLD = 0.04      # 提高阈值，只检测大幅度运动（篮网晃动）
MIN_CONTINUOUS_FRAMES = 12   # 增加连续帧数，确保是持续晃动
COOLDOWN_SECONDS = 5         # 进球后冷却时间

# 创建背景减除器
backSub = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=50, detectShadows=True)

# 加载YOLO模型用于篮球检测
model = YOLO("yolov8n.pt")

# 篮球检测参数
BALL_CONFIDENCE = 0.5  # 篮球检测置信度阈值
BALL_TRACKING_FRAMES = 5  # 篮球跟踪帧数
ball_positions = []  # 存储篮球位置历史

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# 记录程序开始时间
start_time = time.time()

cap = cv2.VideoCapture(VIDEO_PATH)
fps = cap.get(cv2.CAP_PROP_FPS)

prev_gray = None
frame_index = 0
motion_count = 0
cooldown = 0
goal_times = []

FRAME_SKIP = 3  # 每3帧检测一次


while True:
    ret, frame = cap.read()
    if not ret:
        break

    debug_frame = frame.copy()
    # 给篮框话红框，然后看图调整圈起来的位置  x1 y1 左上角的坐标  x2 y2 右下角的坐标
    # cv2.rectangle(
    #     debug_frame,
    #     (HOOP_REGION["x1"], HOOP_REGION["y1"]),
    #     (HOOP_REGION["x2"], HOOP_REGION["y2"]),
    #     (0, 0, 255),
    #     3
    # )
    # cv2.imwrite("roi_position.jpg", debug_frame)
    # break


    frame_index += 1
    current_time = frame_index / fps

    if frame_index % FRAME_SKIP != 0:
        continue  # 跳过非检测帧

    if cooldown > 0:
        cooldown -= 1
        ball_positions.clear()  # 冷却期间清空篮球位置历史
        continue

    # 篮球检测
    ball_detected = False
    results = model(frame)
    for r in results:
        boxes = r.boxes
        for box in boxes:
            # COCO数据集中，类别0是person, 32是sports ball
            if int(box.cls[0]) == 32 and float(box.conf[0]) > BALL_CONFIDENCE:
                ball_detected = True
                # 获取篮球中心点坐标
                x1, y1, x2, y2 = box.xyxy[0]
                center_x = int((x1 + x2) / 2)
                center_y = int((y1 + y2) / 2)
                
                # 检查篮球是否在篮筐上方区域
                if (HOOP_ABOVE_REGION["x1"] <= center_x <= HOOP_ABOVE_REGION["x2"] and
                    HOOP_ABOVE_REGION["y1"] <= center_y <= HOOP_ABOVE_REGION["y2"]):
                    ball_positions.append((center_x, center_y, current_time))
                
                # 保持篮球位置历史记录的长度
                if len(ball_positions) > BALL_TRACKING_FRAMES:
                    ball_positions.pop(0)
    
    # 检查篮球是否经过篮筐区域
    goal_detected = False
    if len(ball_positions) >= 3:  # 至少需要3个点来判断轨迹
        # 检查篮球是否从上到下穿过篮筐区域
        first_pos = ball_positions[0]
        last_pos = ball_positions[-1]
        
        # 判断篮球是否从篮筐上方区域进入并穿过
        if first_pos[1] < HOOP_ABOVE_REGION["y2"] < last_pos[1]:
            goal_detected = True
    
    # 裁剪篮框区域（用于篮网晃动检测）
    roi = frame[
        HOOP_REGION["y1"]:HOOP_REGION["y2"],
        HOOP_REGION["x1"]:HOOP_REGION["x2"]
    ]
    # 只裁剪篮框位置的截图
    # cv2.imwrite("roi_debug.jpg", roi)
    # break
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    if prev_gray is None:
        prev_gray = gray
        continue

    # 帧差
    diff = cv2.absdiff(prev_gray, gray)
    _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)

    motion_ratio = np.sum(thresh > 0) / thresh.size

    # 结合两种检测方法
    if motion_ratio > MOTION_THRESHOLD:
        motion_count += 1
    else:
        motion_count = 0

    # 如果检测到篮球经过篮筐或篮网晃动，则认为是进球
    if motion_count >= MIN_CONTINUOUS_FRAMES or goal_detected:
        print(f"Goal detected at {current_time:.2f}s")
        goal_times.append(current_time)
        cooldown = int(fps * COOLDOWN_SECONDS)
        motion_count = 0
        ball_positions.clear()  # 检测到进球后清空篮球位置历史

    prev_gray = gray

cap.release()

# 裁剪视频
for idx, t in enumerate(goal_times):
    start = max(t - PRE_SECONDS, 0)
    end = t + POST_SECONDS

    output_file = f"{OUTPUT_DIR}/goal_{idx+1}.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start),
        "-to", str(end),
        "-i", VIDEO_PATH,
        "-c", "copy",
        output_file
    ]

    subprocess.run(cmd)

# 记录程序结束时间并输出耗时
end_time = time.time()
total_time = end_time - start_time
print(f"Done. Total execution time: {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
