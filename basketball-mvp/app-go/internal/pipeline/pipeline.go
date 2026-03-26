package pipeline

import (
	"context"
	"fmt"
	"path/filepath"

	"basketball-mvp/app-go/internal/config"
	"basketball-mvp/app-go/internal/engine"
	"basketball-mvp/app-go/internal/ffmpeg"
	"basketball-mvp/app-go/internal/models"
)

// ResolveOutputDir 统一解析输出目录路径。
//
// 输入:
//   - projectRoot: 项目根目录（用于拼接相对路径）。
//   - outputDir: 任务配置中的输出目录（可能是相对路径）。
//
// 返回:
//   - 可直接用于读写文件的绝对或规范化路径。
func ResolveOutputDir(projectRoot, outputDir string) string {
	// 兼容相对路径（开发态）与绝对路径（桌面态/打包态）。
	absOutDir := outputDir
	if !filepath.IsAbs(absOutDir) {
		absOutDir = filepath.Join(projectRoot, absOutDir)
	}
	return absOutDir
}

// Run 执行单个任务的完整流水线。
//
// 输入:
//   - projectRoot: 项目根目录。
//   - job: 当前任务对象（会写入检测结果、片段路径、最终视频路径）。
//   - progressFile: Python 检测进度文件路径。
//   - onProgress: 进度回调，可为空。
//
// 返回:
//   - error: 任一阶段失败则返回错误；成功返回 nil。
func Run(
	ctx context.Context,
	projectRoot string,
	job *models.Job,
	progressFile string,
	onProgress func(models.JobProgress),
) error {
	// 流水线顺序固定：detect -> cut clips -> merge。
	// 这样便于前端按 stage 展示，也便于定位失败环节。
	cfg, err := config.LoadPipelineConfig(job.ConfigPath)
	if err != nil {
		return err
	}

	absOutDir := ResolveOutputDir(projectRoot, job.OutputDir)
	if onProgress != nil {
		// 检测阶段占整体进度前段；更细粒度由 Python 侧进度文件补充。
		onProgress(models.JobProgress{Stage: "detecting", Percent: 2})
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}

	detectJSON, events, err := engine.DetectGoals(ctx, projectRoot, job.VideoPath, job.ConfigPath, absOutDir, progressFile, job.ManualGoals)
	if err != nil {
		return fmt.Errorf("detect goals: %w", err)
	}
	job.DetectionJSON = detectJSON
	job.Events = events
	if ctx.Err() != nil {
		return ctx.Err()
	}

	clips, err := ffmpeg.CutClips(ctx, job.VideoPath, absOutDir, events, cfg, func(done, total int) {
		if onProgress == nil {
			return
		}
		// 剪切阶段映射到 72~95%，避免和检测/合并阶段进度重叠。
		pct := 72.0
		if total > 0 {
			pct = 72.0 + (23.0*float64(done))/float64(total)
		}
		onProgress(models.JobProgress{
			Stage:   "cutting_clips",
			Percent: pct,
		})
	})
	if err != nil {
		return fmt.Errorf("cut clips: %w", err)
	}
	job.ClipPaths = clips
	if ctx.Err() != nil {
		return ctx.Err()
	}

	if onProgress != nil {
		// 合并一般耗时短，保留一个独立 stage 便于用户理解当前动作。
		onProgress(models.JobProgress{Stage: "merging", Percent: 96})
	}
	highlight, err := ffmpeg.MergeHighlight(ctx, absOutDir, clips)
	if err != nil {
		return fmt.Errorf("merge highlight: %w", err)
	}
	job.HighlightPath = highlight
	if onProgress != nil {
		onProgress(models.JobProgress{Stage: "done", Percent: 100})
	}
	return nil
}
