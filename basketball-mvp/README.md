# Basketball MVP（本地篮球集锦桌面工具）

一个本地运行的篮球视频剪辑 MVP：

1. 自动检测进球时间点（Python/OpenCV）。
2. 支持手动勾选进球事件。
3. 一键导出集锦（FFmpeg）。

当前形态是单任务桌面流程（无上传、直接读本地视频）。

## 1. 功能总览

- 本地选择视频并框选篮框（两次点击：中心 -> 边缘）。
- 可选启用 `auto_hoop`（ONNX）自动识别篮框并回填 `hoop`。
- 自动检测进球事件并展示时间轴。
- 勾选事件后点击 `导出视频` 重导出。
- 任务进度实时显示：`进度`、`预计剩余`、`已耗时`。
- 导出成功后显示完整输出路径。
- 默认导出目录固定为视频同级：
  - `<视频目录>/BasketballMVP_Exports/<video_name>_<timestamp>/`
- 调试文件统一存放在任务目录 `debug/`，不在界面暴露配置项。

## 2. 项目结构

```text
basketball-mvp/
├─ app-go/                 # Go 服务 + 桌面壳 + Web UI
├─ engine-py/              # Python 检测引擎
├─ configs/                # 配置模板与中文参数说明
├─ scripts/                # 运行时准备、校验、打包脚本
├─ runtime/                # 可选：内置 Python/FFmpeg 运行时
├─ dist/                   # 打包产物
└─ workspace/              # 运行输出（源码运行时）
```

## 3. 快速上手（开发环境）

### 3.1 启动 Web 版流程

```bash
cd app-go
go run ./cmd/app
```

打开：`http://127.0.0.1:8088/app/`

### 3.2 启动原生桌面窗口（源码）

```bash
cd app-go
go run ./cmd/desktop
```

### 3.3 启动云 API 服务（移动端/前后端分离）

```bash
cd app-go
go run ./cmd/cloud -f ./conf/cloud/dev.yml
```

健康检查：

- `GET http://127.0.0.1:8090/health`

登录并拿令牌：

```bash
curl -X POST http://127.0.0.1:8090/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"ChangeMe123"}'
```

说明：

- 云 API 已按 gin_fram 风格重构启动链路：`flags -> config -> logger -> driver -> http`。
- 配置文件支持 `includes`（参考 `app-go/conf/cloud/dev.yml`）。
- 用户、任务、refresh token 已切到 MySQL 仓库；任务按 `user_id` 隔离。
- 登录会返回 `access_token + refresh_token`，并支持 refresh token 轮换刷新。
- 桌面版入口 `cmd/app` 与 `cmd/desktop` 保留，不受影响。

### 3.4 桌面端 API 模式切换

桌面 Web UI 新增了 API 配置：

- `本地模式`：业务 API 走本机 `cmd/app`（默认）。
- `云端模式`：业务 API 走你填写的 `api_base_url`（本地文件选择/预览仍走本机接口）。

设置会持久化到本地 `settings.json`，对应字段：

- `api_mode`：`local` / `cloud`
- `api_base_url`：云端服务根地址（例如 `https://api.example.com`）

### 3.3 使用步骤（UI）

1. 点击 `1. 选择本地视频`（或手输绝对路径并点击“加载路径”）。
2. 点击 `2. 框选篮框`，在视频上依次点击中心、边缘。
3. 点击 `3. 开始剪辑任务`。
4. 检测完成后在时间轴勾选事件。
5. 点击 `导出视频` 进行重导出。

## 4. 输出目录与产物

每次任务在以下目录生成：

- `<视频目录>/BasketballMVP_Exports/<video_name>_<timestamp>/`

主要文件：

- `highlight.mp4`：最终集锦。
- `goals.json`：检测事件结果。
- `pipeline.run.json`：本次任务使用的配置（含 hoop）。
- `debug/`：调试产物。

`debug/` 常见内容：

- `roi_debug.jpg`：ROI 可视化。
- `goal_frames/`：事件截图。
- `clips/`：剪切片段。
- `clips.txt`：合并输入列表。
- `merge.stderr.log`：FFmpeg 合并日志。
- `tuning_suggestions.json`：调参建议。

## 5. ROI 区域说明（自动检测）

相关代码位置：`engine-py/detect_goals.py` 的 `setup_regions()`。

- `detect_region`：大检测区域，用于前景运动里找球候选。
- `hoop_above_region`：篮框上方区域，用于判定“球先在框上方出现”。
- `hoop_region`：篮框核心区域，用于判定“球进入框内”。
- `net_region`：篮网确认区域，用于判定“球过框后网是否有晃动”。

核心判定逻辑：

1. 在 `detect_region` 找到球心轨迹。
2. 轨迹需满足“先进入 `hoop_above_region`，再进入 `hoop_region`，整体下行”。
3. 在确认窗口内，`net_region` 有足够运动量，才确认为进球事件。

## 6. 轻量调试模式（默认关闭，不影响业务流程）

仅在手动执行检测脚本时打开：

```bash
python3 engine-py/detect_goals.py \
  --video /abs/path/input.mp4 \
  --config configs/pipeline.sample.json \
  --output /abs/path/output/goals.json \
  --debug-dir /abs/path/output/debug \
  --lite-debug \
  --lite-debug-frame-step 12 \
  --lite-debug-max-frames 120
```

额外产物目录：`debug/lite_debug/`

- `frame_metrics.jsonl`
- `frames/`
- `candidates.json`
- `events_raw.json`
- `events_dedup.json`
- `summary.json`

## 7. 篮框标定工具

当 `roi_debug.jpg` 不准时，可先标定再跑检测：

```bash
python3 engine-py/calibrate_hoop_roi.py \
  --video /abs/path/input.mp4 \
  --config configs/pipeline.sample.json \
  --frame-ratio 0.5
```

会更新配置中的：

```json
"hoop": { "cx": ..., "cy": ..., "r": ... }
```

## 8. 打包为免依赖安装包

目标：测试机无需安装 Python / NumPy / OpenCV / FFmpeg。

### 8.1 macOS（arm64 / amd64 / universal）

1) 准备内置 runtime：

```bash
cd /Users/quzhengyang/www/360.cn/Python/highLight/basketball-mvp
./scripts/prepare_runtime_macos.sh --arch arm64
./scripts/prepare_runtime_macos.sh --arch amd64
```

2) 校验 runtime：

```bash
./scripts/verify_runtime_bundle.sh --runtime-dir ./runtime/macos-arm64
./scripts/verify_runtime_bundle.sh --runtime-dir ./runtime/macos-amd64
```

3) 打包：

```bash
./scripts/build_macos_app.sh --arch arm64 --require-runtime
./scripts/build_macos_app.sh --arch amd64 --require-runtime
# 可选：./scripts/build_macos_app.sh --arch universal --require-runtime
```

产物在 `dist/`，例如：

- `BasketballMVP-arm64.app`
- `BasketballMVP-amd64.app`
- `BasketballMVP-universal.app`（可选）

### 8.2 Windows（amd64 / arm64）

建议在 Windows PowerShell 中执行：

```powershell
cd <repo>\basketball-mvp
.\scripts\prepare_runtime_windows.ps1 -Arch amd64
.\scripts\verify_runtime_bundle.ps1 -RuntimeDir .\runtime\windows-amd64
.\scripts\build_windows_app.ps1 -Arch amd64 -RequireRuntime
```

产物目录：`dist/windows-amd64/`（或对应架构目录）。

说明：

- Windows 仍需系统有 WebView2 Runtime（Win10/11 通常已具备或自动安装）。
- `prepare_runtime_windows.ps1 -Arch arm64` 当前 ffmpeg 使用 x64 资产回退策略。

## 9. 运行时查找与环境变量

程序会按顺序尝试：

1. 环境变量指定路径。
2. 内置 runtime 路径。
3. 系统 PATH / 常见本地解释器。

可手动指定：

- `BASKETBALL_MVP_ROOT`：项目根目录。
- `BASKETBALL_MVP_DATA`：工作目录（任务与设置）。
- `BASKETBALL_MVP_PYTHON`：Python 可执行文件路径。
- `BASKETBALL_MVP_FFMPEG`：FFmpeg 可执行文件路径。

## 10. API（最常用）

- `POST /api/v1/single-job/start`：启动单任务。
- `GET /api/v1/jobs/:id`：查询任务状态、进度、事件、导出路径。
- `PUT /api/v1/jobs/:id/events`：更新事件列表。
- `POST /api/v1/jobs/:id/reexport`：按更新后事件重导出。
- `GET /api/v1/file?path=<abs_path>`：读取本地文件（预览截图等）。
- `GET /api/v1/settings`、`PUT /api/v1/settings`：设置项接口（含 `api_mode/api_base_url`）。

云 API（`cmd/cloud`）首批接口：

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/auth/me`（需 Bearer Token）
- `POST /api/v1/jobs`（需 Bearer Token）
- `GET /api/v1/jobs`（需 Bearer Token，仅返回当前用户任务）
- `GET /api/v1/jobs/:id`（需 Bearer Token，仅当前用户可访问）
- `POST /api/v1/jobs/:id/terminate`（需 Bearer Token，仅当前用户可终止）

`GET /api/v1/jobs/:id` 进度字段：

- `progress.stage`
- `progress.percent`
- `progress.elapsed_sec`
- `progress.estimated_left_sec`
- `progress.processed_frames`
- `progress.total_frames`

## 11. 常见问题

### Q1：打包后的 App 还需要测试机安装 Python 吗？

不需要。前提是你打包时已内置 runtime，并使用 `--require-runtime`（或 `-RequireRuntime`）保证打包阶段强校验。

### Q2：首次打开 macOS App 被拦截怎么办？

右键 App 选择“打开”一次，或在“系统设置 -> 隐私与安全性”放行。

### Q3：自动检测报 OpenCV/NumPy 缺失？

- 源码运行：给当前 Python 安装依赖。
- 打包运行：确认包内 runtime 完整并通过 `verify_runtime_bundle`。

## 12. 相关文档

- 参数中文说明：`configs/CONFIG.zh-CN.md`
- 示例配置：`configs/pipeline.sample.json`

## 13. 自动篮框（YOLO -> ONNX）准备

当前线上流程仍以手工框选为入口；若要推进自动篮框，可按以下步骤启动训练与部署准备。

标注规范：

- `docs/auto_hoop_annotation.zh-CN.md`

训练说明：

- `training/hoop_detector/README.zh-CN.md`

最小执行命令：

```bash
# 1) 抽帧生成待标注图片（可选但推荐）
python3 scripts/extract_hoop_label_frames.py \
  --input /abs/path/videos \
  --output-root training/hoop_detector/datasets/hoop_v1/images \
  --interval-sec 0.8 \
  --max-frames-per-video 220 \
  --recursive

# 2) 复制并修改数据集配置
cp training/hoop_detector/dataset.yaml.template training/hoop_detector/dataset.yaml

# 3) 训练
./scripts/train_hoop_detector.sh

# 4) 导出 ONNX
MODEL=./training/hoop_detector/runs/hoop_v1_n/weights/best.pt ./scripts/export_hoop_onnx.sh
```
### 编译APP
cd /Users/quzhengyang/www/360.cn/Python/highLight/basketball-mvp
./scripts/build_macos_app.sh
