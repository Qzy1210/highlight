# Progress Log

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
