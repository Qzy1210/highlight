# Findings & Decisions

## Project Goal (MVP)
在桌面端离线处理固定机位篮球视频，自动导出进球集锦，验证“球经过篮框 + 篮网晃动”的进球识别思路。

## Recommended Stack
- Language: Go 1.22+
- GUI: Fyne
- CV: gocv (OpenCV)
- Video cutting/merge: FFmpeg CLI
- Optional helper: Python scripts only for离线阈值调参与数据分析

## MVP Architecture
1. `ui`：视频导入、篮框 ROI 标定、参数面板、导出配置
2. `pipeline`：逐帧解析、ROI 检测、事件候选生成
3. `detector`：球轨迹检测、篮网晃动检测、进球判定融合
4. `clipper`：按时间窗口切片（例如 -4s 到 +2s）
5. `exporter`：导出单个集锦和多片段文件
6. `storage`：保存项目配置（ROI、阈值、输出模板）

## Core Detection Logic

### Step A: 篮框 ROI
- 首版默认手动框选 ROI（必做）
- 自动识别作为增强项（可后置）

### Step B: 球经过篮框
- 在 ROI 中做运动目标检测（背景差分 + 形态学）
- 用几何规则筛候选球（面积、圆度、速度）
- 跟踪球心轨迹，判定是否“从框上方进入并穿过框中心区域”

### Step C: 篮网晃动
- 在篮网子 ROI 做帧差累计 + 稀疏光流
- 计算晃动分数 `net_score`
- 在球穿框后 0~500ms 时间窗内，若 `net_score` 超阈值则加权通过

### Step D: 进球融合判定
- `score = w1*ball_cross + w2*net_score + w3*post_motion_decay`
- `score >= threshold_goal` 触发进球事件
- 事件去重：2 秒内只保留最高分事件

## Practical Parameters (initial)
- Frame sampling: 25 FPS（先不降采样）
- Goal clip window: `[-4.0s, +2.0s]`
- Event cooldown: 2.0s
- Ball min/max area ratio: 0.0005 ~ 0.02 (相对 ROI)
- Net shake threshold: 经验值起步，按 10~20 段视频标定

## Module Interface Draft
- `DetectGoals(videoPath string, cfg DetectConfig) ([]GoalEvent, error)`
- `CutClips(videoPath string, events []GoalEvent, cfg ClipConfig) ([]string, error)`
- `MergeHighlight(clips []string, output string) error`
- `SaveProjectConfig(path string, cfg ProjectConfig) error`

## 4-Week Roadmap
1. Week 1: GUI + ROI 标定 + 项目保存/加载 + FFmpeg 切片跑通
2. Week 2: 球经过篮框检测（不含篮网），先保证高召回
3. Week 3: 篮网晃动检测 + 融合判定 + 去重
4. Week 4: 阈值调优、批量处理、稳定性测试、打包发布

## Evaluation Plan
- 数据集：固定机位 15~30 场片段，人工标注进球时间点
- 指标：
  - Recall（先保底）：目标 > 90%
  - Precision（MVP 可接受）：目标 > 75%
  - 平均处理速度：>= 0.5x 实时（可离线）
- 输出：误检/漏检清单 + 每个阈值组合结果表

## Risks & Mitigation
- 遮挡严重导致球轨迹断裂：引入短时轨迹补全 + 时间窗融合
- 光照变化导致帧差抖动：ROI 内自适应阈值 + 平滑滤波
- 不同球馆颜色差异：参数配置文件按场地保存

## Decision Summary
| Decision | Why |
|----------|-----|
| 先做传统 CV | 4 周内可验证业务，不依赖标注训练 |
| Go 主实现，Python 辅助 | 复用你的强项，同时保留快速分析能力 |
| 手动 ROI 作为默认流程 | 最大化稳定性，减少前期不确定性 |
| FFmpeg 负责最终剪辑 | 成熟、稳定、生态广 |

---

## 2026-03-20: App 架构评估发现（端侧 vs 云端）

### 平台约束（官方文档）
- iOS：`BGAppRefreshTask` 适合短任务（文档示例提到约 30 秒窗口）；长任务更适合 `BGProcessingTaskRequest`，系统在“最佳时机”调度，执行时机不可强控。
- iOS：`AVAssetExportSession` 可用于系统级视频导出。
- Android：长时后台任务建议用 WorkManager 的 long-running worker，并以前台服务运行；Android 16 对这类任务配额更敏感。
- Android：Media3 `Transformer` 支持常见编辑能力（裁剪、拼接、特效链路）。

### 云端成本结构（官方文档）
- 腾讯云点播（按量计费）包含：媒体处理、媒资管理（存储）、媒体分发播放、客户端上传加速。
- 腾讯云公开了可用于估算的刊例价：例如标准存储（刊例价 0.0048 元/GB，按日峰值计），普通转码按输出规格倍率计费，客户端上传加速按流量计费（示例值 0.48 元/GB）。
- 阿里云视频点播的计费同样按能力拆分：存储、转码、CDN/下行流量、增值能力等，适合按“上传量 + 转码分钟数 + 分发流量”建统一成本模型。

### 结论（用于方案设计）
- 纯端侧：隐私和即时性好，但受设备性能、温升、电量和后台策略影响大，机型一致性难保证。
- 纯云端：稳定可控、易复用现有 Python/FFmpeg 流水线，但上传等待和云成本压力明显。
- 混合架构：端侧先粗剪/预筛，云端做重处理与终稿导出，通常是移动端视频应用更稳妥的首选路线。
