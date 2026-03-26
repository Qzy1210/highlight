#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
篮球进球自动检测与高光视频生成工具

功能：
1. 自动检测篮筐位置（支持多种检测方法）
2. 通过篮球轨迹和篮网晃动检测进球
3. 自动裁剪生成高光视频片段
4. 生成检测报告

作者：Auto-generated
日期：2024
"""

import cv2
import numpy as np
import subprocess
import os
import time
import json
import argparse
from datetime import datetime
from ultralytics import YOLO
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Any


# ============================================================================
# 配置类
# ============================================================================

@dataclass
class VideoConfig:
    """视频处理配置"""
    # 输入输出路径
    input_path: str = "IMG_1556.MOV"  # 输入视频文件路径
    output_dir: str = "highlights"    # 输出目录路径
    
    # 高光片段时间配置
    pre_seconds: int = 8   # 进球前录制的秒数
    post_seconds: int = 2  # 进球后录制的秒数


@dataclass
class DetectionConfig:
    """检测算法配置"""
    # 自动检测参数
    auto_detect_frames: int = 300  # 用于自动检测篮筐的采样帧数
    hoop_detection_method: str = "auto"  # 篮筐检测方法：color/yolo/trajectory/auto/manual
    
    # 运动检测参数
    motion_threshold: float = 0.04      # 运动检测阈值（像素变化比例）
    min_continuous_frames: int = 12     # 最小连续运动帧数（判定进球）
    cooldown_seconds: int = 5           # 进球冷却时间（防止重复检测）
    
    # 篮球检测参数
    ball_confidence: float = 0.5        # YOLO 篮球检测置信度阈值
    ball_tracking_frames: int = 5       # 篮球轨迹追踪帧数
    
    # 性能优化参数
    frame_skip: int = 3  # 帧跳跃间隔（每隔N帧处理一次）


@dataclass
class DebugConfig:
    """调试与可视化配置"""
    debug_mode: bool = False          # 是否启用调试模式（显示实时检测画面）
    enable_progress: bool = True      # 是否显示处理进度
    progress_interval: int = 100      # 进度显示间隔（帧数）


@dataclass
class DetectionRegions:
    """检测区域配置（由自动检测填充）"""
    detection_region: Dict = field(default_factory=dict)   # 总检测区域
    hoop_region: Dict = field(default_factory=dict)        # 篮筐区域
    hoop_above_region: Dict = field(default_factory=dict)  # 篮筐上方区域


# ============================================================================
# 工具函数
# ============================================================================

def simple_dbscan(points: List[Tuple], eps: int = 50, min_samples: int = 5) -> List[int]:
    """
    简化版 DBSCAN 聚类算法（不依赖 sklearn）
    
    用于将检测到的候选篮筐位置进行聚类，找出稳定的篮筐位置。
    
    参数:
        points: 待聚类的点集，每个点为 (x, y) 或 (x, y, radius)
        eps: 邻域半径，距离小于此值的点视为邻居
        min_samples: 核心点所需的最小邻居数
    
    返回:
        labels: 每个点的簇标签，-1 表示噪声点
    """
    n_points = len(points)
    labels = [-1] * n_points
    cluster_id = 0
    
    for i in range(n_points):
        if labels[i] != -1:
            continue
        
        # 找到点 i 的邻居
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
                # 找到 j 的邻居
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


# ============================================================================
# 篮筐检测模块
# ============================================================================

class HoopDetector:
    """篮筐检测器：支持多种检测方法"""
    
    def __init__(self, video_path: str, sample_frames: int = 300):
        """
        初始化篮筐检测器
        
        参数:
            video_path: 视频文件路径
            sample_frames: 采样帧数
        """
        self.video_path = video_path
        self.sample_frames = sample_frames
    
    def detect(self, method: str = "auto") -> Optional[Tuple[int, int, int]]:
        """
        检测篮筐位置
        
        参数:
            method: 检测方法 (color/yolo/trajectory/auto/manual)
        
        返回:
            (center_x, center_y, radius) 或 None
        """
        hoop_location = None
        
        # 方法1: 增强版颜色检测（最可靠）
        if method in ["color", "auto"]:
            hoop_location = self.detect_by_color_enhanced()
            if hoop_location:
                print(f"✅ 使用增强版颜色检测法成功")
                return hoop_location
        
        # 方法2: YOLO 篮球轨迹聚类
        if method in ["yolo", "auto"] and not hoop_location:
            try:
                hoop_location = self.detect_by_yolo()
                if hoop_location:
                    print(f"✅ 使用YOLO推断法成功")
                    return hoop_location
            except Exception as e:
                print(f"⚠️  YOLO推断法失败: {e}")
        
        # 方法3: 轨迹分析
        if method in ["trajectory", "auto"] and not hoop_location:
            try:
                hoop_location = self.detect_by_trajectory()
                if hoop_location:
                    print(f"✅ 使用轨迹分析法成功")
                    return hoop_location
            except Exception as e:
                print(f"⚠️  轨迹分析法失败: {e}")
        
        # 方法4: 手动标注（兜底方案）
        if not hoop_location:
            print("\n⚠️  自动检测失败，启动手动标注")
            hoop_location = self.manual_selection()
        
        return hoop_location
    
    def detect_by_color_enhanced(self) -> Optional[Tuple[int, int, int]]:
        """
        增强版篮筐检测：颜色 + 霍夫圆 + 边缘特征融合
        
        通过多种图像处理方法检测篮筐位置，并对结果进行融合验证。
        
        返回:
            (center_x, center_y, radius) 或 None
        """
        print("🔍 方法1: 增强版颜色检测 - 颜色 + 霍夫圆 + 边缘特征融合...")
        
        cap = cv2.VideoCapture(self.video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        sample_interval = max(1, total_frames // self.sample_frames)
        
        hoop_candidates = []  # 存储所有候选篮筐
        frame_count = 0
        
        print(f"  视频分辨率: {frame_width}x{frame_height}")
        print(f"  采样帧数: {self.sample_frames}, 间隔: {sample_interval}")
        
        while frame_count < self.sample_frames:
            ret, frame = cap.read()
            if not ret:
                break
                
            frame_count += 1
            if frame_count % sample_interval != 0:
                continue
            
            # 方法1: 多颜色检测
            color_candidates = self._detect_by_multiple_colors(frame)
            
            # 方法2: 霍夫圆检测
            hough_candidates = self._detect_by_hough_circles(frame)
            
            # 方法3: 边缘特征检测
            edge_candidates = self._detect_by_edge_features(frame)
            
            # 融合候选结果
            all_candidates = color_candidates + hough_candidates + edge_candidates
            
            # 对候选结果进行聚类和验证
            if all_candidates:
                validated = self._validate_and_merge_candidates(
                    all_candidates, frame_width, frame_height
                )
                hoop_candidates.extend(validated)
        
        cap.release()
        
        # 统计分析
        if len(hoop_candidates) > self.sample_frames * 0.05:  # 至少5%的帧检测到
            result = self._analyze_hoop_candidates(hoop_candidates, frame_width, frame_height)
            if result:
                print(f"✅ 检测到篮筐位置: 中心({result[0]}, {result[1]}), 半径{result[2]}")
                return result
        
        print("⚠️  增强检测法未找到稳定篮筐位置")
        return None
    
    def _detect_by_multiple_colors(self, frame: np.ndarray) -> List[Tuple]:
        """
        多颜色检测：橙色、红色、黄色
        
        篮筐可能呈现多种颜色，通过多颜色检测提高召回率。
        """
        candidates = []
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # 定义多个颜色范围（HSV空间）
        color_ranges = [
            ([10, 80, 80], [25, 255, 255], "orange"),   # 橙色
            ([0, 80, 80], [10, 255, 255], "red1"),      # 红色范围1
            ([170, 80, 80], [180, 255, 255], "red2"),   # 红色范围2
            ([26, 80, 80], [35, 255, 255], "yellow"),   # 黄色
        ]
        
        for lower, upper, color_name in color_ranges:
            lower = np.array(lower)
            upper = np.array(upper)
            mask = cv2.inRange(hsv, lower, upper)
            
            # 形态学操作：去除噪声
            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            
            # 查找轮廓
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for contour in contours:
                area = cv2.contourArea(contour)
                # 面积范围：30-30000，适应远距离拍摄
                if 30 < area < 30000:
                    (x, y), radius = cv2.minEnclosingCircle(contour)
                    radius = int(radius)
                    
                    # 验证圆形度
                    circularity = area / (np.pi * radius * radius) if radius > 0 else 0
                    if 0.3 < circularity < 1.5:
                        candidates.append((int(x), int(y), radius, "color", color_name))
        
        return candidates
    
    def _detect_by_hough_circles(self, frame: np.ndarray) -> List[Tuple]:
        """
        霍夫圆检测：寻找圆形篮筐
        
        利用霍夫变换检测图像中的圆形结构。
        """
        candidates = []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # 高斯模糊：减少噪声干扰
        blurred = cv2.GaussianBlur(gray, (9, 9), 2)
        
        # 霍夫圆检测参数
        height, width = gray.shape
        min_radius = int(min(width, height) * 0.02)   # 最小半径：图像短边的2%
        max_radius = int(min(width, height) * 0.15)   # 最大半径：图像短边的15%
        
        circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp=1,
            minDist=50,
            param1=50,   # Canny边缘检测高阈值
            param2=30,   # 累加器阈值（越小检测到越多圆）
            minRadius=min_radius,
            maxRadius=max_radius
        )
        
        if circles is not None:
            circles = np.uint16(np.around(circles))
            for circle in circles[0]:
                x, y, radius = circle
                candidates.append((int(x), int(y), int(radius), "hough", "circle"))
        
        return candidates
    
    def _detect_by_edge_features(self, frame: np.ndarray) -> List[Tuple]:
        """
        边缘特征检测：利用 Canny 边缘检测
        
        通过边缘检测和轮廓分析寻找篮筐结构。
        """
        candidates = []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Canny 边缘检测
        edges = cv2.Canny(gray, 50, 150)
        
        # 形态学操作：连接断开的边缘
        kernel = np.ones((5, 5), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)
        edges = cv2.erode(edges, kernel, iterations=1)
        
        # 查找轮廓
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > 100:
                # 最小外接圆
                (x, y), radius = cv2.minEnclosingCircle(contour)
                radius = int(radius)
                
                if radius > 10:
                    candidates.append((int(x), int(y), radius, "edge", "contour"))
        
        return candidates
    
    def _validate_and_merge_candidates(
        self, 
        candidates: List[Tuple], 
        frame_width: int, 
        frame_height: int
    ) -> List[Tuple]:
        """
        验证并合并候选结果
        
        过滤掉不合理的候选篮筐位置。
        """
        validated = []
        
        for x, y, radius, method, detail in candidates:
            # 位置验证：篮筐通常在视频上半部分
            if y > frame_height * 0.7:
                continue
            
            # 半径验证：合理的篮筐大小
            if radius < 10 or radius > frame_height * 0.2:
                continue
            
            # 边缘验证：不超出画面
            if x - radius < 0 or x + radius > frame_width:
                continue
            if y - radius < 0 or y + radius > frame_height:
                continue
            
            validated.append((x, y, radius))
        
        return validated
    
    def _analyze_hoop_candidates(
        self, 
        candidates: List[Tuple], 
        frame_width: int, 
        frame_height: int
    ) -> Optional[Tuple[int, int, int]]:
        """
        分析候选篮筐，找出最稳定的位置
        
        使用 DBSCAN 聚类找出最频繁出现的篮筐位置。
        """
        if len(candidates) < 10:
            return None
        
        points = [(c[0], c[1]) for c in candidates]
        labels = simple_dbscan(points, eps=50, min_samples=10)
        
        # 统计各簇的大小
        cluster_counts = {}
        cluster_positions = {}
        
        for i, label in enumerate(labels):
            if label == -1:
                continue
            if label not in cluster_counts:
                cluster_counts[label] = 0
                cluster_positions[label] = []
            cluster_counts[label] += 1
            cluster_positions[label].append(candidates[i])
        
        if not cluster_counts:
            return None
        
        # 找到最大的簇
        max_cluster = max(cluster_counts.keys(), key=lambda k: cluster_counts[k])
        positions = cluster_positions[max_cluster]
        
        # 计算平均位置
        avg_x = int(np.mean([p[0] for p in positions]))
        avg_y = int(np.mean([p[1] for p in positions]))
        avg_radius = int(np.mean([p[2] for p in positions]))
        
        return (avg_x, avg_y, avg_radius)
    
    def detect_by_yolo(self) -> Optional[Tuple[int, int, int]]:
        """
        YOLO 推断法：检测篮球轨迹推断篮筐位置
        
        通过 YOLO 检测篮球位置，使用聚类分析找出篮球聚集区域（篮筐）。
        """
        print("🔍 方法2: YOLO推断法 - 检测篮球轨迹推断篮筐...")
        
        model = YOLO("yolov8n.pt")
        cap = cv2.VideoCapture(self.video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        sample_interval = max(1, total_frames // self.sample_frames)
        
        ball_positions = []
        frame_count = 0
        
        while frame_count < self.sample_frames:
            ret, frame = cap.read()
            if not ret:
                break
                
            frame_count += 1
            if frame_count % sample_interval != 0:
                continue
            
            # 检测篮球（COCO dataset: sports ball = class 32)
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
    
    def detect_by_trajectory(self) -> Optional[Tuple[int, int, int]]:
        """
        轨迹分析法：通过篮球下落轨迹分析篮筐位置
        
        通过追踪篮球的下落轨迹，找到篮球消失的位置（篮筐）。
        """
        print("🔍 方法3: 轨迹分析法 - 分析篮球下落轨迹...")
        
        model = YOLO("yolov8n.pt")
        cap = cv2.VideoCapture(self.video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        sample_interval = max(1, total_frames // self.sample_frames)
        
        ball_trajectories = []
        current_trajectory = []
        
        frame_count = 0
        prev_y = None
        
        while frame_count < self.sample_frames:
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
            print("⚠️  轨迹分析法未找到足够的篮球轨迹")
            return None
        
        # 分析轨迹终点
        end_points = [traj[-1] for traj in ball_trajectories if len(traj) >= 3]
        
        if len(end_points) < 3:
            print("⚠️  未找到足够的轨迹终点")
            return None
        
        # 聚类分析终点
        labels = simple_dbscan(end_points, eps=100, min_samples=3)
        
        # 找到最大的簇
        unique_labels = set(labels) - {-1}
        if not unique_labels:
            print("⚠️  未找到明显的轨迹终点聚集区域")
            return None
        
        largest_cluster_label = max(unique_labels, key=lambda l: labels.count(l))
        cluster_points = [end_points[i] for i in range(len(end_points)) if labels[i] == largest_cluster_label]
        
        center_x = int(np.mean([p[0] for p in cluster_points]))
        center_y = int(np.mean([p[1] for p in cluster_points]))
        
        distances = [np.sqrt((p[0] - center_x)**2 + (p[1] - center_y)**2) for p in cluster_points]
        radius = int(np.percentile(distances, 80))
        
        print(f"✅ 检测到篮筐位置（基于轨迹分析）: 中心({center_x}, {center_y}), 半径{radius}")
        return (center_x, center_y, radius)
    
    def manual_selection(self) -> Optional[Tuple[int, int, int]]:
        """
        手动标注法：通过鼠标选择篮筐位置
        
        打开视频第一帧，让用户用鼠标框选篮筐区域。
        """
        print("🖱️  方法4: 手动标注 - 请在视频窗口中框选篮筐")
        print("  操作说明：")
        print("    - 鼠标左键拖动：绘制矩形框")
        print("    - 'c'：确认选择")
        print("    - 'r'：重置选择")
        print("    - 'q'：取消退出")
        
        cap = cv2.VideoCapture(self.video_path)
        
        # 跳到视频中间帧
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        middle_frame = total_frames // 2
        cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame)
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            print("⚠️  无法读取视频帧")
            return None
        
        selection = {'rect': None, 'confirmed': False}
        
        def mouse_callback(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN:
                selection['start'] = (x, y)
                selection['end'] = None
            elif event == cv2.EVENT_MOUSEMOVE and 'start' in selection:
                selection['end'] = (x, y)
            elif event == cv2.EVENT_LBUTTONUP and 'start' in selection:
                selection['end'] = (x, y)
        
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


# ============================================================================
# 检测区域管理
# ============================================================================

class RegionManager:
    """检测区域管理器：根据篮筐位置设置各个检测区域"""
    
    @staticmethod
    def setup_regions(
        hoop_center_x: int, 
        hoop_center_y: int, 
        hoop_radius: int
    ) -> DetectionRegions:
        """
        根据篮筐位置设置检测区域
        
        参数:
            hoop_center_x: 篮筐中心X坐标
            hoop_center_y: 篮筐中心Y坐标
            hoop_radius: 篮筐半径
        
        返回:
            DetectionRegions: 检测区域配置对象
        """
        regions = DetectionRegions()
        
        # 篮筐区域
        regions.hoop_region = {
            "x1": hoop_center_x - hoop_radius,
            "y1": hoop_center_y - hoop_radius // 2,
            "x2": hoop_center_x + hoop_radius,
            "y2": hoop_center_y + hoop_radius
        }
        
        # 篮筐上方区域
        regions.hoop_above_region = {
            "x1": hoop_center_x - hoop_radius * 2,
            "y1": hoop_center_y - hoop_radius * 4,
            "x2": hoop_center_x + hoop_radius * 2,
            "y2": hoop_center_y - hoop_radius
        }
        
        # YOLO检测区域
        regions.detection_region = {
            "x1": hoop_center_x - hoop_radius * 3,
            "y1": hoop_center_y - hoop_radius * 5,
            "x2": hoop_center_x + hoop_radius * 3,
            "y2": hoop_center_y + hoop_radius * 2
        }
        
        print("\n" + "="*60)
        print("自动设置检测区域:")
        print("="*60)
        print(f"篮筐区域: {regions.hoop_region}")
        print(f"篮筐上方区域: {regions.hoop_above_region}")
        print(f"YOLO检测区域: {regions.detection_region}")
        print("="*60)
        
        return regions
    
    @staticmethod
    def save_debug_images(
        video_path: str,
        regions: DetectionRegions
    ) -> None:
        """
        保存检测区域的调试图片
        
        参数:
            video_path: 视频文件路径
            regions: 检测区域配置
        """
        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        middle_frame = total_frames // 2
        cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame)
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return
        
        # 创建副本用于绘制
        debug_frame = frame.copy()
        
        # 绘制篮筐区域（红色）
        cv2.rectangle(debug_frame,
                     (regions.hoop_region["x1"], regions.hoop_region["y1"]),
                     (regions.hoop_region["x2"], regions.hoop_region["y2"]),
                     (0, 0, 255), 2)
        cv2.putText(debug_frame, "Hoop Region",
                   (regions.hoop_region["x1"], regions.hoop_region["y1"] - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1)
        
        # 绘制篮筐上方区域（蓝色）
        cv2.rectangle(debug_frame,
                     (regions.hoop_above_region["x1"], regions.hoop_above_region["y1"]),
                     (regions.hoop_above_region["x2"], regions.hoop_above_region["y2"]),
                     (255, 0, 0), 2)
        cv2.putText(debug_frame, "Hoop Above Region",
                   (regions.hoop_above_region["x1"], regions.hoop_above_region["y1"] - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 1)
        
        # 绘制YOLO检测区域（绿色）
        cv2.rectangle(debug_frame,
                     (regions.detection_region["x1"], regions.detection_region["y1"]),
                     (regions.detection_region["x2"], regions.detection_region["y2"]),
                     (0, 255, 0), 2)
        cv2.putText(debug_frame, "Detection Region",
                   (regions.detection_region["x1"], regions.detection_region["y1"] - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
        
        # 保存各区域图片
        cv2.imwrite("hoop_region.jpg", 
                   debug_frame[regions.hoop_region["y1"]:regions.hoop_region["y2"], 
                              regions.hoop_region["x1"]:regions.hoop_region["x2"]])
        cv2.imwrite("hoop_above_region.jpg", 
                   debug_frame[regions.hoop_above_region["y1"]:regions.hoop_above_region["y2"], 
                              regions.hoop_above_region["x1"]:regions.hoop_above_region["x2"]])
        cv2.imwrite("detection_region.jpg", 
                   debug_frame[regions.detection_region["y1"]:regions.detection_region["y2"], 
                              regions.detection_region["x1"]:regions.detection_region["x2"]])
        
        # 保存包含所有区域的完整帧
        cv2.imwrite("all_detection_regions.jpg", debug_frame)
        print("✅ 已保存检测区域调试图片")


# ============================================================================
# 进球检测器
# ============================================================================

class GoalDetector:
    """进球检测器：结合篮球轨迹和篮网晃动检测进球"""
    
    def __init__(
        self,
        regions: DetectionRegions,
        detection_config: DetectionConfig,
        debug_config: DebugConfig
    ):
        """
        初始化进球检测器
        
        参数:
            regions: 检测区域配置
            detection_config: 检测算法配置
            debug_config: 调试配置
        """
        self.regions = regions
        self.config = detection_config
        self.debug_config = debug_config
        
        # YOLO模型
        self.model = YOLO("yolov8n.pt")
        
        # 状态变量
        self.ball_positions = []
        self.prev_gray = None
        self.motion_count = 0
        self.cooldown = 0
        
        # 检测结果
        self.goal_times = []
        self.goal_methods = []
    
    def process_frame(
        self, 
        frame: np.ndarray, 
        frame_index: int, 
        current_time: float
    ) -> bool:
        """
        处理单帧视频
        
        参数:
            frame: 视频帧
            frame_index: 帧索引
            current_time: 当前时间（秒）
        
        返回:
            bool: 是否检测到进球
        """
        # 冷却期处理
        if self.cooldown > 0:
            self.cooldown -= 1
            self.ball_positions.clear()
            return False
        
        # ROI裁剪 + YOLO检测
        detection_roi = frame[
            self.regions.detection_region["y1"]:self.regions.detection_region["y2"],
            self.regions.detection_region["x1"]:self.regions.detection_region["x2"]
        ]
        
        ball_detected = False
        goal_detected = False
        
        # 篮球检测
        results = self.model(detection_roi, classes=[32], verbose=False, conf=self.config.ball_confidence)
        
        for r in results:
            for box in r.boxes:
                if float(box.conf[0]) > self.config.ball_confidence:
                    x1, y1, x2, y2 = box.xyxy[0]
                    
                    # 转换为全局坐标
                    global_x = int((x1 + x2) / 2) + self.regions.detection_region["x1"]
                    global_y = int((y1 + y2) / 2) + self.regions.detection_region["y1"]
                    
                    # 检查是否在篮筐上方区域
                    if (self.regions.hoop_above_region["x1"] < global_x < self.regions.hoop_above_region["x2"] and
                        self.regions.hoop_above_region["y1"] < global_y < self.regions.hoop_above_region["y2"]):
                        
                        ball_detected = True
                        self.ball_positions.append((global_x, global_y))
                        
                        # 保持固定长度的轨迹
                        if len(self.ball_positions) > self.config.ball_tracking_frames:
                            self.ball_positions.pop(0)
                        
                        # 检测篮球是否进入篮筐区域
                        if (self.regions.hoop_region["x1"] < global_x < self.regions.hoop_region["x2"] and
                            self.regions.hoop_region["y1"] < global_y < self.regions.hoop_region["y2"]):
                            
                            # 检查轨迹是否向下
                            if len(self.ball_positions) >= 3:
                                y_positions = [p[1] for p in self.ball_positions]
                                if y_positions[-1] > y_positions[0]:
                                    goal_detected = True
        
        # 运动检测（篮网晃动）
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        if self.prev_gray is not None:
            diff = cv2.absdiff(self.prev_gray, gray)
            _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            
            motion_ratio = np.sum(thresh > 0) / thresh.size
            
            if motion_ratio > self.config.motion_threshold:
                self.motion_count += 1
            else:
                self.motion_count = 0
        else:
            motion_ratio = 0
        
        self.prev_gray = gray
        
        # 进球判定
        detection_method = ""
        if self.motion_count >= self.config.min_continuous_frames or goal_detected:
            if goal_detected:
                detection_method = "篮球轨迹"
            else:
                detection_method = "篮网晃动"
            
            print(f"✓ 进球检测！时间: {current_time:.2f}s (方法: {detection_method})")
            self.goal_times.append(current_time)
            self.goal_methods.append(detection_method)
            self.cooldown = int(30 * self.config.cooldown_seconds)  # 假设30fps
            self.motion_count = 0
            self.ball_positions.clear()
            
            return True
        
        # 调试可视化
        if self.debug_config.debug_mode:
            self._draw_debug_info(frame, frame_index, motion_ratio)
        
        return False
    
    def _draw_debug_info(self, frame: np.ndarray, frame_index: int, motion_ratio: float):
        """绘制调试信息"""
        debug_frame = frame.copy()
        
        # 绘制检测区域
        cv2.rectangle(debug_frame,
            (self.regions.detection_region["x1"], self.regions.detection_region["y1"]),
            (self.regions.detection_region["x2"], self.regions.detection_region["y2"]),
            (0, 255, 0), 2)
        
        cv2.rectangle(debug_frame,
            (self.regions.hoop_above_region["x1"], self.regions.hoop_above_region["y1"]),
            (self.regions.hoop_above_region["x2"], self.regions.hoop_above_region["y2"]),
            (255, 0, 0), 2)
        
        cv2.rectangle(debug_frame,
            (self.regions.hoop_region["x1"], self.regions.hoop_region["y1"]),
            (self.regions.hoop_region["x2"], self.regions.hoop_region["y2"]),
            (0, 0, 255), 2)
        
        # 绘制篮球轨迹
        for i, pos in enumerate(self.ball_positions):
            alpha = (i + 1) / len(self.ball_positions)
            color = (0, 0, int(255 * alpha))
            cv2.circle(debug_frame, (pos[0], pos[1]), 8, color, -1)
            if i > 0:
                cv2.line(debug_frame,
                        (self.ball_positions[i-1][0], self.ball_positions[i-1][1]),
                        (pos[0], pos[1]), color, 2)
        
        # 绘制文本信息
        cv2.putText(debug_frame, f"Frame: {frame_index}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(debug_frame, f"Motion: {motion_ratio:.3f}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(debug_frame, f"Ball pos: {len(self.ball_positions)}", (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        cv2.imshow("Debug", debug_frame)
        cv2.waitKey(1)


# ============================================================================
# 视频处理器
# ============================================================================

class VideoProcessor:
    """视频处理器：处理视频并生成高光片段"""
    
    def __init__(
        self,
        video_config: VideoConfig,
        detection_config: DetectionConfig,
        debug_config: DebugConfig
    ):
        """
        初始化视频处理器
        
        参数:
            video_config: 视频配置
            detection_config: 检测配置
            debug_config: 调试配置
        """
        self.video_config = video_config
        self.detection_config = detection_config
        self.debug_config = debug_config
    
    def process(self) -> Tuple[List[float], List[str], int, float]:
        """
        处理视频，检测进球
        
        返回:
            (goal_times, goal_methods, total_frames, fps)
        """
        # 检测篮筐位置
        detector = HoopDetector(
            self.video_config.input_path, 
            self.detection_config.auto_detect_frames
        )
        
        hoop_location = detector.detect(self.detection_config.hoop_detection_method)
        
        if not hoop_location:
            print("\n❌ 未能确定篮筐位置，程序退出")
            return [], [], 0, 0.0
        
        hoop_center_x, hoop_center_y, hoop_radius = hoop_location
        
        # 设置检测区域
        regions = RegionManager.setup_regions(hoop_center_x, hoop_center_y, hoop_radius)
        
        # 保存调试图片
        RegionManager.save_debug_images(self.video_config.input_path, regions)
        
        # 创建进球检测器
        goal_detector = GoalDetector(regions, self.detection_config, self.debug_config)
        
        # 打开视频
        cap = cv2.VideoCapture(self.video_config.input_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        frame_index = 0
        start_time = time.time()
        
        print("\n" + "="*60)
        print("篮球进球检测系统启动")
        print("="*60)
        print(f"视频文件: {self.video_config.input_path}")
        print(f"视频时长: {total_frames/fps:.1f}秒 ({total_frames} 帧)")
        print(f"帧率: {fps:.1f} FPS")
        print(f"自动检测篮筐: ({hoop_center_x}, {hoop_center_y}), 半径{hoop_radius}")
        print(f"调试模式: {'开启' if self.debug_config.debug_mode else '关闭'}")
        print("="*60)
        print()
        
        # 创建输出目录
        if not os.path.exists(self.video_config.output_dir):
            os.makedirs(self.video_config.output_dir)
        
        # 处理视频
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            frame_index += 1
            current_time = frame_index / fps
            
            # 进度显示
            if self.debug_config.enable_progress and frame_index % self.debug_config.progress_interval == 0:
                progress = frame_index / total_frames * 100
                elapsed = time.time() - start_time
                eta = elapsed / frame_index * (total_frames - frame_index)
                print(f"📊 处理进度: {progress:.1f}% ({frame_index}/{total_frames}) | "
                      f"已用时: {elapsed:.1f}s | 预计剩余: {eta:.1f}s")
            
            # 跳帧处理
            if frame_index % self.detection_config.frame_skip != 0:
                continue
            
            # 检测进球
            goal_detector.process_frame(frame, frame_index, current_time)
        
        cap.release()
        
        if self.debug_config.debug_mode:
            cv2.destroyAllWindows()
        
        print("\n" + "="*60)
        print(f"检测完成！共检测到 {len(goal_detector.goal_times)} 个进球")
        print("="*60)
        print()
        
        return goal_detector.goal_times, goal_detector.goal_methods, total_frames, fps
    
    def generate_clips(self, goal_times: List[float], goal_methods: List[str]):
        """
        生成高光视频片段
        
        参数:
            goal_times: 进球时间列表
            goal_methods: 进球检测方法列表
        """
        print("开始裁剪视频片段...")
        
        for idx, (t, method) in enumerate(zip(goal_times, goal_methods)):
            start = max(t - self.video_config.pre_seconds, 0)
            end = t + self.video_config.post_seconds
            
            output_file = f"{self.video_config.output_dir}/goal_{idx+1}.mp4"
            
            cmd = [
                "ffmpeg",
                "-y",
                "-ss", str(start),
                "-to", str(end),
                "-i", self.video_config.input_path,
                "-c", "copy",
                output_file
            ]
            
            subprocess.run(cmd, capture_output=True)
            print(f"✓ 已生成: {output_file} (时间: {t:.2f}s, 方法: {method})")


# ============================================================================
# 报告生成器
# ============================================================================

class ReportGenerator:
    """报告生成器：生成检测报告"""
    
    @staticmethod
    def generate(
        video_config: VideoConfig,
        detection_config: DetectionConfig,
        regions: DetectionRegions,
        goal_times: List[float],
        goal_methods: List[str],
        total_frames: int,
        fps: float,
        execution_time: float,
        hoop_location: Tuple[int, int, int]
    ):
        """
        生成检测报告
        
        参数:
            video_config: 视频配置
            detection_config: 检测配置
            regions: 检测区域
            goal_times: 进球时间列表
            goal_methods: 进球检测方法列表
            total_frames: 总帧数
            fps: 帧率
            execution_time: 执行时间（秒）
            hoop_location: 篮筐位置 (x, y, radius)
        """
        hoop_center_x, hoop_center_y, hoop_radius = hoop_location
        
        report = {
            "video_info": {
                "file": video_config.input_path,
                "duration": f"{total_frames/fps:.1f}s",
                "total_frames": total_frames,
                "fps": fps
            },
            "auto_detection": {
                "method": detection_config.hoop_detection_method,
                "hoop_center": [hoop_center_x, hoop_center_y],
                "hoop_radius": hoop_radius,
                "detection_region": regions.detection_region,
                "hoop_region": regions.hoop_region,
                "hoop_above_region": regions.hoop_above_region
            },
            "detection_settings": {
                "motion_threshold": detection_config.motion_threshold,
                "min_continuous_frames": detection_config.min_continuous_frames,
                "frame_skip": detection_config.frame_skip
            },
            "results": {
                "total_goals": len(goal_times),
                "process_time": datetime.now().isoformat(),
                "execution_seconds": round(execution_time, 2),
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
        
        report_file = f"{video_config.output_dir}/report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        # 打印报告摘要
        print("\n" + "="*60)
        print("检测报告")
        print("="*60)
        print(f"处理视频: {video_config.input_path}")
        print(f"视频时长: {total_frames/fps:.1f}秒")
        print(f"检测到进球: {len(goal_times)} 个")
        print(f"总耗时: {execution_time:.2f} 秒 ({execution_time/60:.2f} 分钟)")
        print(f"处理速度: {total_frames/execution_time:.1f} FPS")
        print(f"篮筐位置: ({hoop_center_x}, {hoop_center_y}), 半径{hoop_radius}")
        print(f"输出目录: {video_config.output_dir}")
        print(f"检测报告: {report_file}")
        print("="*60)
        
        for idx, (t, method) in enumerate(zip(goal_times, goal_methods)):
            video_time = f"{int(t//60):02d}:{int(t%60):02d}"
            print(f"  进球 {idx+1}: {video_time} ({t:.2f}s) - {method}")
        print("="*60)


# ============================================================================
# 主程序
# ============================================================================

def main():
    """主函数：解析命令行参数并执行检测"""
    parser = argparse.ArgumentParser(description="篮球进球自动检测与高光视频生成工具")
    
    # 视频参数
    parser.add_argument("--input", "-i", type=str, default="IMG_1556.MOV",
                       help="输入视频文件路径")
    parser.add_argument("--output", "-o", type=str, default="highlights",
                       help="输出目录路径")
    parser.add_argument("--pre-seconds", type=int, default=8,
                       help="进球前录制的秒数")
    parser.add_argument("--post-seconds", type=int, default=2,
                       help="进球后录制的秒数")
    
    # 检测参数
    parser.add_argument("--auto-detect-frames", type=int, default=300,
                       help="自动检测篮筐的采样帧数")
    parser.add_argument("--hoop-detection-method", type=str, default="auto",
                       choices=["color", "yolo", "trajectory", "auto", "manual"],
                       help="篮筐检测方法")
    parser.add_argument("--motion-threshold", type=float, default=0.04,
                       help="运动检测阈值")
    parser.add_argument("--min-continuous-frames", type=int, default=12,
                       help="最小连续运动帧数")
    parser.add_argument("--cooldown-seconds", type=int, default=5,
                       help="进球冷却时间（秒）")
    parser.add_argument("--ball-confidence", type=float, default=0.5,
                       help="YOLO篮球检测置信度阈值")
    parser.add_argument("--frame-skip", type=int, default=3,
                       help="帧跳跃间隔")
    
    # 调试参数
    parser.add_argument("--debug", action="store_true",
                       help="启用调试模式")
    parser.add_argument("--no-progress", action="store_true",
                       help="禁用进度显示")
    
    args = parser.parse_args()
    
    # 创建配置对象
    video_config = VideoConfig(
        input_path=args.input,
        output_dir=args.output,
        pre_seconds=args.pre_seconds,
        post_seconds=args.post_seconds
    )
    
    detection_config = DetectionConfig(
        auto_detect_frames=args.auto_detect_frames,
        hoop_detection_method=args.hoop_detection_method,
        motion_threshold=args.motion_threshold,
        min_continuous_frames=args.min_continuous_frames,
        cooldown_seconds=args.cooldown_seconds,
        ball_confidence=args.ball_confidence,
        frame_skip=args.frame_skip
    )
    
    debug_config = DebugConfig(
        debug_mode=args.debug,
        enable_progress=not args.no_progress
    )
    
    # 执行处理
    start_time = time.time()
    
    processor = VideoProcessor(video_config, detection_config, debug_config)
    goal_times, goal_methods, total_frames, fps = processor.process()
    
    if goal_times:
        processor.generate_clips(goal_times, goal_methods)
        
        # 获取检测区域（用于报告）
        detector = HoopDetector(video_config.input_path, detection_config.auto_detect_frames)
        hoop_location = detector.detect(detection_config.hoop_detection_method)
        
        regions = RegionManager.setup_regions(*hoop_location)
        
        # 生成报告
        execution_time = time.time() - start_time
        ReportGenerator.generate(
            video_config, detection_config, regions,
            goal_times, goal_methods,
            total_frames, fps, execution_time, hoop_location
        )


if __name__ == "__main__":
    main()
