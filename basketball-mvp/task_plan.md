# Task Plan: 移动端云服务重构（gin_fram 风格）

## Goal
完成后端服务重构：基于 gin_fram 风格实现前后端分离标准 API，保留桌面版能力，新增登录鉴权与多用户任务隔离，支持云部署与移动端接入。

## Current Phase
Phase E

## Phases

### Phase A: 架构与协议冻结
- [x] 梳理现有桌面服务接口与运行模式
- [x] 研究 `gin_fram` 架构并输出迁移映射
- [x] 产出重构计划文档
- **Status:** complete

### Phase B: 云端 API 骨架搭建
- [x] 新增云端服务入口（独立于桌面入口）
- [x] 建立 gin_fram 风格分层目录（router/controller/logic/repository）
- [x] 建立统一响应与错误处理中间件
- **Status:** complete

### Phase C: 登录鉴权模块
- [x] 用户模型与账号存储（首版内存存储，预留 DB 扩展）
- [x] `POST /api/v1/auth/login` 与 `GET /api/v1/auth/me`
- [x] JWT 鉴权中间件（Access Token）
- **Status:** complete

### Phase D: 用户任务隔离
- [x] 任务模型增加 `user_id`
- [x] 任务创建/查询/终止按 `user_id` 隔离
- [x] 补充任务访问越权测试
- **Status:** complete

### Phase E: 业务接口迁移
- [ ] 迁移核心任务接口到新服务（create/status/reexport/terminate，接入真实 pipeline）
- [ ] 桌面端改为可配置 API BaseURL，继续使用 HTTP 调用
- [ ] 保留桌面特有接口（文件对话框、本地预览）在本地模式
- **Status:** in_progress

### Phase F: 云部署与发布
- [ ] 新增云部署配置（env、端口、存储路径）
- [ ] 日志/超时/限流/安全策略完善
- [ ] 发布验收与回滚文档
- **Status:** pending

## Key Questions
1. 首版用户体系是否只需要“账号密码 + JWT”，暂不接入短信/第三方登录？
2. 云端任务结果与视频文件存储策略（本地盘 / OSS）本轮是否先用本地盘占位？

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| 采用“双入口并行”（桌面入口保留 + 新云 API 入口） | 降低回归风险，保证开发连续性 |
| 优先做鉴权与隔离再迁移业务接口 | 先建立安全边界，避免后续返工 |
| 首版按 gin_fram 风格分层，不强依赖复制整个 gin_fram 仓库 | 兼顾落地速度与可维护性 |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| 暂无 | 1 | - |

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
