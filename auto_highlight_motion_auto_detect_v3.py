import cv2
import numpy as np
import subprocess
import os
import time
import json
from datetime import datetime
from ultralytics import YOLO

VIDEO_PATH = "IMG_1556.MOV"
OUTPUT_DIR = "highlights"
PRE_SECONDS = 8
POST_SECONDS = 2

# ✅ 自动检测参数
AUTO_DETECT_FRAMES = 300  # 用于自动检测篮筐的帧数
HOOP_DETECTION_METHOD = "auto"  # 可选: "color", "yolo", "trajectory", "auto", "manual"

# 检测参数（自动检测后会更新）
MOTION_THRESHOLD = 0.04
MIN_CONTINUOUS_FRAMES = 12
COOLDOWN_SECONDS = 5
BALL_CONFIDENCE = 0.5
BALL_TRACKING_FRAMES = 5
FRAME_SKIP = 3

# 功能增强配置
DEBUG_MODE = False
ENABLE_PROGRESS = True
PROGRESS_INTERVAL = 100

# 检测区域（将由自动检测填充）
DETECTION_REGION = {}
HOOP_REGION = {}
HOOP_ABOVE_REGION = {}


def simple_dbscan(points, eps=50, min_samples=5):
    """
    简化版DBSCAN聚类算法（不依赖sklearn）
    """
    n_points = len(points)
    labels = [-1] * n_points
    cluster_id = 0
    
    for i in range(n_points):
        if labels[i] != -1:
            continue
        
        # 找到点i的邻居
        neighbors = []
        for j in range(n_points):
            if i != j:
                dist = np.sqrt((points[i][0] - points[j][0])**2 + 
                              (points[i][1] - points[j][1])**2)
                if dist < eps:
                    neighbors.append(j)
        
        # 如果邻居数量不足，标记为噪声
        if len(neighbors) < min_samples:
            continue
        
        # 创建新簇
        labels[i] = cluster_id
        
        # 扩展簇
        seed_set = neighbors.copy()
        for j in seed_set:
            if labels[j] == -1:
                labels[j] = cluster_id
                # 找到j的邻居
                j_neighbors = []
                for k in range(n_points):
                    if k != j:
                        dist = np.sqrt((points[j][0] - points[k][0])**2 + 
                                      (points[j][1] - points[k][1])**2)
                        if dist < eps:
                            j_neighbors.append(k)
                if len(j_neighbors) >= min_samples:
                    for neighbor in j_neighbors:
                        if neighbor not in seed_set:
                            seed_set.append(neighbor)
        
        cluster_id += 1
    
    return labels


def detect_hoop_by_color_enhanced(video_path, sample_frames=300):
    """
    增强版篮筐检测：颜色 + 霍夫圆 + 边缘特征融合
    """
    print("🔍 增强版检测：颜色 + 霍夫圆 + 边缘特征融合...")
    
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    sample_interval = max(1, total_frames // sample_frames)
    
    hoop_candidates = []  # 存储所有候选篮筐
    frame_count = 0
    
    print(f"  视频分辨率: {frame_width}x{frame_height}")
    print(f"  采样帧数: {sample_frames}, 间隔: {sample_interval}")
    
    while frame_count < sample_frames:
        ret, frame = cap.read()
        if not ret:
            break
            
        frame_count += 1
        if frame_count % sample_interval != 0:
            continue
        
        # ========== 方法1: 多颜色检测 ==========
        color_candidates = detect_by_multiple_colors(frame)
        
        # ========== 方法2: 霍夫圆检测 ==========
        hough_candidates = detect_by_hough_circles(frame)
        
        # ========== 方法3: 边缘特征检测 ==========
        edge_candidates = detect_by_edge_features(frame)
        
        # ========== 融合候选结果 ==========
        all_candidates = color_candidates + hough_candidates + edge_candidates
        
        # 对候选结果进行聚类和验证
        if all_candidates:
            validated = validate_and_merge_candidates(all_candidates, frame_width, frame_height)
            hoop_candidates.extend(validated)
    
    cap.release()
    
    # ========== 统计分析 ==========
    if len(hoop_candidates) > sample_frames * 0.05:  # 至少5%的帧检测到
        result = analyze_hoop_candidates(hoop_candidates, frame_width, frame_height)
        if result:
            print(f"✅ 检测到篮筐位置: 中心({result[0]}, {result[1]}), 半径{result[2]}")
            return result
    
    print("⚠️  增强检测法未找到稳定篮筐位置")
    return None


def detect_by_multiple_colors(frame):
    """
    多颜色检测：橙色、红色、白色、银色、黄色
    """
    candidates = []
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    # 定义多个颜色范围
    color_ranges = [
        # 橙色
        ([10, 80, 80], [25, 255, 255], "orange"),
        # 红色1
        ([0, 80, 80], [10, 255, 255], "red1"),
        # 红色2
        ([170, 80, 80], [180, 255, 255], "red2"),
        # 黄色
        ([26, 80, 80], [35, 255, 255], "yellow"),
    ]
    
    for lower, upper, color_name in color_ranges:
        lower = np.array(lower)
        upper = np.array(upper)
        mask = cv2.inRange(hsv, lower, upper)
        
        # 形态学操作
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        
        # 查找轮廓
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        for contour in contours:
            area = cv2.contourArea(contour)
            # 降低面积阈值，适应远距离拍摄
            if area > 30 and area < 30000:
                (x, y), radius = cv2.minEnclosingCircle(contour)
                radius = int(radius)
                
                # 降低半径阈值
                if radius > 3 and radius < 200:
                    # 形状验证：圆度
                    perimeter = cv2.arcLength(contour, True)
                    if perimeter > 0:
                        circularity = 4 * np.pi * area / (perimeter ** 2)
                        # 圆度在0.3-1.0之间（篮框可能不是完美圆形）
                        if circularity > 0.2:
                            candidates.append({
                                'center': (int(x), int(y)),
                                'radius': radius,
                                'area': area,
                                'circularity': circularity,
                                'method': f'color_{color_name}',
                                'confidence': circularity * (area / 1000)
                            })
    
    # 白色/银色检测（高亮度区域）
    bright_mask = cv2.inRange(gray, 200, 255)
    kernel = np.ones((3, 3), np.uint8)
    bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_CLOSE, kernel)
    
    contours, _ = cv2.findContours(bright_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    for contour in contours:
        area = cv2.contourArea(contour)
        if area > 20 and area < 20000:
            (x, y), radius = cv2.minEnclosingCircle(contour)
            radius = int(radius)
            
            if radius > 2 and radius < 150:
                perimeter = cv2.arcLength(contour, True)
                if perimeter > 0:
                    circularity = 4 * np.pi * area / (perimeter ** 2)
                    if circularity > 0.2:
                        candidates.append({
                            'center': (int(x), int(y)),
                            'radius': radius,
                            'area': area,
                            'circularity': circularity,
                            'method': 'color_white',
                            'confidence': circularity * (area / 1000) * 0.8  # 白色权重稍低
                        })
    
    return candidates


def detect_by_hough_circles(frame):
    """
    霍夫圆检测篮框
    """
    candidates = []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    # 高斯模糊
    blurred = cv2.GaussianBlur(gray, (9, 9), 2)
    
    # 霍夫圆检测
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1,
        minDist=50,
        param1=50,
        param2=30,
        minRadius=5,
        maxRadius=150
    )
    
    if circles is not None:
        circles = np.uint16(np.around(circles))
        
        for circle in circles[0, :]:
            x, y, radius = circle[0], circle[1], circle[2]
            
            # 验证圆形区域
            mask = np.zeros(gray.shape, dtype=np.uint8)
            cv2.circle(mask, (x, y), radius, 255, 2)  # 只画圆环
            
            # 检查圆环上是否有足够的边缘
            edges = cv2.Canny(gray, 50, 150)
            edge_pixels = np.sum(edges[mask > 0] > 0)
            total_pixels = np.sum(mask > 0)
            
            if total_pixels > 0:
                edge_ratio = edge_pixels / total_pixels
                
                # 圆环上边缘像素比例应该较高
                if edge_ratio > 0.3:
                    candidates.append({
                        'center': (int(x), int(y)),
                        'radius': int(radius),
                        'area': np.pi * radius ** 2,
                        'circularity': 0.9,  # 霍夫圆默认圆度较高
                        'method': 'hough_circle',
                        'confidence': edge_ratio * 2
                    })
    
    return candidates


def detect_by_edge_features(frame):
    """
    边缘特征检测：寻找矩形/椭圆形篮框
    """
    candidates = []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    # 边缘检测
    edges = cv2.Canny(gray, 50, 150)
    
    # 形态学操作连接边缘
    kernel = np.ones((5, 5), np.uint8)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
    
    # 查找轮廓
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    for contour in contours:
        area = cv2.contourArea(contour)
        
        if area > 50 and area < 25000:
            # 最小外接矩形
            rect = cv2.minAreaRect(contour)
            (rx, ry), (rw, rh), angle = rect
            
            # 篮框通常是宽>高，纵横比在1.5-3.0之间
            aspect_ratio = max(rw, rh) / (min(rw, rh) + 1e-5)
            
            if 1.2 < aspect_ratio < 4.0:
                # 矩形度
                rect_area = rw * rh
                if rect_area > 0:
                    extent = area / rect_area
                    
                    # 椭圆拟合
                    if len(contour) >= 5:
                        ellipse = cv2.fitEllipse(contour)
                        (ex, ey), (ea, eb), eangle = ellipse
                        
                        # 椭圆面积
                        ellipse_area = np.pi * ea * eb / 4
                        
                        if ellipse_area > 0:
                            ellipse_ratio = area / ellipse_area
                            
                            # 验证是否像篮框
                            if extent > 0.3 and ellipse_ratio > 0.5:
                                # 使用椭圆中心和外接矩形尺寸
                                radius = int(max(rw, rh) / 2)
                                
                                candidates.append({
                                    'center': (int(ex), int(ey)),
                                    'radius': radius,
                                    'area': area,
                                    'circularity': extent,
                                    'method': 'edge_feature',
                                    'confidence': extent * aspect_ratio * 0.5
                                })
    
    return candidates


def validate_and_merge_candidates(candidates, frame_width, frame_height):
    """
    验证和合并候选结果
    """
    validated = []
    
    for candidate in candidates:
        x, y = candidate['center']
        radius = candidate['radius']
        
        # 位置验证：篮框通常在画面上半部分
        if y > frame_height * 0.8:  # 太靠下，不太可能是篮框
            continue
        
        if y < frame_height * 0.05:  # 太靠上
            continue
        
        # 边界验证
        if x < radius or x > frame_width - radius:
            continue
        
        if y < radius or y > frame_height - radius:
            continue
        
        # 置信度过滤
        if candidate['confidence'] > 0.1:
            validated.append(candidate)
    
    return validated


def analyze_hoop_candidates(candidates, frame_width, frame_height):
    """
    分析候选篮框，确定最终位置
    """
    if not candidates:
        return None
    
    # 提取中心和半径
    centers = [c['center'] for c in candidates]
    radii = [c['radius'] for c in candidates]
    confidences = [c['confidence'] for c in candidates]
    
    # 加权聚类
    # 1. 按置信度排序
    sorted_candidates = sorted(candidates, key=lambda x: x['confidence'], reverse=True)
    
    # 2. 取高置信度候选的中心作为初始种子
    top_candidates = sorted_candidates[:max(10, len(sorted_candidates) // 5)]
    
    if not top_candidates:
        return None
    
    # 3. 计算加权中心
    total_weight = sum(c['confidence'] for c in top_candidates)
    if total_weight == 0:
        return None
    
    center_x = int(sum(c['center'][0] * c['confidence'] for c in top_candidates) / total_weight)
    center_y = int(sum(c['center'][1] * c['confidence'] for c in top_candidates) / total_weight)
    
    # 4. 计算半径（使用中位数，更鲁棒）
    radius = int(np.median([c['radius'] for c in top_candidates]))
    
    # 5. 验证最终结果
    # 统计在最终位置附近的候选数量
    nearby_count = 0
    for c in candidates:
        dist = np.sqrt((c['center'][0] - center_x)**2 + (c['center'][1] - center_y)**2)
        if dist < radius * 2:  # 在2倍半径范围内
            nearby_count += 1
    
    # 至少有一定比例的候选在附近
    if nearby_count < len(candidates) * 0.3:
        return None
    
    # 确保半径合理
    radius = max(10, min(radius, min(frame_width, frame_height) // 4))
    
    return (center_x, center_y, radius)


def manual_hoop_selection(video_path):
    """
    手动选择篮筐位置
    """
    print("\n" + "="*60)
    print("📷 自动检测失败，启动手动标注模式")
    print("="*60)
    
    # 提取视频中间帧
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    middle_frame = total_frames // 2
    
    cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame)
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        print("❌ 无法读取视频帧")
        return None
    
    # 保存标注图片
    manual_frame_path = "manual_hoop_selection.jpg"
    cv2.imwrite(manual_frame_path, frame)
    
    print(f"\n已提取视频中间帧保存为: {manual_frame_path}")
    print("\n请在图片上标注篮筐区域：")
    print("1. 用鼠标拖拽绘制矩形框选篮筐")
    print("2. 按 'c' 确认选择")
    print("3. 按 'r' 重新选择")
    print("4. 按 'q' 退出")
    
    # 全局变量存储选择结果
    selection = {'rect': None, 'confirmed': False}
    
    def mouse_callback(event, x, y, flags, param):
        nonlocal selection
        if event == cv2.EVENT_LBUTTONDOWN:
            selection['start'] = (x, y)
            selection['drawing'] = True
        elif event == cv2.EVENT_MOUSEMOVE and selection.get('drawing'):
            selection['end'] = (x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            selection['end'] = (x, y)
            selection['drawing'] = False
    
    cv2.namedWindow('Manual Hoop Selection')
    cv2.setMouseCallback('Manual Hoop Selection', mouse_callback)
    
    while True:
        display_frame = frame.copy()
        
        # 绘制当前选择
        if 'start' in selection and 'end' in selection:
            cv2.rectangle(display_frame, selection['start'], selection['end'], (0, 255, 0), 2)
            
            # 计算中心和半径
            x1, y1 = selection['start']
            x2, y2 = selection['end']
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2
            radius = max(abs(x2 - x1), abs(y2 - y1)) // 2
            
            cv2.circle(display_frame, (center_x, center_y), radius, (0, 0, 255), 2)
            cv2.putText(display_frame, f"Center: ({center_x}, {center_y}), Radius: {radius}",
                       (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        # 显示提示
        cv2.putText(display_frame, "Draw rectangle around hoop | 'c': confirm | 'r': reset | 'q': quit",
                   (10, display_frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        cv2.imshow('Manual Hoop Selection', display_frame)
        
        key = cv2.waitKey(1) & 0xFF
        
        if key == ord('c') and 'start' in selection and 'end' in selection:
            selection['confirmed'] = True
            break
        elif key == ord('r'):
            selection = {'rect': None, 'confirmed': False}
        elif key == ord('q'):
            break
    
    cv2.destroyAllWindows()
    
    if selection['confirmed'] and 'start' in selection and 'end' in selection:
        x1, y1 = selection['start']
        x2, y2 = selection['end']
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        radius = max(abs(x2 - x1), abs(y2 - y1)) // 2
        
        print(f"\n✅ 手动标注完成: 中心({center_x}, {center_y}), 半径{radius}")
        return (center_x, center_y, radius)
    
    print("\n❌ 手动标注取消")
    return None


def detect_hoop_by_yolo(video_path, sample_frames=300):
    """
    使用YOLO检测篮球，推断篮筐位置
    """
    print("🔍 方法2: YOLO推断法 - 检测篮球轨迹推断篮筐...")
    
    model = YOLO("yolov8n.pt")
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sample_interval = max(1, total_frames // sample_frames)
    
    ball_positions = []
    frame_count = 0
    
    while frame_count < sample_frames:
        ret, frame = cap.read()
        if not ret:
            break
            
        frame_count += 1
        if frame_count % sample_interval != 0:
            continue
        
        # 检测篮球
        results = model(frame, classes=[32], verbose=False, conf=0.3)
        
        for r in results:
            for box in r.boxes:
                if float(box.conf[0]) > 0.3:
                    x1, y1, x2, y2 = box.xyxy[0]
                    center_x = int((x1 + x2) / 2)
                    center_y = int((y1 + y2) / 2)
                    ball_positions.append((center_x, center_y))
    
    cap.release()
    
    if len(ball_positions) < 10:
        print("⚠️  YOLO未检测到足够的篮球位置")
        return None
    
    # 使用简化版DBSCAN聚类
    labels = simple_dbscan(ball_positions, eps=50, min_samples=5)
    
    # 找到最大的簇
    unique_labels = set(labels) - {-1}
    if not unique_labels:
        print("⚠️  未找到明显的篮球聚集区域")
        return None
    
    largest_cluster_label = max(unique_labels, key=lambda l: labels.count(l))
    cluster_points = [ball_positions[i] for i in range(len(ball_positions)) if labels[i] == largest_cluster_label]
    
    # 计算聚类中心
    center_x = int(np.mean([p[0] for p in cluster_points]))
    center_y = int(np.mean([p[1] for p in cluster_points]))
    
    # 计算聚集范围作为半径
    distances = [np.sqrt((p[0] - center_x)**2 + (p[1] - center_y)**2) for p in cluster_points]
    radius = int(np.percentile(distances, 80))
    
    print(f"✅ 检测到篮筐位置（基于篮球轨迹）: 中心({center_x}, {center_y}), 半径{radius}")
    return (center_x, center_y, radius)


def detect_hoop_by_trajectory(video_path, sample_frames=500):
    """
    通过篮球轨迹分析篮筐位置
    """
    print("🔍 方法3: 轨迹分析法 - 分析篮球下落轨迹...")
    
    model = YOLO("yolov8n.pt")
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sample_interval = max(1, total_frames // sample_frames)
    
    ball_trajectories = []
    current_trajectory = []
    
    frame_count = 0
    prev_y = None
    
    while frame_count < sample_frames:
        ret, frame = cap.read()
        if not ret:
            break
            
        frame_count += 1
        if frame_count % sample_interval != 0:
            continue
        
        # 检测篮球
        results = model(frame, classes=[32], verbose=False, conf=0.3)
        
        ball_found = False
        for r in results:
            for box in r.boxes:
                if float(box.conf[0]) > 0.3:
                    x1, y1, x2, y2 = box.xyxy[0]
                    center_x = int((x1 + x2) / 2)
                    center_y = int((y1 + y2) / 2)
                    
                    ball_found = True
                    
                    # 检测篮球是否在下落
                    if prev_y is not None and center_y > prev_y + 10:
                        current_trajectory.append((center_x, center_y))
                    else:
                        if len(current_trajectory) >= 3:
                            ball_trajectories.append(current_trajectory.copy())
                        current_trajectory = [(center_x, center_y)]
                    
                    prev_y = center_y
                    break
        
        if not ball_found:
            if len(current_trajectory) >= 3:
                ball_trajectories.append(current_trajectory.copy())
            current_trajectory = []
            prev_y = None
    
    cap.release()
    
    if len(ball_trajectories) < 3:
        print("⚠️  未检测到足够的篮球下落轨迹")
        return None
    
    # 分析轨迹终点
    end_points = []
    for trajectory in ball_trajectories:
        if len(trajectory) >= 3:
            end_points.extend(trajectory[-3:])
    
    if len(end_points) < 5:
        print("⚠️  轨迹终点数据不足")
        return None
    
    # 计算终点中心
    end_array = np.array(end_points)
    center_x = int(np.median(end_array[:, 0]))
    center_y = int(np.median(end_array[:, 1]))
    
    # 计算聚集半径
    distances = np.sqrt((end_array[:, 0] - center_x)**2 + (end_array[:, 1] - center_y)**2)
    radius = int(np.percentile(distances, 80))
    
    print(f"✅ 检测到篮筐位置（基于轨迹分析）: 中心({center_x}, {center_y}), 半径{radius}")
    return (center_x, center_y, radius)


def auto_detect_hoop_region(video_path):
    """
    自动检测篮筐位置，尝试多种方法
    """
    print("\n" + "="*60)
    print("开始自动检测篮筐位置...")
    print("="*60)
    
    hoop_location = None
    
    # 方法1: 增强版颜色检测（最可靠）
    if HOOP_DETECTION_METHOD in ["color", "auto"]:
        hoop_location = detect_hoop_by_color_enhanced(video_path)
        if hoop_location:
            print(f"✅ 使用增强版颜色检测法成功")
            return hoop_location
    
    # 方法2: YOLO篮球轨迹聚类
    if HOOP_DETECTION_METHOD in ["yolo", "auto"] and not hoop_location:
        try:
            hoop_location = detect_hoop_by_yolo(video_path)
            if hoop_location:
                print(f"✅ 使用YOLO推断法成功")
                return hoop_location
        except Exception as e:
            print(f"⚠️  YOLO推断法失败: {e}")
    
    # 方法3: 轨迹分析
    if HOOP_DETECTION_METHOD in ["trajectory", "auto"] and not hoop_location:
        try:
            hoop_location = detect_hoop_by_trajectory(video_path)
            if hoop_location:
                print(f"✅ 使用轨迹分析法成功")
                return hoop_location
        except Exception as e:
            print(f"⚠️  轨迹分析法失败: {e}")
    
    # 方法4: 手动标注
    if not hoop_location:
        print("\n⚠️  自动检测失败，启动手动标注")
        hoop_location = manual_hoop_selection(video_path)
    
    return hoop_location


def setup_detection_regions(hoop_center_x, hoop_center_y, hoop_radius):
    """
    根据篮筐位置设置检测区域
    """
    global DETECTION_REGION, HOOP_REGION, HOOP_ABOVE_REGION
    
    # 篮筐区域
    HOOP_REGION = {
        "x1": hoop_center_x - hoop_radius,
        "y1": hoop_center_y - hoop_radius // 2,
        "x2": hoop_center_x + hoop_radius,
        "y2": hoop_center_y + hoop_radius
    }
    
    # 篮筐上方区域
    HOOP_ABOVE_REGION = {
        "x1": hoop_center_x - hoop_radius * 2,
        "y1": hoop_center_y - hoop_radius * 4,
        "x2": hoop_center_x + hoop_radius * 2,
        "y2": hoop_center_y - hoop_radius
    }
    
    # YOLO检测区域
    DETECTION_REGION = {
        "x1": hoop_center_x - hoop_radius * 3,
        "y1": hoop_center_y - hoop_radius * 5,
        "x2": hoop_center_x + hoop_radius * 3,
        "y2": hoop_center_y + hoop_radius * 2
    }
    
    print("\n" + "="*60)
    print("自动设置检测区域:")
    print("="*60)
    print(f"篮筐区域: {HOOP_REGION}")
    print(f"篮筐上方区域: {HOOP_ABOVE_REGION}")
    print(f"YOLO检测区域: {DETECTION_REGION}")
    print("="*60)


# 主程序
if __name__ == "__main__":
    # 自动检测篮筐位置
    hoop_result = auto_detect_hoop_region(VIDEO_PATH)
    
    if not hoop_result:
        print("\n❌ 未能确定篮筐位置，程序退出")
        exit(1)
    
    hoop_center_x, hoop_center_y, hoop_radius = hoop_result
    
    # 设置检测区域
    setup_detection_regions(hoop_center_x, hoop_center_y, hoop_radius)
    
    # 保存检测区域图片  debug-监测区域-start=========
    cap = cv2.VideoCapture(VIDEO_PATH)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    middle_frame = total_frames // 2
    cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame)
    ret, frame = cap.read()
    cap.release()
    
    if ret:
        # 创建副本用于绘制
        debug_frame = frame.copy()
        
        # 绘制篮筐区域（红色）
        cv2.rectangle(debug_frame,
                     (HOOP_REGION["x1"], HOOP_REGION["y1"]),
                     (HOOP_REGION["x2"], HOOP_REGION["y2"]),
                     (0, 0, 255), 2)
        cv2.putText(debug_frame, "Hoop Region",
                   (HOOP_REGION["x1"], HOOP_REGION["y1"] - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1)
        
        # 绘制篮筐上方区域（蓝色）
        cv2.rectangle(debug_frame,
                     (HOOP_ABOVE_REGION["x1"], HOOP_ABOVE_REGION["y1"]),
                     (HOOP_ABOVE_REGION["x2"], HOOP_ABOVE_REGION["y2"]),
                     (255, 0, 0), 2)
        cv2.putText(debug_frame, "Hoop Above Region",
                   (HOOP_ABOVE_REGION["x1"], HOOP_ABOVE_REGION["y1"] - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 1)
        
        # 绘制YOLO检测区域（绿色）
        cv2.rectangle(debug_frame,
                     (DETECTION_REGION["x1"], DETECTION_REGION["y1"]),
                     (DETECTION_REGION["x2"], DETECTION_REGION["y2"]),
                     (0, 255, 0), 2)
        cv2.putText(debug_frame, "Detection Region",
                   (DETECTION_REGION["x1"], DETECTION_REGION["y1"] - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
        
        # 保存三个区域的图片
        cv2.imwrite("hoop_region.jpg", debug_frame[HOOP_REGION["y1"]:HOOP_REGION["y2"], HOOP_REGION["x1"]:HOOP_REGION["x2"]])
        cv2.imwrite("hoop_above_region.jpg", debug_frame[HOOP_ABOVE_REGION["y1"]:HOOP_ABOVE_REGION["y2"], HOOP_ABOVE_REGION["x1"]:HOOP_ABOVE_REGION["x2"]])
        cv2.imwrite("detection_region.jpg", debug_frame[DETECTION_REGION["y1"]:DETECTION_REGION["y2"], DETECTION_REGION["x1"]:DETECTION_REGION["x2"]])
        
        # 保存包含所有区域的完整帧
        cv2.imwrite("all_detection_regions.jpg", debug_frame)
        # debug-监测区域-end=========
    # 加载YOLO模型
    model = YOLO("yolov8n.pt")
    ball_positions = []
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    
    start_time = time.time()
    
    cap = cv2.VideoCapture(VIDEO_PATH)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    prev_gray = None
    frame_index = 0
    motion_count = 0
    cooldown = 0
    goal_times = []
    goal_methods = []
    
    print("\n" + "="*60)
    print("篮球进球检测系统启动")
    print("="*60)
    print(f"视频文件: {VIDEO_PATH}")
    print(f"视频时长: {total_frames/fps:.1f}秒 ({total_frames} 帧)")
    print(f"帧率: {fps:.1f} FPS")
    print(f"自动检测篮筐: ({hoop_center_x}, {hoop_center_y}), 半径{hoop_radius}")
    print(f"调试模式: {'开启' if DEBUG_MODE else '关闭'}")
    print("="*60)
    print()
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        frame_index += 1
        current_time = frame_index / fps
        
        # 进度显示
        if ENABLE_PROGRESS and frame_index % PROGRESS_INTERVAL == 0:
            progress = frame_index / total_frames * 100
            elapsed = time.time() - start_time
            eta = elapsed / frame_index * (total_frames - frame_index)
            print(f"📊 处理进度: {progress:.1f}% ({frame_index}/{total_frames}) | "
                  f"已用时: {elapsed:.1f}s | 预计剩余: {eta:.1f}s")
        
        if frame_index % FRAME_SKIP != 0:
            continue
        
        if cooldown > 0:
            cooldown -= 1
            ball_positions.clear()
            continue
        
        # ROI裁剪 + YOLO检测
        detection_roi = frame[
            DETECTION_REGION["y1"]:DETECTION_REGION["y2"],
            DETECTION_REGION["x1"]:DETECTION_REGION["x2"]
        ]
        
        ball_detected = False
        results = model(detection_roi, classes=[32], verbose=False, conf=BALL_CONFIDENCE)
        
        for r in results:
            for box in r.boxes:
                if float(box.conf[0]) > BALL_CONFIDENCE:
                    ball_detected = True
                    x1_roi, y1_roi, x2_roi, y2_roi = box.xyxy[0]
                    center_x = int((x1_roi + x2_roi) / 2) + DETECTION_REGION["x1"]
                    center_y = int((y1_roi + y2_roi) / 2) + DETECTION_REGION["y1"]
                    
                    if (HOOP_ABOVE_REGION["x1"] <= center_x <= HOOP_ABOVE_REGION["x2"] and
                        HOOP_ABOVE_REGION["y1"] <= center_y <= HOOP_ABOVE_REGION["y2"]):
                        ball_positions.append((center_x, center_y, current_time))
                    
                    if len(ball_positions) > BALL_TRACKING_FRAMES:
                        ball_positions.pop(0)
        
        # 篮球轨迹检测
        goal_detected = False
        if len(ball_positions) >= 3:
            first_pos = ball_positions[0]
            last_pos = ball_positions[-1]
            
            if first_pos[1] < HOOP_ABOVE_REGION["y2"] < last_pos[1]:
                goal_detected = True
        
        # 篮网晃动检测
        roi = frame[
            HOOP_REGION["y1"]:HOOP_REGION["y2"],
            HOOP_REGION["x1"]:HOOP_REGION["x2"]
        ]
        
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        
        if prev_gray is None:
            prev_gray = gray
            continue
        
        diff = cv2.absdiff(prev_gray, gray)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        
        motion_ratio = np.sum(thresh > 0) / thresh.size
        
        if motion_ratio > MOTION_THRESHOLD:
            motion_count += 1
        else:
            motion_count = 0
        
        # 进球判定
        detection_method = ""
        if motion_count >= MIN_CONTINUOUS_FRAMES or goal_detected:
            if goal_detected:
                detection_method = "篮球轨迹"
            else:
                detection_method = "篮网晃动"
            
            print(f"✓ 进球检测！时间: {current_time:.2f}s (方法: {detection_method})")
            goal_times.append(current_time)
            goal_methods.append(detection_method)
            cooldown = int(fps * COOLDOWN_SECONDS)
            motion_count = 0
            ball_positions.clear()
        
        prev_gray = gray
        
        # 可视化调试
        if DEBUG_MODE:
            debug_frame = frame.copy()
            
            cv2.rectangle(debug_frame,
                (DETECTION_REGION["x1"], DETECTION_REGION["y1"]),
                (DETECTION_REGION["x2"], DETECTION_REGION["y2"]),
                (0, 255, 0), 2)
            
            cv2.rectangle(debug_frame,
                (HOOP_ABOVE_REGION["x1"], HOOP_ABOVE_REGION["y1"]),
                (HOOP_ABOVE_REGION["x2"], HOOP_ABOVE_REGION["y2"]),
                (255, 0, 0), 2)
            
            cv2.rectangle(debug_frame,
                (HOOP_REGION["x1"], HOOP_REGION["y1"]),
                (HOOP_REGION["x2"], HOOP_REGION["y2"]),
                (0, 0, 255), 2)
            
            cv2.circle(debug_frame, (hoop_center_x, hoop_center_y),
                      hoop_radius, (0, 255, 255), 2)
            
            for i, pos in enumerate(ball_positions):
                alpha = (i + 1) / len(ball_positions)
                color = (0, 0, int(255 * alpha))
                cv2.circle(debug_frame, (pos[0], pos[1]), 8, color, -1)
                if i > 0:
                    cv2.line(debug_frame,
                            (ball_positions[i-1][0], ball_positions[i-1][1]),
                            (pos[0], pos[1]), color, 2)
            
            cv2.putText(debug_frame, f"Frame: {frame_index}/{total_frames}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(debug_frame, f"Motion: {motion_ratio:.3f}", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(debug_frame, f"Ball pos: {len(ball_positions)}", (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            cv2.imshow("Debug", debug_frame)
            cv2.waitKey(1)
    
    cap.release()
    
    if DEBUG_MODE:
        cv2.destroyAllWindows()
    
    print("\n" + "="*60)
    print(f"检测完成！共检测到 {len(goal_times)} 个进球")
    print("="*60)
    print()
    
    # 裁剪视频
    print("开始裁剪视频片段...")
    for idx, (t, method) in enumerate(zip(goal_times, goal_methods)):
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
        
        subprocess.run(cmd, capture_output=True)
        print(f"✓ 已生成: {output_file} (时间: {t:.2f}s, 方法: {method})")
    
    # 生成报告
    end_time = time.time()
    total_time = end_time - start_time
    
    report = {
        "video_info": {
            "file": VIDEO_PATH,
            "duration": f"{total_frames/fps:.1f}s",
            "total_frames": total_frames,
            "fps": fps
        },
        "auto_detection": {
            "method": HOOP_DETECTION_METHOD,
            "hoop_center": [hoop_center_x, hoop_center_y],
            "hoop_radius": hoop_radius,
            "detection_region": DETECTION_REGION,
            "hoop_region": HOOP_REGION,
            "hoop_above_region": HOOP_ABOVE_REGION
        },
        "detection_settings": {
            "motion_threshold": MOTION_THRESHOLD,
            "min_continuous_frames": MIN_CONTINUOUS_FRAMES,
            "frame_skip": FRAME_SKIP
        },
        "results": {
            "total_goals": len(goal_times),
            "process_time": datetime.now().isoformat(),
            "execution_seconds": round(total_time, 2),
            "goals": [
                {
                    "index": idx + 1,
                    "timestamp": f"{t:.2f}s",
                    "video_time": f"{int(t//60):02d}:{int(t%60):02d}",
                    "method": method,
                    "output_file": f"goal_{idx+1}.mp4"
                }
                for idx, (t, method) in enumerate(zip(goal_times, goal_methods))
            ]
        }
    }
    
    report_file = f"{OUTPUT_DIR}/report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print("\n" + "="*60)
    print("检测报告")
    print("="*60)
    print(f"处理视频: {VIDEO_PATH}")
    print(f"视频时长: {total_frames/fps:.1f}秒")
    print(f"检测到进球: {len(goal_times)} 个")
    print(f"总耗时: {total_time:.2f} 秒 ({total_time/60:.2f} 分钟)")
    print(f"处理速度: {total_frames/total_time:.1f} FPS")
    print(f"篮筐位置: ({hoop_center_x}, {hoop_center_y}), 半径{hoop_radius}")
    print(f"输出目录: {OUTPUT_DIR}")
    print(f"检测报告: {report_file}")
    print("="*60)
    
    for idx, (t, method) in enumerate(zip(goal_times, goal_methods)):
        video_time = f"{int(t//60):02d}:{int(t%60):02d}"
        print(f"  进球 {idx+1}: {video_time} ({t:.2f}s) - {method}")
    print("="*60)
