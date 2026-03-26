# Task Plan: 跨平台无外部依赖安装包

## Goal
产出可分发给测试同学的安装包：支持 macOS Apple 芯片、macOS Intel、Windows，运行时不要求额外安装 Python/FFmpeg。

## Current Phase
Phase 7

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
