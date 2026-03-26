package ffmpeg

import (
	"bytes"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"

	"basketball-mvp/app-go/internal/models"
)

// debugArtifactsDir 返回调试产物目录（统一放在 output/debug）。
func debugArtifactsDir(outputDir string) string {
	// 统一把中间产物放在 debug/ 下，避免污染业务结果目录。
	return filepath.Join(outputDir, "debug")
}

// CutClips 按事件时间切出视频片段。
//
// 输入:
//   - videoPath: 原视频路径。
//   - outputDir: 任务输出目录。
//   - events: 进球事件列表（time_sec 为切片中心参考）。
//   - cfg: 切片窗口配置（pre_seconds/post_seconds）。
//   - onProgress: 切片进度回调，可为空。
//
// 返回:
//   - []string: 每个片段文件路径（按事件顺序）。
//   - error: 切片失败时返回错误。
func CutClips(
	videoPath, outputDir string,
	events []models.GoalEvent,
	cfg models.PipelineConfig,
	onProgress func(done, total int),
) ([]string, error) {
	if len(events) == 0 {
		return nil, fmt.Errorf("no goal events")
	}
	// clip 片段也保存在 debug 目录，便于问题排查与复现。
	clipsDir := filepath.Join(debugArtifactsDir(outputDir), "clips")
	if err := os.MkdirAll(clipsDir, 0o755); err != nil {
		return nil, fmt.Errorf("mkdir clips: %w", err)
	}
	ffmpegBin, err := ffmpegExecutable()
	if err != nil {
		return nil, err
	}

	paths := make([]string, 0, len(events))
	if onProgress != nil {
		onProgress(0, len(events))
	}
	for i, ev := range events {
		start := ev.TimeSec - cfg.PreSeconds
		if start < 0 {
			start = 0
		}
		duration := cfg.PreSeconds + cfg.PostSeconds
		outPath := filepath.Join(clipsDir, fmt.Sprintf("goal_%03d.mp4", i+1))

		// 每个事件单独切片，后续再统一合并。
		cmd := exec.Command(
			ffmpegBin, "-y",
			"-ss", formatSec(start),
			"-i", videoPath,
			"-t", formatSec(duration),
			"-c:v", "libx264", "-preset", "fast", "-crf", "22",
			"-c:a", "aac",
			outPath,
		)
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		if err := cmd.Run(); err != nil {
			return nil, fmt.Errorf("cut clip %d: %w", i+1, err)
		}
		paths = append(paths, outPath)
		if onProgress != nil {
			onProgress(i+1, len(events))
		}
	}
	return paths, nil
}

// MergeHighlight 将片段合并为最终集锦视频。
//
// 输入:
//   - outputDir: 任务输出目录。
//   - clips: 已切好的片段路径。
//
// 返回:
//   - string: 合并后 `highlight.mp4` 路径。
//   - error: 主流程与兜底流程都失败时返回错误。
func MergeHighlight(outputDir string, clips []string) (string, error) {
	if len(clips) == 0 {
		return "", fmt.Errorf("no clips to merge")
	}
	for i, p := range clips {
		st, err := os.Stat(p)
		if err != nil {
			return "", fmt.Errorf("clip missing (%d): %s: %w", i+1, p, err)
		}
		if st.Size() <= 0 {
			return "", fmt.Errorf("clip empty (%d): %s", i+1, p)
		}
	}

	debugDir := debugArtifactsDir(outputDir)
	if err := os.MkdirAll(debugDir, 0o755); err != nil {
		return "", fmt.Errorf("mkdir debug dir: %w", err)
	}
	ffmpegBin, err := ffmpegExecutable()
	if err != nil {
		return "", err
	}

	listPath := filepath.Join(debugDir, "clips.txt")
	f, err := os.Create(listPath)
	if err != nil {
		return "", fmt.Errorf("create clips list: %w", err)
	}
	for _, p := range clips {
		// Escape single quotes for ffmpeg concat demuxer.
		escaped := strings.ReplaceAll(p, "'", "'\\''")
		if _, err := fmt.Fprintf(f, "file '%s'\n", escaped); err != nil {
			_ = f.Close()
			return "", fmt.Errorf("write clips list: %w", err)
		}
	}
	if err := f.Close(); err != nil {
		return "", fmt.Errorf("close clips list: %w", err)
	}

	highlightPath := filepath.Join(outputDir, "highlight.mp4")
	logPath := filepath.Join(debugDir, "merge.stderr.log")
	// 主路径：concat demuxer（输入同编码参数时最快最稳）。
	cmd := exec.Command(
		ffmpegBin, "-y",
		"-f", "concat", "-safe", "0",
		"-i", listPath,
		"-c:v", "libx264", "-preset", "fast", "-crf", "22",
		"-c:a", "aac",
		highlightPath,
	)
	cmd.Stdout = os.Stdout
	var stderr bytes.Buffer
	cmd.Stderr = io.MultiWriter(os.Stderr, &stderr)
	runErr := cmd.Run()
	if runErr == nil {
		_ = os.WriteFile(logPath, stderr.Bytes(), 0o644)
		return highlightPath, nil
	}
	// Fallback: concat filter without audio, more tolerant for mismatched streams.
	// 兜底路径：放弃音频并重编码视频，尽量保证“能导出”。
	var fallbackErr bytes.Buffer
	args := []string{"-y"}
	for _, p := range clips {
		args = append(args, "-i", p)
	}
	filter := "concat=n=" + strconv.Itoa(len(clips)) + ":v=1:a=0[v]"
	args = append(args,
		"-filter_complex", filter,
		"-map", "[v]",
		"-c:v", "libx264", "-preset", "fast", "-crf", "22",
		highlightPath,
	)
	fallback := exec.Command(ffmpegBin, args...)
	fallback.Stdout = os.Stdout
	fallback.Stderr = io.MultiWriter(os.Stderr, &fallbackErr)
	if fbRunErr := fallback.Run(); fbRunErr != nil {
		all := "primary:\n" + stderr.String() + "\n\nfallback:\n" + fallbackErr.String()
		_ = os.WriteFile(logPath, []byte(all), 0o644)
		return "", fmt.Errorf(
			"merge clips failed. primary=%v fallback=%v; see %s; tail=%s",
			runErr, fbRunErr, logPath, tail(all, 800),
		)
	}
	all := "primary_failed:\n" + stderr.String() + "\n\nfallback_succeeded:\n" + fallbackErr.String()
	_ = os.WriteFile(logPath, []byte(all), 0o644)
	return highlightPath, nil
}

// formatSec 将秒数格式化为 ffmpeg 参数字符串（毫秒精度）。
func formatSec(v float64) string {
	return fmt.Sprintf("%.3f", v)
}

// tail 返回字符串末尾 n 个字符。
func tail(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[len(s)-n:]
}

// ffmpegExecutable 按优先级解析 ffmpeg 可执行文件路径。
//
// 优先级:
//   1) 环境变量 BASKETBALL_MVP_FFMPEG
//   2) 系统 PATH 中的 ffmpeg
func ffmpegExecutable() (string, error) {
	if env := strings.TrimSpace(os.Getenv("BASKETBALL_MVP_FFMPEG")); env != "" {
		if p, ok := resolveExecutable(env); ok {
			return p, nil
		}
		return "", fmt.Errorf("BASKETBALL_MVP_FFMPEG is set but not executable: %s", env)
	}
	if p, err := exec.LookPath("ffmpeg"); err == nil {
		return p, nil
	}
	return "", fmt.Errorf("ffmpeg not found. Set BASKETBALL_MVP_FFMPEG, bundle runtime/bin/ffmpeg, or install ffmpeg in PATH")
}

// resolveExecutable 校验候选路径是否为可执行文件。
func resolveExecutable(candidate string) (string, bool) {
	if filepath.IsAbs(candidate) || strings.Contains(candidate, "/") || strings.Contains(candidate, `\`) {
		info, err := os.Stat(candidate)
		if err != nil || info.IsDir() {
			return "", false
		}
		return candidate, true
	}
	path, err := exec.LookPath(candidate)
	if err != nil {
		return "", false
	}
	return path, true
}
