# Progress Log

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
