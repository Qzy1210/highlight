# Findings & Decisions

## Requirements
- 目标平台：`macOS arm64`、`macOS amd64`、`Windows amd64`
- 运行目标：测试同学机器无需额外安装 Python/FFmpeg
- 交付形式：可直接分发的应用包（后续可再做签名公证 DMG/Installer）

## Research Findings
- 当前 `build_macos_app.sh` 只构建单架构、仅拷贝源码与前端资源，不内置 Python/FFmpeg。
- 当前 `build_windows_app.ps1` 同样未内置 Python/FFmpeg。
- Python 调用路径由 `internal/engine/runner.go` 决定，当前优先环境变量与系统/venv。
- FFmpeg 调用在 `internal/ffmpeg/ffmpeg.go`，当前硬编码 `ffmpeg` 依赖 PATH。
- 桌面启动器 `cmd/desktop/main.go` 已支持注入 `BASKETBALL_MVP_PYTHON`，可扩展到 FFmpeg。
- 当前机器已验证可直接构建 `arm64`、`amd64`、`universal` 三种 macOS 包。
- `astral-sh/python-build-standalone` 最新 release 可按目标三元组精确下载 `install_only.tar.gz`。
- `eugeneware/ffmpeg-static` 最新 release 含 `darwin-arm64/darwin-x64/win32-x64` ffmpeg 可执行文件。

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| 使用 `runtime/<platform>-<arch>/` 作为打包输入目录 | 明确分平台产物边界，方便 CI 或人工准备依赖 |
| 运行时优先探测“内置依赖”，其次 fallback 到系统 | 兼容开发调试与线上分发 |
| 先做“可执行脚本与代码通路”，再做自动下载依赖 | 降低一次性复杂度，保证可逐步验证 |
| macOS 构建支持 `--arch arm64|amd64|universal` | 满足 M 系列与 Intel 双平台目标 |
| 自动 runtime 脚本默认安装 `numpy + opencv-python-headless` | 满足检测依赖并减少 GUI 组件体积 |

## 2026-03-09 检测链路审查（新增）
- 本次审查范围聚焦检测主链路：`engine-py/detect_goals.py`、`engine-py/calibrate_hoop_roi.py`、`app-go/internal/{pipeline,engine,ffmpeg}`。
- 发现可优化点（低风险）：
  - `cleanupOutputDir` 在 `runJob` 中用 `job.OutputDir` 直接清理，若是相对路径存在误清理风险；应统一先做 `ResolveOutputDir`。
  - 自动检测后处理中，候选事件确认使用“每个候选遍历整段 `net_series`”的方式，复杂度偏高，可改为按帧索引查询减少扫描开销。
- 注释层面现状：
  - 已有少量行内注释，但缺少系统化“函数职责 + 入参/出参 + 约束”的说明，阅读成本仍偏高。

## 2026-03-09 注释增强与低风险优化（补充）
- 已落地优化：
  - `engine-py/detect_goals.py`：
    - 将候选事件的篮网确认由“遍历整段序列”改为“按帧字典窗口查询”，减少重复扫描。
    - 修正 `net_region` 公式中“向下额外扩展 1/3 高度”未统一生效的问题。
  - `app-go/cmd/app/main.go`：
    - `cleanupOutputDir` 调用前统一 `ResolveOutputDir`，避免相对路径清理风险。
    - `startSingleJob` 改为在任务创建时一次性写入 `KeepDebug/ExportRoot`，避免任务启动后再写字段的并发竞态窗口。
  - `app-go/web/index.html`：
    - 原生对话框请求超时定时器改为 `finally` 统一清理，避免异常路径残留定时器。
- 注释覆盖扩展：
  - Python：检测主脚本、标定脚本关键函数已补齐职责/入参/出参注释。
  - Go：`cmd/app`、`cmd/desktop`、`internal/{pipeline,engine,ffmpeg,config,models}` 关键类型与函数补齐注释。
  - 前端：`web/index.html` 主要函数补充 JSDoc 与关键交互逻辑说明。

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| 当前环境无法直接验证 Windows 打包运行 | 先完成脚本与路径改造，文档中明确需在 Windows 机做最终验证 |

## Resources
- `/Users/quzhengyang/www/360.cn/Python/highLight/basketball-mvp/scripts/build_macos_app.sh`
- `/Users/quzhengyang/www/360.cn/Python/highLight/basketball-mvp/scripts/build_windows_app.ps1`
- `/Users/quzhengyang/www/360.cn/Python/highLight/basketball-mvp/app-go/cmd/desktop/main.go`
- `/Users/quzhengyang/www/360.cn/Python/highLight/basketball-mvp/app-go/internal/engine/runner.go`
- `/Users/quzhengyang/www/360.cn/Python/highLight/basketball-mvp/app-go/internal/ffmpeg/ffmpeg.go`
