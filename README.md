### 高光时刻

自动识别特殊场景，自动剪辑视频。

### 抓取野球场公开视频素材（合规 API）
新增脚本 `download_field_videos.py`，通过 Pexels/Pixabay 公开 API 按关键词下载视频，自动去重并写入元数据。

```bash
# 1) 安装依赖
pip install requests

# 2) 配置 API Key（至少一个）
export PEXELS_API_KEY="你的_pexels_key"
export PIXABAY_API_KEY="你的_pixabay_key"

# 3) 执行下载（默认关键词已包含 baseball field / 棒球场 / 野球场）
python download_field_videos.py \
  --provider both \
  --per-query 10 \
  --max-total 30 \
  --output-dir workspace/field_videos

# 4) 自定义关键词
python download_field_videos.py \
  --provider pexels \
  --queries "baseball field" "amateur baseball game" "野球场" \
  --max-total 20
```

输出内容：
- 视频文件：`workspace/field_videos/*.mp4`
- 元数据：`workspace/field_videos/metadata.jsonl`

### 项目搭建流程
```
1. 创建虚拟环境
    python3 -m venv venv
2. 激活虚拟环境
    source venv/bin/activate
3. 安装依赖
    pip install --upgrade pip
    pip install ultralytics opencv-python numpy
        ultralytics: 用于使用和训练 YOLOv8、YOLOv5 等 YOLO 系列目标检测模型。
            1. 加载预训练的 YOLO 模型（如 yolov8n.pt）
            2. 进行图像/视频目标检测、实例分割、姿态估计等.
        opencv-python: Python 版的 OpenCV，用于图像和视频处理.
            1. 读取/保存图像（cv2.imread, cv2.imwrite）
            2. 图像变换（缩放、旋转、滤波）
            3. 绘制边界框、文字（常用于可视化检测结果）
            4. 视频流处理（摄像头、视频文件）
        numpy: Python 科学计算的基础库，提供高性能的多维数组（ndarray）操作.
            1. OpenCV 的图像本质是 numpy.ndarray
            2. PyTorch/TensorFlow 的张量经常与 NumPy 数组互转
            3. 几乎所有科学计算、机器学习库都依赖 NumPy
4. 运行脚本
    python auto_highlight.py
    
    
      # 自定义检测参数
  python auto_highlight_motion_auto_detect_v3_refactored.py \
    --input video.mp4 \
    --motion-threshold 0.05 \
    --cooldown 8 \
    --pre-seconds 10
    --debug
``` 
