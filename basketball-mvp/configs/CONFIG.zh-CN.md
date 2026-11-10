# 配置参数说明（中文）

本文对应 `configs/pipeline.sample.json`。

## 顶层参数

- `pre_seconds`
  - 含义：每个进球片段向前截取多少秒。
  - 调大：更完整，但视频更长。
- `post_seconds`
  - 含义：每个进球片段向后截取多少秒。
  - 调大：能看到更多后续动作。
- `cooldown_sec`
  - 含义：全局冷却时间（检测和去重时参考）。
  - 调大：重复触发更少；可能漏掉极短间隔连续进球。

## hoop（篮框标定）

- `hoop.cx`
  - 篮框中心 X 坐标（像素）。
- `hoop.cy`
  - 篮框中心 Y 坐标（像素）。
- `hoop.r`
  - 篮框半径（像素）。

说明：这三个参数最关键，错误会直接导致漏检或误检。

## auto_hoop（自动篮框，可开关）

- `enabled`
  - 是否启用 ONNX 自动篮框。
  - `false` 时完全不影响现有手工流程。
- `model_path`
  - ONNX 模型路径（`best.onnx`）。
  - 可写绝对路径；留空时会尝试自动选择最新模型。
- `input_size`
  - 自动篮框推理输入尺寸，通常与训练导出尺寸一致（如 `960`）。
- `conf_threshold`
  - 候选框置信度阈值。
  - 越高越严格，误检少但可能漏检。
- `iou_threshold`
  - NMS 去重阈值。
- `fallback_to_manual`
  - 自动篮框失败时，是否回退到已有 `hoop` 参数继续跑检测。
  - 建议默认 `true`，避免任务直接失败。

## ball_detector（YOLO 球检测，可开关）

- `enabled`
  - 是否启用 YOLO ONNX 球检测。默认 `true`（2026-10-29 起）。
  - 启用后球定位优先走 YOLO 全图检测，对手持/移动机位更鲁棒。
- `model_path`
  - ONNX 模型路径。
  - 留空时自动查找 `models/ball/best.onnx`，再回退到
    `training/ball_detector/runs/*/weights/best.onnx` 中最新的一个。
- `input_size`
  - 推理输入尺寸，必须与导出时一致（当前模型固定 `640`）。
  - 注意：`cv2.dnn` 后端改尺寸会触发 DFL Reshape 报错，不要随意改。
- `conf_threshold`
  - 球检测置信度阈值。实测 `0.15` 可较好平衡手持视频召回。
- `iou_threshold`
  - NMS 去重阈值。
- `fallback_to_mog2`
  - YOLO 未检出时是否回退到 MOG2 背景差分。
  - `true`：召回更高，但会把 MOG2 的误报一并带进来。
  - `false`：只用 YOLO，误报明显更少（实测 IMG_3 由 3 个事件降到 1 个）。

## detect（自动检测参数）

- `frame_skip`
  - 每隔多少帧处理一次。
  - 越大越快，但更容易漏检。建议先用 `1~2`。
- `cooldown_sec`
  - 单次事件的冷却时间。
  - 用于避免一次进球触发多次。
- `min_ball_area` / `max_ball_area`
  - 球体候选轮廓面积范围（像素）。
  - 画面分辨率越高，通常需要更大面积范围。
- `min_ball_circularity`
  - 圆度阈值（0~1）。
  - 越高越严格，误检少但可能漏检。
- `track_len`
  - 轨迹缓冲长度。
  - 越大越平滑，但反应会更慢。
- `net_motion_threshold`
  - 篮网晃动确认阈值。
  - 越高越严格，误检少。
- `net_confirm_window_sec`
  - 球穿框后观察篮网晃动的时间窗。
  - 越大越宽松，召回更高。
- `event_merge_window_sec`
  - 相邻事件去重窗口。
  - 越大越容易把相近事件合并。
- `bg_history`
  - 背景建模历史帧数（MOG2）。
  - 越大越稳定，但对场景变化反应更慢。
- `bg_var_threshold`
  - 背景建模方差阈值。
  - 越大越不敏感，可能漏小运动；越小更敏感，可能误检增多。

## 调参建议（经验）

- 漏检多：
  - 降低 `frame_skip`（例如 2 -> 1）
  - 降低 `net_motion_threshold`
  - 放宽 `min_ball_circularity`
- 误检多：
  - 提高 `min_ball_circularity`
  - 提高 `net_motion_threshold`
  - 提高 `min_ball_area`
