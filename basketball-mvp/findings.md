# Findings: 移动端云服务重构（2026-03-22）

## 2026-09-23 P0：YOLO 球检测接入 detect_goals（新增）
- 目标：把微调后的球 ONNX 作为主链路球定位来源（YOLO 优先 + MOG2 兜底），
  解决手持/移动机位下 MOG2 背景差分失效问题。
- 关键实现：
  - `BallDetectorConfig` 从 `cfg["ball_detector"]` 读取，默认 `enabled:false`，旧配置/旧行为完全不变。
  - `_infer_ball_box_with_onnx` 复用 hoop 的 letterbox + cv2.dnn 自做 NMS 范式；ONNX 固定 640 输入。
  - 主循环：YOLO 全图命中直接用全局坐标；未命中且 `fallback_to_mog2=true` 时回退 detect_region 内 MOG2。
  - 候选事件 `ball_conf` 由写死的 0.65 改为 YOLO 真实置信度（MOG2 路径仍为 0.65）。
  - 新增 `--ball-detect-only` 调试模式，均匀采样输出 `detection_ratio`（等价于“画面可检出球 %”）。
- 实测命中率（ball-detect-only, ~40 帧采样）：
  | 视频 | detection_ratio |
  |------|-----------------|
  | 582055(高晃) | 19.1% |
  | 371be0(中晃) | 31.0% |
  | IMG_3(低晃) | 40.0% |
  - 注：与之前 ultralytics 逐帧 probe（23.8/47.6/55.0）量级一致但偏低，
    原因是 `--ball-detect-only` 采样帧数少（40 帧）且为均匀间隔，非逐帧密采样。
- 回归：582055 `detect_goals_auto` events 2→3（YOLO 优先后多捕获候选）；IMG_3 两模式均 0（无进球）。
- 已知约束/后续：
  - Go 端 `cmd/app/main.go` 构造 `pipeline.run.json` 时读 `configs/pipeline.sample.json` 模板，
    因此只需在模板里加 `ball_detector` 段即可让桌面端任务使用 YOLO 球检测（需置 `enabled:true`）。
  - 主循环每帧全图 YOLO（imgsz=640）比原 MOG2 慢（IMG_3 1080p 全程约 66s vs 13s，约 5x）；
    后续可加检测区域裁剪或帧级缓存优化，当前先保证正确性。

## Requirements
- 使用 `gin_fram` 风格重构 Go 服务。
- 前后端分离，提供标准 HTTP 接口，支持云部署与移动端调用。
- 保留桌面版调试应用，桌面端也走 HTTP 接口。
- 新增登录鉴权与用户任务隔离。

## Research Findings
- 当前桌面服务入口在 `app-go/cmd/app/main.go`，路由与任务状态管理高度耦合在单文件中。
- 当前桌面前端已通过 HTTP 调用接口（`fetch('/api/v1/...')`），天然适合迁移到远程 API。
- 当前桌面壳 `cmd/desktop/main.go` 本质是本地启动 server + webview，可保留为“本地模式客户端”。
- `gin_fram` 的核心模式是：
  - `framework.App` 容器
  - Provider 启动流程
  - `router/controller/logic/repository` 分层
  - 中间件链统一装配
- 现有业务核心能力（Python 检测、ffmpeg 剪辑）已在 `internal/engine`、`internal/pipeline`、`internal/ffmpeg`，可复用。

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| 新增“云 API 入口”并逐步迁移接口 | 避免一次性改动过大影响桌面版 |
| 保留旧桌面入口直到云 API 稳定 | 保障现网/测试连续可用 |
| 先落地鉴权与用户隔离，再迁移任务接口 | 先建立安全边界 |
| 鉴权首版采用 `JWT(access)`，后续再扩展 refresh 与会话管理 | 快速可用，易于演进 |

## Implementation Progress (2026-03-22)
- 已新增云 API 入口：`app-go/cmd/cloud/main.go`。
- 已新增 gin_fram 风格分层骨架：
  - `app-go/internal/cloudapi/framework/*`
  - `app-go/internal/cloudapi/router/*`
  - `app-go/internal/cloudapi/controller/*`
  - `app-go/internal/cloudapi/logic/*`
  - `app-go/internal/cloudapi/repository/*`
  - `app-go/internal/cloudapi/model/*`
- 已实现鉴权基础接口：
  - `POST /api/v1/auth/login`
  - `GET /api/v1/auth/me`
- 已实现任务隔离基础接口（按 `user_id`）：
  - `POST /api/v1/jobs`
  - `GET /api/v1/jobs`
  - `GET /api/v1/jobs/:id`
  - `POST /api/v1/jobs/:id/terminate`
- 首版任务执行是“异步占位流程”（内存仓库 + 模拟状态流转），后续 Phase E 替换为真实 `pipeline` 调用。

## Risks
| Risk | Mitigation |
|------|------------|
| 任务执行链路迁移期间出现回归 | 双入口并行，逐接口切换 |
| 视频文件云端传输成本高 | 首版先保证 API 能力，存储策略分阶段优化 |
| 任务取消不彻底 | 全链路引入 `context cancel`（已开始改造） |

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

## 2026-03-09 自动篮框检测方案规划（新增）
- 当前依赖点确认：
  - 任务启动接口要求前端传入 `hoop`（`SingleStartRequest.Hoop` 为 required）。
  - 检测 ROI 全部从 `hoop(cx, cy, r)` 派生（`setup_regions`）。
- 推荐方向：
  - 采用“OpenCV 视觉线索 + 跨帧一致性聚类 + 检测链路自校验”的三层方案，先不引入 YOLO，保持打包体积和运行依赖稳定。
  - 在服务端新增自动篮框检测步骤，写回 `pipeline.run.json` 的 `hoop`，前端改为“自动检测优先，手工改框可选”。
- 关键工程点：
  - 新增 `engine-py/auto_detect_hoop.py`（输出 `hoop + confidence + debug artifacts`）。
  - Go 端新增调用封装并在单任务启动前执行自动检测。
  - 前端增加“自动检测中/成功/失败”状态和检测结果预览。

## 2026-03-09 自动篮框实施计划（YOLO->ONNX->时序融合）
- 目标链路：
  - 训练阶段：`YOLO + 篮框标注数据` 微调得到专用模型。
  - 部署阶段：将微调模型导出 `ONNX`，在应用中执行推理。
  - 决策阶段：多帧结果做时序稳定性打分并做短时自校验。
- 推荐里程碑：
  - M1（训练基线）：产出 `best.pt`，并形成指标基线。
  - M2（部署可用）：产出 `hoop_detector.onnx`，跑通候选框输出。
  - M3（端到端可用）：自动输出 `hoop(cx,cy,r)` 并接入现有剪辑任务。
  - M4（质量验收）：在评测集上达到上线阈值。
- 建议验收阈值（首版）：
  - 篮框中心误差中位数 <= 20px（1080p）。
  - 半径相对误差中位数 <= 15%。
  - 自动篮框成功率 >= 95%（失败可自动二次搜索）。
  - 对最终进球事件 F1 下降不超过 3%（相对手工框选基线）。

## 2026-03-09 Phase 9 已落地模板（新增）
- 新增标注规范文档：`docs/auto_hoop_annotation.zh-CN.md`。
- 新增训练目录说明：`training/hoop_detector/README.zh-CN.md`。
- 新增数据集配置模板：`training/hoop_detector/dataset.yaml.template`。
- 预创建数据集目录骨架：`training/hoop_detector/datasets/hoop_v1/{images,labels}/{train,val,test}`。
- 新增抽帧脚本：`scripts/extract_hoop_label_frames.py`（按视频级别划分 train/val/test，便于快速生成待标注样本）。
- 新增训练脚本：`scripts/train_hoop_detector.sh`。
- 新增 ONNX 导出脚本：`scripts/export_hoop_onnx.sh`。
- README 新增“自动篮框（YOLO->ONNX）准备”章节，便于执行。

## 2026-03-10 单视频冒烟验证结果（新增）
- 冒烟输入视频：
  - `/Users/quzhengyang/www/360.cn/Python/highLight/IMG_1556-tmp.MOV`
- 已验证链路：
  - 抽帧：`extract_hoop_label_frames.py` 正常产出样本。
  - 训练：`train_hoop_detector.sh` 在 1 epoch（smoke 数据集）下可跑通并产出 `best.pt`。
  - 导出：`export_hoop_onnx.sh` 正常产出 `best.onnx`。
  - 推理：ONNX Runtime 加载与批量预测命令可执行。
- 备注：
  - 冒烟数据使用了“临时标签 + 极少样本 + 1 epoch”，目的是验证流程可跑通，不代表模型精度。

## 2026-03-15 真实数据准备进展（新增）
- 已从用户采集视频目录抽帧到 `hoop_v1`：
  - 输入目录：`/Users/quzhengyang/www/360.cn/Python/highLight`
  - 抽帧汇总：`training/hoop_detector/datasets/hoop_v1/frame_extract_summary.json`
- 已按视频级拆分到 `train/val`（当前 2 条视频）：
  - train 图片：260
  - val 图片：38
- 已生成训练配置：
  - `training/hoop_detector/dataset.yaml`
- 当前阻塞点：
  - `hoop_v1` 的真实标注文件尚未完成（train/val 标签数均为 0），还不能启动有效训练。

## 2026-03-22 自动篮框确认流程落地（新增）
- 已落地目标流程：
  1) 自动检测篮框；
  2) 未检测到时，用户手动画框并回填；
  3) 检测到多个候选时，用户选择并回填；
  4) 检测到 1 个候选时，用户确认后回填。
- 关键实现：
  - Python 引擎 `detect_goals.py` 新增 `--detect-hoop-only` 模式，输出 `none/single/multiple`、候选列表与预览图。
  - Go 后端新增 `POST /api/v1/hoop/detect`，作为任务启动前的候选检测接口。
  - 前端 `web/index.html` 改为“先自动检测，再确认回填”的向导交互。
  - `single-job/start` 调整为必须携带已确认 `hoop`，并关闭任务阶段二次自动篮框，保证可复现。
- 当前已知约束：
  - 自动篮框推理依赖 `opencv-python + numpy`；若运行环境缺失会返回失败并走手工兜底。

## 2026-09-23 球检测微调基线（ball_v1_n）结果（新增）
- 背景：现有进球检测依赖 MOG2 背景差分 + 固定 ROI，对手持/移动机位失效。
  目标是用「YOLO 微调单类球检测」替代，先建一个可量化基线。
- 数据：公开数据集 `koppolusameer/basketball-coco-player-detection`（CC BY 4.0，
  NBA 转播片段，COCO 标注）。用 `scripts/convert_ball_coco_to_yolo.py` 抽取
  `category_id==1`（ball），转成 YOLO 单类。
  - 拆分：train 1943 / valid 166 / test 151（含球图）。
  - 球框极小：576 图中位约 10×17 px（小目标，是召回偏低的主因之一）。
- 训练：YOLOv8n 微调，`imgsz=640, batch=16, device=mps, epochs=100(patience=30)`。
  - 实际跑 89 epoch 早停，最佳 epoch 59，耗时 2.81h。
  - 指标（ultralytics val，test 划分）：P=0.948 R=0.815 mAP50=0.905 mAP50-95=0.538。
- **关键对比（同数据、同 conf=0.15、IoU>=0.5，ball_v1/test）**：
  | 模型 | images_with_det | TP | FP | FN | P | R | F1 |
  |------|-----------------|----|----|----|---|---|----|
  | COCO 零样本 yolov8n(c32) | 3/151 | 0 | 3 | 151 | 0.00 | 0.00 | **0.00** |
  | 微调 ball_v1_n(c0) | 134/151 | 129 | 17 | 22 | 0.884 | 0.854 | **0.869** |
  - 结论：COCO 的 `sports ball` 对本场景几乎完全失效（151 GT 里只 0 个命中）；
    微调后 F1≈0.87，是数量级的提升。
- 手持真机视频（逐帧采样，同 imgsz=640，画面能否检出球）：
  | 视频 | COCO 零样本 | 微调 | 提升 |
  |------|------------|------|------|
  | 582055(高晃) | 9.5% | 23.8% | 2.5x |
  | 371be0(中晃) | 23.8% | 47.6% | 2.0x |
  | IMG_3(低晃) | 0.0% | 55.0% | ∞ |
  | 均值 | **11.1%** | **42.1%** | **3.8x** |
  - 与既有“零样本 COCO 命中率 14-16%”基线一致，微调后抬到约 42%。
- 部署产物：`training/ball_detector/runs/ball_v1_n/weights/best.onnx`
  （固定输入 640，输出 `1x5x8400` 裸检测，未内置 NMS，供
  `engine-py/ball_detector.py` 的 `OnnxDnnBackend` 自做 NMS）。
- 已知约束/后续：
  - ONNX 固定 640 输入，`cv2.dnn` 改 imgsz 会触发 DFL Reshape 报错；训练也是
    640，故推理固定 640。若要 960 推理需重新导出（动态轴/onnxruntime）。
  - 目前是「转播片段」训练 → 手持/低角度视频存在域差；手持召回仍有提升空间，
    后续建议用用户自有视频抽帧做增量微调。
  - 评测产物：`training/ball_detector/runs/ball_v1_n/eval_report.json`。

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
