# Task Plan: 跨平台无外部依赖安装包

## Goal
产出可分发给测试同学的安装包：支持 macOS Apple 芯片、macOS Intel、Windows，运行时不要求额外安装 Python/FFmpeg。

## Current Phase
Phase 9

## Phases

### Phase 1: 需求确认与现状梳理
- [x] 确认目标平台（macOS arm64 / macOS amd64 / Windows）
- [x] 梳理当前依赖点（Python、FFmpeg、架构）
- [x] 建立任务规划文件
- **Status:** complete

### Phase 2: 运行时探测与代码改造
- [x] 增加内置 Python 探测优先级
- [x] 增加内置 FFmpeg 探测优先级
- [x] 让桌面启动时注入内置依赖环境变量
- **Status:** complete

### Phase 3: 打包脚本改造（含多架构）
- [x] macOS 脚本支持 arm64/amd64/universal 输出
- [x] Windows 脚本支持内置 runtime 目录
- [x] 统一拷贝 `runtime/<platform>-<arch>/...`
- **Status:** complete

### Phase 4: 文档与验证
- [x] 补充打包前准备步骤
- [x] 补充“无环境依赖”验证清单
- [x] 本地可执行验证
- **Status:** complete

### Phase 5: 交付
- [x] 汇总限制与后续动作（签名、公证、CI）
- [x] 给出测试同学使用说明
- **Status:** complete

### Phase 6: 自动化 runtime 准备
- [x] 提供 macOS 自动下载/组装脚本
- [x] 提供 Windows 自动下载/组装脚本
- [x] 提供 runtime 校验与强制打包联动
- **Status:** complete

### Phase 7: 检测链路审查 + 注释增强
- [x] 审查检测与编排代码中的不合理点
- [x] 落地低风险优化（不改变业务意图）
- [x] 为核心类/函数/方法补充通俗注释（含入参、出参）
- [x] 编译/语法校验并汇总结果
- **Status:** complete

### Phase 8: 自动篮框检测方案规划
- [x] 梳理当前“hoop 参数输入点”和“ROI 派生逻辑”
- [x] 给出不依赖手工框选的自动检测方案（算法分层 + 兜底机制）
- [x] 给出可执行实施计划（阶段、产出、验收指标、风险）
- **Status:** complete

### Phase 9: 篮框数据准备与 YOLO 微调训练
- [x] 明确数据标准（标注规范、分辨率、类别定义）
- [ ] 构建训练/验证集（建议先 800~1500 帧，单类 hoop）
- [ ] 基于 YOLOv8n/s 做微调，输出 best.pt 与评估报告
- [ ] 记录指标（P/R/mAP50/mAP50-95）并确定基线模型
- **Status:** in_progress

### Phase 10: ONNX 推理接入（候选篮框生成）
- [x] 导出 ONNX（固定输入尺寸，opset 与动态轴策略确认）
- [x] 新增 Python 推理模块（读取视频采样帧，输出候选 hoop）
- [x] 新增调试产物（候选框可视化、置信度、每帧结果）
- [x] 校验跨平台 runtime 依赖（mac arm/intel、windows）
- **Status:** complete

### Phase 11: 时序稳定性融合与自动决策
- [x] 对候选框做跨帧聚类（位置、半径、持续帧数）
- [x] 定义稳定性得分并选取 top-k 候选
- [ ] 引入短时链路自校验（复用 detect_goals 逻辑）
- [ ] 输出最终 `hoop(cx,cy,r)` + `confidence` + `source=auto`
- **Status:** in_progress

### Phase 12: 服务端/前端接入与灰度发布
- [x] 新增 `POST /api/v1/hoop/detect`，接入自动检测前置步骤并写回临时 config
- [x] 改造前端为“自动检测优先 + 候选确认/手工兜底 + 回填 hoop”流程
- [x] 改造 `single-job/start` 为“必须带已确认 hoop”，避免任务阶段二次自动漂移
- [ ] 增加失败兜底策略（低置信度时自动二次搜索）
- **Status:** in_progress

### Phase 13: 评估、调参与上线验收
- [ ] 建立评测集（不同机位、光照、清晰度）
- [ ] 统计误差与成功率，迭代阈值与融合权重
- [ ] 对比“手工框选 vs 自动篮框”进球检测最终效果
- [ ] 形成上线标准与回滚策略
- **Status:** pending

## Key Questions
1. 是否采用单个 universal mac 包，还是两个独立架构包（arm64/amd64）？
2. Python 运行时是“本地已准备 runtime 目录复制”还是“打包时自动下载”？

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| 先实现“runtime 目录内置 + 代码优先探测” | 改造最小、可逐步落地，不阻塞后续自动下载方案 |
| FFmpeg 通过环境变量 `BASKETBALL_MVP_FFMPEG` 指定 | 与现有 `BASKETBALL_MVP_PYTHON` 风格一致，兼容 CLI/桌面 |
| runtime 自动下载默认取 GitHub 最新 release | 降低手工维护 URL 成本，覆盖多架构 |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| 暂无 | 1 | - |
