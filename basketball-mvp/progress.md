# Progress Log

## Session: 2026-10-29（球检测默认启用 + 模型入库 + 端到端验证）

### 目标
上一轮训练的 YOLO 球检测模型虽已接入代码，但 `ball_detector.enabled=false`，
桌面端实际仍走纯 MOG2。本轮把模型真正接入默认链路并做端到端验证。

### 变更
- 新增 `models/ball/best.onnx`（来自 `training/ball_detector/runs/ball_v1_n/weights/best.onnx`）。
- 新增 `models/hoop/best.onnx`（此前只存在于 `dist/` 打包产物中，源码树缺失，
  导致源码运行时 `auto hoop model not found`）。
  - `models/` 不在 `.gitignore` 中，两个模型现已可入库、可复现。
- `configs/pipeline.sample.json`：`ball_detector.enabled` 由 `false` 改为 `true`。
- `scripts/build_macos_app.sh`：`copy_auto_hoop_model` 泛化为 `copy_detector_model`，
  优先取 `models/<kind>/best.onnx`，其次回退训练目录，hoop 与 ball 各拷一份。
- `scripts/build_windows_app.ps1`：此前**完全没有拷贝任何模型**，现补齐 hoop/ball 拷贝。
- `configs/CONFIG.zh-CN.md`：补充 `ball_detector` 参数说明。
- `README.md`：功能总览与项目结构补充 YOLO 球检测与 `models/` 目录。

### 验证（macOS arm64，venv Python 3.13 + cv2 4.13）
- `go build ./...` 通过；`python3 -m py_compile engine-py/detect_goals.py` 通过。
- `bash -n scripts/build_macos_app.sh` 通过；实跑打包成功，
  两个模型均出现在 `.app/Contents/Resources/project/models/{hoop,ball}/best.onnx`。
- 模型自动发现：
  - `_discover_default_ball_model()` → `models/ball/best.onnx`
  - `_discover_default_auto_hoop_model()` → `models/hoop/best.onnx`
- 自动篮框检测（此前源码环境直接 400）：`POST /api/v1/hoop/detect` 返回
  `status=multiple`，真篮框候选 `cx=863 cy=321 r=35 score=0.461` 排第一。
  但 4 条视频实测质量不稳：371be0 全部误检、1165 完全漏检，仍需人工确认。
- 端到端单任务（IMG_3，hoop=863/321/35）：
  - `POST /api/v1/single-job/start` → 产出 `goals.json` + `highlight.mp4`（6.3MB）。
  - `goals.json` 中 `ball_detector.status=ok`、`model_path` 指向 `models/ball/best.onnx`。
  - 事件 3 个：65.67s / 80.80s / 102.13s。

### 关键实测结论（MOG2 vs YOLO）

人工逐帧核对（放大到篮框区域，逐 0.1~0.2s 取帧）建立 IMG_3 真值：
真实进球 5 个 —— 65.7 / 80.9 / 92.15 / 102.15 / 113.2 秒。
真值已落盘：`workspace/truth/IMG_3.truth.json`。

| 模式 | 检出 | TP | FP | FN | 精确率 | 召回率 | F1 | 耗时 |
|------|------|----|----|----|--------|--------|----|------|
| 纯 MOG2 | 3 | 3 | 0 | 2 | 1.00 | 0.60 | 0.75 | 14.9s |
| YOLO + MOG2 兜底 | 3 | 3 | 0 | 2 | 1.00 | 0.60 | 0.75 | 103.9s |
| 纯 YOLO（不回退） | 1 | 1 | 0 | 4 | 1.00 | 0.20 | 0.33 | 116.8s |

- 三种模式在这条视频上**都没有误报**，短板是**漏检**，不是误报。
  （上一版记录里“另 2 个是 MOG2 误报”的结论是错的，已更正。）
- 纯 YOLO 把召回从 0.60 拉到 0.20，因此 `fallback_to_mog2` **必须保持 true**。
- 两种模式各漏 2 个，且漏的不是同一批：
  - 纯 MOG2 漏 92.15 / 102.15；
  - YOLO+MOG2 漏 92.15 / 113.2。
- 92.15 秒两种模式都漏。逐帧查 YOLO 推理输出可见：球在 91.47s 于框上方被检出，
  下一次检出已在 92.13s 的框下方（y=374），**穿框瞬间完全没有检出**（遮挡/运动模糊），
  轨迹里缺了框内那几帧，因此不满足“连续下行穿框”条件。
  这是当前召回瓶颈的直接原因：靠“逐帧必须检到框内点”判定，中间断一帧就漏。
- 代价：YOLO 全图逐帧推理使 1080p 视频耗时约 7x（14.9s → 103.9s）。

### 待办（本轮未做）
- 召回优化优先于切换检测器：允许轨迹在框内短暂断检（跨帧插值）后再判穿框。
- 扩评测集：当前只有 IMG_3 一条真值，结论不足以支撑阈值调参。
- 篮框自动检测准确率不足（漏检 + 多项误检），维持“候选 + 人工确认”定位。

## Session: 2026-09-23（P0：YOLO 球检测接入 detect_goals 主链路）

### Phase P0: YOLO 球检测优先 + MOG2 兜底
- **Status:** complete
- Actions taken:
  - 新增 `BallDetectorConfig`（model_path/input_size=640/conf/iou/area 上下限/fallback_to_mog2）。
  - 新增 `load_ball_detector_config`、`_discover_default_ball_model`、`_resolve_ball_model_path`、
    `_infer_ball_box_with_onnx`（复用 hoop 的 letterbox + cv2.dnn 自做 NMS 范式，返回球中心+置信度）。
  - `detect_goals_auto` 主循环改为「YOLO ONNX 球检测优先 → MOG2 兜底」：
    - YOLO 全图检测直接返回全局坐标（对手持/移动机位鲁棒）；
    - MOG2 路径仅在 detect_region 内做背景差分（保留固定机位能力），并沿用历史 `ball_conf=0.65` 常量；
    - 候选事件的 `ball_conf` 不再写死，YOLO 命中时透传真实置信度。
  - 新增 `--ball-detect-only` + `--ball-detect-samples` 调试模式（均匀采样求检测命中率）。
  - `configs/pipeline.sample.json` 增加 `ball_detector` 配置段（默认 `enabled:false`，不影响旧行为）。
- 验证：
  - `python3 -m py_compile detect_goals.py` 通过。
  - `cd app-go && go build ./...` 通过（仅第三方 sqweek/dialog deprecation 告警）。
  - ONNX 自动发现并推理：
    - IMG_3(1080p) detected 16/40 => 40.0%
    - 582055(720p竖) 8/42 => 19.1%
    - 371be0(720p横) 13/42 => 31.0%
  - 全链路回归（`detect_goals_auto`，582055 / IMG_3）：
    - `ball_detector.enabled=false` 与 `=true` 均正常出 events/meta；
    - 582055 events 2 → 3（YOLO 优先后多捕获 1 个候选）；
    - IMG_3 两模式均为 0 events（该视频目视无明显进球）。
  - 加载失败安全兜底：`enabled:true` 但模型缺失时 `ball_det_meta.status=error`，不阻断主流程。
- 产物：
  - `engine-py/detect_goals.py`（BallDetectorConfig / 推理 / 主循环集成 / CLI）
  - `configs/pipeline.sample.json`（ball_detector 段）

## Session: 2026-09-23（球检测微调基线）

### Phase 1: 公开数据集下载与整理
- **Status:** complete
- Actions taken:
  - 弃用坏数据集 `emirsahin/basketball-ball`（224MB zip 含 0 个标签文件）。
  - 采用 `koppolusameer/basketball-coco-player-detection`（CC BY 4.0，COCO 标注）。
  - `snapshot_download(max_workers=16)` 下载 2446 文件到 `/tmp/bball_ds/dl/...`。
  - 新增 `scripts/convert_ball_coco_to_yolo.py`，抽取 `category_id==1`(ball) 转 YOLO。
- 产物：
  - `training/ball_detector/datasets/ball_v1/`（train 1943 / valid 166 / test 151）。
  - `training/ball_detector/dataset.yaml`。

### Phase 2: 训练球检测基线
- **Status:** complete
- Actions taken:
  - 新增 `scripts/train_ball_detector.sh`、`scripts/export_ball_onnx.sh`。
  - YOLOv8n 微调：`imgsz=640 batch=16 device=mps epochs=100(patience=30)`。
  - 89 epoch 早停，最佳 epoch 59，耗时 2.81h。
- 指标：
  - test 划分（ultralytics val）：P=0.948 R=0.815 mAP50=0.905 mAP50-95=0.538。
  - 与 COCO 零样本同条件对比（ball_v1/test, IoU>=0.5）：
    COCO(c32) F1=0.00 vs 微调(c0) F1=0.869。
  - 手持真机逐帧采样“画面可检出球 %”：COCO 均值 11.1% → 微调 42.1%（约 3.8x）。

### Phase 3: 导出 ONNX 并用 ball_detector 评测
- **Status:** complete
- Actions taken:
  - 导出 `best.onnx`：固定 640 输入，输出 `1x5x8400` 裸检测（`nms=False, opset=12`），
    兼容 `engine-py/ball_detector.py` 的 `OnnxDnnBackend`（自做 NMS）。
  - 修正 `export_ball_onnx.sh`：不能 `nms=True`（会把 NMS 烙进图里，破坏 OnnxDnnBackend）。
  - 用 ONNX 在 3 条手持视频跑完整 `ball_detector.py` 漏斗：检测数量级下降（
    28000→707），说明 COCO 基线主要是误检；`tracks_usable` IMG_3 从 282 降至 31。
- 评测产物：
  - `training/ball_detector/runs/ball_v1_n/eval_report.json`
  - `training/ball_detector/runs/ball_v1_n/weights/{best.pt,best.onnx}`

## Session: 2026-03-22（移动端云服务重构）

### Phase A: 架构与协议冻结
- **Status:** complete
- Actions taken:
  - 对比分析当前 `app-go` 服务入口与 `gin_fram` 框架结构。
  - 明确迁移策略：双入口并行（桌面保留 + 新云 API 入口）。
  - 产出专项重构计划文档：
    - `docs/mobile_cloud_refactor_plan.zh-CN.md`
  - 更新规划文件：
    - `task_plan.md`
    - `findings.md`
    - `progress.md`

### Phase B: 云端 API 骨架搭建
- **Status:** complete
- Actions taken:
  - 新增云端服务入口：`app-go/cmd/cloud/main.go`。
  - 新增 gin_fram 风格分层骨架：
    - `internal/cloudapi/framework/http`
    - `internal/cloudapi/router`
    - `internal/cloudapi/controller`
    - `internal/cloudapi/logic`
    - `internal/cloudapi/repository`
  - 新增统一中间件：trace、timeout、access log、recovery。
  - 新增统一响应结构：`code/message/data/trace_id`。

### Phase C: 登录鉴权模块
- **Status:** complete
- Actions taken:
  - 新增登录模型与鉴权逻辑。
  - 实现 `POST /api/v1/auth/login` 与 `GET /api/v1/auth/me`。
  - 实现 Bearer 鉴权中间件，支持用户上下文注入。

### Phase D: 用户任务隔离
- **Status:** complete（基础版）
- Actions taken:
  - 新增任务模型 `Task` 并包含 `user_id`。
  - 实现任务接口：
    - `POST /api/v1/jobs`
    - `GET /api/v1/jobs`
    - `GET /api/v1/jobs/:id`
    - `POST /api/v1/jobs/:id/terminate`
  - 按 `user_id` 做读写隔离，避免跨用户访问。
  - 任务执行链路先采用异步占位实现，后续将切换到真实 `pipeline`。

### 验证结果（本轮）
- `cd app-go && go test ./...` 通过。
- 云 API 冒烟通过：
  - `GET /health`
  - `POST /api/v1/auth/login`
  - `GET /api/v1/auth/me`
  - `POST /api/v1/jobs`
  - `GET /api/v1/jobs`
  - `GET /api/v1/jobs/:id`
  - `POST /api/v1/jobs/:id/terminate`

## Session: 2026-03-07

### Phase 1: 需求确认与现状梳理
- **Status:** complete
- **Started:** 2026-03-07 17:00
- Actions taken:
  - 确认发布目标：macOS M 系列、macOS Intel、Windows。
  - 检查现有打包脚本和依赖调用路径。
  - 新建 `task_plan.md`、`findings.md`、`progress.md`。
- Files created/modified:
  - `task_plan.md`（created+filled）
  - `findings.md`（created+filled）
  - `progress.md`（created+filled）

### Phase 2: 运行时探测与代码改造
- **Status:** complete
- Actions taken:
  - `cmd/app` 增加内置运行时探测并自动设置 `BASKETBALL_MVP_PYTHON`、`BASKETBALL_MVP_FFMPEG`。
  - `cmd/desktop` 扩展 FFmpeg 探测并传递到后端进程环境。
  - `internal/engine/runner.go` 增加 `runtime/python` 候选路径。
  - `internal/ffmpeg/ffmpeg.go` 改为支持 `BASKETBALL_MVP_FFMPEG`，并保留 PATH fallback。
- Files created/modified:
  - `app-go/cmd/app/main.go`
  - `app-go/cmd/desktop/main.go`
  - `app-go/internal/engine/runner.go`
  - `app-go/internal/ffmpeg/ffmpeg.go`

### Phase 3: 打包脚本改造（含多架构）
- **Status:** complete
- Actions taken:
  - `build_macos_app.sh` 支持 `--arch arm64|amd64|universal`。
  - macOS 构建新增运行时拷贝：`runtime/macos-<arch>/`。
  - `build_windows_app.ps1` 支持 `-Arch`，输出到 `dist/windows-<arch>/`。
  - Windows 启动脚本支持自动注入内置 Python/FFmpeg 环境变量。
- Files created/modified:
  - `scripts/build_macos_app.sh`
  - `scripts/build_windows_app.ps1`

### Phase 4: 文档与验证
- **Status:** complete
- Actions taken:
  - README 增加 runtime 目录规范与多架构打包说明。
  - 完成 `go build` / `py_compile` / `bash -n` 校验。
  - 本地执行了 macOS 三种打包命令并成功产出应用包。
- Files created/modified:
  - `README.md`

### Phase 5: 自动化 runtime 下载与组装
- **Status:** complete
- Actions taken:
  - 新增 `scripts/prepare_runtime_macos.sh`（自动下载 python-build-standalone + ffmpeg-static 并安装 pip 依赖）。
  - 新增 `scripts/prepare_runtime_windows.ps1`（Windows 自动下载/组装 runtime）。
  - README 补充自动化命令与参数说明。
  - 实测 `prepare_runtime_macos.sh --arch arm64` 成功安装 `numpy/opencv-python-headless`。
- Files created/modified:
  - `scripts/prepare_runtime_macos.sh`（new）
  - `scripts/prepare_runtime_windows.ps1`（new）
  - `README.md`（updated）

## Test Results
| Test | Input | Expected | Actual | Status |
|------|-------|----------|--------|--------|
| 现状梳理 | 查看打包脚本与执行入口 | 找到所有依赖调用点 | 已完成 | ✓ |
| Go 构建 | `cd app-go && go build ./...` | 通过 | 通过（有系统告警） | ✓ |
| Python 语法 | `python3 -m py_compile engine-py/detect_goals.py` | 通过 | 通过 | ✓ |
| macOS 打包 arm64 | `./scripts/build_macos_app.sh --arch arm64` | 生成 app | 生成成功 | ✓ |
| macOS 打包 amd64 | `./scripts/build_macos_app.sh --arch amd64` | 生成 app | 生成成功 | ✓ |
| macOS 打包 universal | `./scripts/build_macos_app.sh --arch universal` | 生成 app | 生成成功 | ✓ |
| macOS 强制 runtime | `./scripts/build_macos_app.sh --arch arm64 --require-runtime` | 缺少 runtime 时失败 | 按预期失败 | ✓ |
| 架构检查 | `file .../BasketballMVP` | arm64/amd64 架构正确 | 通过 | ✓ |
| macOS runtime 自动准备 | `./scripts/prepare_runtime_macos.sh --arch arm64` | 产出可用 runtime | 成功 | ✓ |
| runtime 校验 | `./scripts/verify_runtime_bundle.sh --runtime-dir ./runtime/macos-arm64` | cv2/numpy/ffmpeg可用 | 通过 | ✓ |
| 强制内置 runtime 打包 | `./scripts/build_macos_app.sh --arch arm64 --require-runtime` | 成功且打包内置 runtime | 通过 | ✓ |

## Error Log
| Timestamp | Error | Attempt | Resolution |
|-----------|-------|---------|------------|
| - | 暂无 | 1 | - |

## 5-Question Reboot Check
| Question | Answer |
|----------|--------|
| Where am I? | Phase 2 |
| Where am I going? | 完成代码改造与打包脚本 |
| What's the goal? | 跨平台无外部依赖安装包 |
| What have I learned? | 见 findings.md |
| What have I done? | 见本日志 |

## Session: 2026-03-09

### Phase 7: 检测链路审查 + 注释增强
- **Status:** complete
- Actions taken:
  - 读取并确认当前规划文件与工作区状态。
  - 扫描检测主链路函数/类清单，确认注释补充范围。
  - 初步识别两个可落地优化点（路径清理健壮性、net motion 后处理复杂度）。
  - 在 `engine-py/detect_goals.py` 完成 net motion 后处理复杂度优化，并修正 `net_region` 扩展计算一致性。
  - 在 `app-go/cmd/app/main.go` 落地 `startSingleJob` 并发竞态收敛（创建任务时一次写入 KeepDebug/ExportRoot）。
  - 扩展注释覆盖到 `app-go/cmd/app/*`、`app-go/cmd/desktop/*`、`app-go/internal/models/models.go`、`app-go/web/index.html`。
  - 对前端原生对话框 fallback 请求补充异常路径定时器清理。
- Files created/modified:
  - `task_plan.md`
  - `findings.md`
  - `progress.md`
  - `engine-py/detect_goals.py`
  - `engine-py/calibrate_hoop_roi.py`
  - `app-go/cmd/app/main.go`
  - `app-go/cmd/app/dialog_darwin.go`
  - `app-go/cmd/app/dialog_windows.go`
  - `app-go/cmd/app/dialog_other.go`
  - `app-go/cmd/app/platform_common.go`
  - `app-go/cmd/desktop/main.go`
  - `app-go/cmd/desktop/dialog_darwin.go`
  - `app-go/cmd/desktop/dialog_windows.go`
  - `app-go/cmd/desktop/dialog_other.go`
  - `app-go/internal/models/models.go`
  - `app-go/web/index.html`

### Phase 7 Validation
- **Status:** complete
- Actions taken:
  - 执行 `gofmt` 格式化所有新增注释的 Go 文件。
  - 执行 `cd app-go && go build ./...` 验证构建通过。
  - 执行 `python3 -m py_compile detect_goals.py calibrate_hoop_roi.py` 验证 Python 语法通过。

### Phase 8: 自动篮框检测方案规划
- **Status:** complete
- Actions taken:
  - 定位 `hoop` 的输入与消费链路：`SingleStartRequest.Hoop` -> `pipeline.run.json` -> `setup_regions`。
  - 输出不依赖手工框选的自动篮框检测方案（分层算法 + 置信度 + 兜底策略）。
  - 输出可落地开发计划（按阶段拆分改造点、验收指标、风险控制）。
- Files created/modified:
  - `task_plan.md`
  - `findings.md`
  - `progress.md`

### Phase 9: YOLO->ONNX 自动篮框实施计划细化
- **Status:** complete
- Actions taken:
  - 基于用户确认路线（YOLO 微调 + ONNX 部署 + 时序融合）细化 5 个执行阶段。
  - 给出阶段目标、关键任务、里程碑与首版验收阈值。
  - 更新 planning 文件，作为后续执行蓝图。
- Files created/modified:
  - `task_plan.md`
  - `findings.md`
  - `progress.md`

### Phase 9: 标注与训练模板落地（进行中）
- **Status:** in_progress
- Actions taken:
  - 新增自动篮框标注规范文档（单类 hoop、框选边界、质检清单）。
  - 新增训练说明与数据集模板，统一 YOLO 目录结构。
  - 预创建 `hoop_v1` 数据集目录骨架，便于直接落图与标签。
  - 新增抽帧脚本 `extract_hoop_label_frames.py`，支持从视频批量抽样到 train/val/test。
  - 新增训练脚本与 ONNX 导出脚本，支持环境变量参数化执行。
  - README 增加自动篮框准备章节与最小执行命令。
- Files created/modified:
  - `docs/auto_hoop_annotation.zh-CN.md`（new）
  - `training/hoop_detector/README.zh-CN.md`（new）
  - `training/hoop_detector/dataset.yaml.template`（new）
  - `training/hoop_detector/datasets/hoop_v1/.../.gitkeep`（new）
  - `scripts/extract_hoop_label_frames.py`（new）
  - `scripts/train_hoop_detector.sh`（new）
  - `scripts/export_hoop_onnx.sh`（new）
  - `README.md`（updated）
  - `task_plan.md`（updated）
  - `findings.md`（updated）
  - `progress.md`（updated）

### Phase 9: 单视频冒烟验证（完成）
- **Status:** complete
- Actions taken:
  - 在 `.venv` 安装 `ultralytics`，补齐训练/导出依赖。
  - 使用单视频执行抽帧：
    - `scripts/extract_hoop_label_frames.py --input IMG_1556-tmp.MOV ...`
  - 构造 `hoop_smoke` 最小数据集，执行 1 epoch 训练。
  - 成功导出 ONNX，并用 ONNX Runtime 执行预测命令验证可加载。
- Key outputs:
  - `training/hoop_detector/datasets/hoop_smoke/frame_extract_summary.json`
  - `runs/detect/training/hoop_detector/runs/hoop_smoke/weights/best.pt`
  - `runs/detect/training/hoop_detector/runs/hoop_smoke/weights/best.onnx`
- Validation:
  - `python3 -m py_compile scripts/extract_hoop_label_frames.py` 通过
  - `yolo detect train`（smoke 配置）通过
  - `yolo export format=onnx` 通过

### Phase 9: 真实视频抽帧与训练集整理（进行中）
- **Status:** in_progress
- Actions taken:
  - 从 `/Users/quzhengyang/www/360.cn/Python/highLight` 下已采集视频抽帧到 `hoop_v1`。
  - 将 `IMG_1556.MOV` 留在 train，将 `IMG_1556-tmp.MOV` 切到 val，避免同视频跨集合泄漏。
  - 生成 `training/hoop_detector/dataset.yaml` 作为正式训练入口配置。
  - 对 `images vs labels` 完成一致性检查，确认当前缺少真实标签文件。
- Current stats:
  - train images: 260, labels: 0
  - val images: 38, labels: 0
- Files created/modified:
  - `training/hoop_detector/datasets/hoop_v1/frame_extract_summary.json`
  - `training/hoop_detector/dataset.yaml`
  - `findings.md`
  - `progress.md`

## Session: 2026-03-22

### Phase 10/12: 自动篮框确认流程实现
- **Status:** in_progress
- Actions taken:
  - 在 Python 引擎 `engine-py/detect_goals.py` 新增 `--detect-hoop-only` 模式，输出篮框候选聚类结果与 `none/single/multiple` 状态。
  - 增加候选聚类与预览图产物（`auto_hoop_candidates.jpg`、`auto_hoop_candidates.json`）。
  - 在 Go 后端新增 `POST /api/v1/hoop/detect`，用于任务前自动检测篮框候选。
  - 新增 `internal/models` 的候选/响应结构，新增 `internal/engine/runner.go` 的候选检测调用。
  - 改造前端向导：
    - 加载视频后自动触发篮框检测；
    - 未检测到时提示手工兜底；
    - 多候选时下拉选择并确认回填；
    - 单候选时用户确认后回填；
    - 未回填篮框前禁止启动任务。
  - 调整 `single-job/start`：必须携带已确认 `hoop`，并关闭任务阶段二次自动篮框。
- Files created/modified:
  - `app-go/internal/models/models.go`
  - `app-go/internal/engine/runner.go`
  - `app-go/cmd/app/main.go`
  - `app-go/web/index.html`
  - `engine-py/detect_goals.py`
  - `task_plan.md`
  - `findings.md`
  - `progress.md`

### Validation
- `gofmt -w app-go/cmd/app/main.go app-go/internal/engine/runner.go app-go/internal/models/models.go` 通过
- `python3 -m py_compile engine-py/detect_goals.py` 通过
- `cd app-go && go build ./...` 通过（第三方依赖 `sqweek/dialog` 有 macOS deprecation warning，不影响构建）
- `python3 detect_goals.py --detect-hoop-only ...` 在当前环境失败：缺少 `cv2`（已按预期提示安装 `opencv-python numpy`）
