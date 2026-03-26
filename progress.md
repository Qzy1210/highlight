# Progress Log

## 2026-03-06

### Session Objective
输出“篮球视频自动剪辑桌面版”MVP 方案，要求贴合 Go 技术栈并可快速验证。

### Completed
- 读取并延续现有规划文件（`task_plan.md`, `findings.md`）
- 完成技术栈建议：Go + gocv + Fyne + FFmpeg
- 完成模块拆分、检测链路、参数初值与接口草案
- 完成 4 周里程碑与评估指标方案
- 新建本日志文件用于后续迭代跟踪

### Key Output
- 明确 MVP 判定逻辑：`球穿框` + `篮网晃动` 融合评分
- 明确输出形态：单个集锦视频 + 多进球片段
- 明确验证指标：Recall 优先，Precision 次之

### Next Actions
1. 初始化 Go 项目骨架（ui/pipeline/detector/clipper/exporter）
2. 接入 FFmpeg 切片命令并做最小可运行链路
3. 开发 ROI 框选与配置保存
4. 实现球轨迹检测基线版本

### Issues
- 暂无阻塞问题

## 2026-03-06 (Implementation)

### Completed
- Created `/basketball-mvp` scaffold with Go(Gin) + Python + FFmpeg pipeline.
- Implemented Gin API:
  - `POST /api/v1/jobs`
  - `GET /api/v1/jobs/:id`
  - `GET /health`
- Implemented Python engine entrypoint `engine-py/detect_goals.py`.
- Implemented FFmpeg clip cut + highlight merge in Go.
- Added sample config and README quick-start.
- Built successfully with Go 1.17 compatibility (`gin v1.7.7`).

### Current State
- End-to-end runnable in manual-goal mode.
- Ready for next step: replace Python manual mode with actual CV detection.

## 2026-03-06 (Auto Detect MVP)

### Completed
- Upgraded `basketball-mvp/engine-py/detect_goals.py` from manual-only to dual mode:
  - manual mode (when `manual_goals` provided)
  - auto detect mode (OpenCV baseline)
- Added ROI-based detection pipeline:
  - hoop/above/detect/net regions
  - moving-ball candidate extraction by background subtraction + contour filtering
  - goal candidate from downward crossing behavior
  - net motion confirmation in short time window
  - cooldown and event dedup merge window
- Added config knobs under `detect` and `hoop` in `configs/pipeline.sample.json`.
- Updated README with auto mode request example and config notes.

### Borrowed Best Practices from Reference Script
- Region derivation from hoop center/radius
- Cooldown strategy to prevent duplicate goals
- Multi-signal approach (ball trajectory + net motion)
- Config-driven thresholds for fast iteration

### Notes
- Current environment does not include OpenCV (`cv2`), so auto mode reports install guidance.
- Manual mode remains available without OpenCV.

## 2026-03-06 (ROI Debug + Tuning Log)

### Completed
- Added ROI debug image output in auto mode: `roi_debug.jpg`.
- Added auto parameter suggestion log: `tuning_suggestions.json`.
- Added `meta.debug_artifacts` paths into `goals.json` output.
- Updated README with artifact descriptions.

### Notes
- In this execution environment, OpenCV is not installed so auto-mode runtime verification cannot complete here.
- Script syntax is validated with `py_compile`; manual mode remains working.

## 2026-03-06 (Fix no-goal + ROI calibration)

### Completed
- Fixed a critical false-negative logic issue in auto detect:
  - replaced impossible same-frame condition (`in_above and in_hoop`) with temporal crossing logic (`above_recently + in_hoop + moving_down`).
- Added `engine-py/calibrate_hoop_roi.py` to interactively select hoop ROI and write `hoop.cx/cy/r` back into config.
- Updated README with calibration command and rerun guidance.

## 2026-03-06 (Goal frame snapshots + API progress)

### Completed
- Added per-goal frame snapshot export in auto mode (`goal_frames/*.jpg`).
- Extended each goal event with `frame_image` field in `goals.json`.
- Added Python progress writer (`--progress-file`) for detection phase.
- Added Go-side progress polling and API exposure in `GET /api/v1/jobs/:id`:
  - stage, percent, elapsed_sec, estimated_left_sec, processed_frames, total_frames.
- Added clip/merge phase progress updates in pipeline.

### Validation
- `go build ./...` passed
- `python3 -m py_compile ...` passed

## 2026-03-06 (Manual edit + re-export backend loop)

### Completed
- Added event editing API: `PUT /api/v1/jobs/:id/events`.
- Added re-export API: `POST /api/v1/jobs/:id/reexport`.
- Re-export now cuts+merges using edited events without re-running detection.
- Added progress states for re-export stages in job status.
- Persist edited events to `<output_dir>/events.edited.json`.
- Updated README with API examples.

### Validation
- `go build ./...` passed.

## 2026-03-06 (Single-task UI flow)

### Completed
- Added built-in web UI at `/app/` for single-task MVP flow.
- Added upload API: `POST /api/v1/upload`.
- Added single-start API: `POST /api/v1/single-job/start` (with hoop cx/cy/r).
- UI supports local video preview, hoop selection, start job, progress polling, manual event edit, and re-export.

### Validation
- `go build ./...` passed.

## 2026-03-06 (Event UX simplification)

### Completed
- Simplified event operation to checkbox-only export selection (default all selected).
- Added timeline preview buttons to jump to event timestamps in video player.
- Added frame thumbnail display for each event row (`frame_image`).
- Added one-step export action: save selected events + re-export.
- Exposed workspace static files via `/workspace` for thumbnail rendering.

### Validation
- `go build ./...` passed.

## 2026-03-06 (Desktop packaging + no-upload flow)

### Completed
- Replaced upload-based flow with local path selection flow (macOS dialog APIs).
- Added app settings persistence: `export_root`, `keep_debug`.
- Single job output now writes to export root (`<video_name>_<timestamp>` run folder).
- Added temp artifact cleanup after success when `keep_debug=false`.
- Added local file streaming API for preview/thumbnails (`/api/v1/file`).
- Added macOS app bundle build script: `scripts/build_macos_app.sh`.
- Built app bundle successfully: `dist/BasketballMVP.app`.

### Notes
- Dialog APIs use `osascript` and are macOS-only.

## 2026-03-06 (Native app window migration)

### Completed
- Added native desktop launcher (`cmd/desktop`) using WebView window.
- Packaged `.app` now launches internal window instead of opening browser.
- Added settings APIs (`export_root`, `keep_debug`) and persistence.
- Added macOS file/folder dialog APIs for local-path flow.
- Added local absolute file serving API (`/api/v1/file`) for preview and thumbnails.
- Updated single-task flow to no-upload and export-root based run folder.
- Rebuilt app bundle successfully.

## 2026-03-06 (Cross-platform prep + Chinese comments)

### Completed
- Added platform-specific dialog implementations:
  - macOS: AppleScript (`osascript`)
  - Windows: PowerShell WinForms dialogs
  - Other OS: clear unsupported error
- Kept mac build path intact and rebuilt `.app` successfully.
- Updated desktop launcher to support mac/windows path conventions.
- Added Windows packaging script: `scripts/build_windows_app.ps1`.
- Added Chinese parameter documentation: `configs/CONFIG.zh-CN.md`.
- Added Chinese inline comments for key detection and config structures.

### Validation
- `go build ./...` passed on macOS.
- `./scripts/build_macos_app.sh` passed.

## 2026-03-07 (mac dialog retry)

### Completed
- Replaced macOS dialog implementation from `osascript` to native Go dialog (`github.com/sqweek/dialog`).
- Rebuilt mac app bundle after change.

### Result
- No longer depends on Apple Events interaction path that triggered -1713.

## 2026-03-20 (App 架构评估：端侧 vs 云端)

### Session Objective
输出移动 App 形态下“端侧剪辑 vs 云端剪辑”的评估方案，并给出可执行决策路径。

### Completed
- 使用官方文档核对 iOS/Android 长任务与视频处理能力边界。
- 使用腾讯云/阿里云官方计费文档梳理云端成本结构与估算维度。
- 形成三种方案对比：纯端侧、纯云端、混合架构。
- 产出试点评估框架（KPI、成本模型、闸口指标、2~4 周执行步骤）。

### Notes
- 本次输出为架构评估方案，无代码编译/测试动作。
