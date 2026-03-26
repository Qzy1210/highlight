import time

import cv2
import numpy as np
from ultralytics import YOLO
import subprocess
import os
# 耗时 Done. Total execution time: 924.80 seconds (15.41 minutes)
VIDEO_PATH = "IMG_1556.MOV"
OUTPUT_DIR = "highlights"
PRE_SECONDS = 8
POST_SECONDS = 2

HOOP_REGION = {
    "x1": 800,
    "y1": 300,
    "x2": 1000,
    "y2": 500
}

model = YOLO("yolov8n.pt")

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# 记录程序开始时间
start_time = time.time()

cap = cv2.VideoCapture(VIDEO_PATH)
fps = cap.get(cv2.CAP_PROP_FPS)

goal_times = []
frame_index = 0
cooldown = 0

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # cv2.rectangle(frame,
    #               (int(x1), int(y1)),
    #               (int(x2), int(y2)),
    #               (0, 255, 0),
    #               2)
    #
    # cv2.imwrite("debug_detect.jpg", frame) # 保存一帧图片 debug
    # break
    frame_index += 1
    current_time = frame_index / fps

    if cooldown > 0:
        cooldown -= 1
        continue

    results = model(frame)

    for r in results:
        for box in r.boxes:
            cls_id = int(box.cls[0])
            label = model.names[cls_id]

            conf = float(box.conf[0])
            if label != "person":
                print(label)
            print("---+++----")
            print(conf)  # 0.8243398070335388
            if label == "sports ball":
                x1, y1, x2, y2 = box.xyxy[0]
                center_x = (x1 + x2) / 2
                center_y = (y1 + y2) / 2

                if (HOOP_REGION["x1"] < center_x < HOOP_REGION["x2"] and
                    HOOP_REGION["y1"] < center_y < HOOP_REGION["y2"]):

                    print(f"Goal detected at {current_time:.2f}s")
                    goal_times.append(current_time)
                    cooldown = int(fps * 3)
                    break

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
