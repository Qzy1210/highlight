package engine

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"

	"basketball-mvp/app-go/internal/models"
)

// DetectGoals 调用 Python 引擎完成进球检测。
//
// 输入:
//   - projectRoot: 项目根目录，用于定位脚本。
//   - videoPath: 输入视频绝对路径。
//   - configPath: 本次任务配置路径。
//   - outputDir: 检测输出目录。
//   - progressFile: 进度文件路径；为空则不写检测进度。
//   - manualGoals: 手工时间点（非空时跳过自动检测逻辑）。
//
// 返回:
//   - string: goals.json 路径。
//   - []models.GoalEvent: 解析后的事件列表。
//   - error: 执行或解析失败时的错误。
func DetectGoals(projectRoot, videoPath, configPath, outputDir, progressFile string, manualGoals []float64) (string, []models.GoalEvent, error) {
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return "", nil, fmt.Errorf("mkdir output: %w", err)
	}

	// 统一约定检测输出位置，便于后续 Go 层和前端稳定读取。
	outJSON := filepath.Join(outputDir, "goals.json")
	debugDir := filepath.Join(outputDir, "debug")
	script := filepath.Join(projectRoot, "engine-py", "detect_goals.py")
	// 自动检测模式才强依赖 cv2/numpy；手工时间点模式不需要。
	pythonExec, err := pickPythonExecutable(projectRoot, len(manualGoals) == 0)
	if err != nil {
		return "", nil, err
	}

	args := []string{script, "--video", videoPath, "--config", configPath, "--output", outJSON, "--debug-dir", debugDir}
	if progressFile != "" {
		args = append(args, "--progress-file", progressFile)
	}
	if len(manualGoals) > 0 {
		// 手工模式用逗号拼接，复用同一 Python 入口，减少双实现分叉。
		parts := make([]string, 0, len(manualGoals))
		for _, v := range manualGoals {
			parts = append(parts, strconv.FormatFloat(v, 'f', -1, 64))
		}
		args = append(args, "--manual-goals", strings.Join(parts, ","))
	}

	cmd := exec.Command(pythonExec, args...)
	var logBuf bytes.Buffer
	cmd.Stdout = io.MultiWriter(os.Stdout, &logBuf)
	cmd.Stderr = io.MultiWriter(os.Stderr, &logBuf)
	if err := cmd.Run(); err != nil {
		detail := strings.TrimSpace(logBuf.String())
		if detail != "" {
			return "", nil, fmt.Errorf("run detect_goals.py with %s: %w\n%s", pythonExec, err, trimTail(detail, 1600))
		}
		return "", nil, fmt.Errorf("run detect_goals.py with %s: %w", pythonExec, err)
	}

	data, err := os.ReadFile(outJSON)
	if err != nil {
		return "", nil, fmt.Errorf("read goals output: %w", err)
	}

	var parsed struct {
		Events []models.GoalEvent `json:"events"`
	}
	if err := json.Unmarshal(data, &parsed); err != nil {
		return "", nil, fmt.Errorf("parse goals output: %w", err)
	}
	return outJSON, parsed.Events, nil
}

// pickPythonExecutable 选择可用的 Python 解释器。
//
// 输入:
//   - projectRoot: 项目根目录。
//   - needAutoDetectDeps: 是否要求解释器具备自动检测依赖（cv2+numpy）。
//
// 返回:
//   - string: 可执行解释器路径。
//   - error: 没有可用解释器或依赖不满足时返回错误。
func pickPythonExecutable(projectRoot string, needAutoDetectDeps bool) (string, error) {
	resolved := resolvePythonCandidates(projectRoot)
	if len(resolved) == 0 {
		return "", fmt.Errorf("python runtime not found. Set BASKETBALL_MVP_PYTHON, bundle runtime/python, or install python3")
	}
	if !needAutoDetectDeps {
		// 手工模式只要能运行解释器即可，不强制检查 opencv/numpy。
		return resolved[0], nil
	}

	// 自动检测模式逐个解释器做依赖探测，找到首个可用项即返回。
	failures := make([]string, 0, len(resolved))
	for _, exe := range resolved {
		ok, detail := checkAutoDetectDeps(exe)
		if ok {
			return exe, nil
		}
		if detail == "" {
			detail = "missing OpenCV/NumPy"
		}
		failures = append(failures, fmt.Sprintf("%s => %s", exe, detail))
	}
	return "", fmt.Errorf(
		"auto detect requires OpenCV+NumPy, but no usable python found.\nSet BASKETBALL_MVP_PYTHON to a ready interpreter, or run:\n<python> -m pip install opencv-python numpy\nChecked:\n- %s",
		strings.Join(failures, "\n- "),
	)
}

// resolvePythonCandidates 构建 Python 候选路径列表并去重。
//
// 输入:
//   - projectRoot: 项目根目录。
//
// 返回:
//   - []string: 可执行解释器路径列表，按优先级排序。
func resolvePythonCandidates(projectRoot string) []string {
	// 优先级：显式环境变量 -> 内置 runtime -> 本地 venv -> 系统 python。
	candidates := []string{}
	if env := strings.TrimSpace(os.Getenv("BASKETBALL_MVP_PYTHON")); env != "" {
		candidates = append(candidates, env)
	}
	candidates = append(candidates, embeddedPythonCandidates(projectRoot)...)

	if runtime.GOOS == "windows" {
		candidates = append(candidates,
			filepath.Join(projectRoot, ".venv", "Scripts", "python.exe"),
			filepath.Join(projectRoot, "venv", "Scripts", "python.exe"),
			"python",
			"python3",
		)
	} else {
		candidates = append(candidates,
			filepath.Join(projectRoot, ".venv", "bin", "python3"),
			filepath.Join(projectRoot, ".venv", "bin", "python"),
			filepath.Join(projectRoot, "venv", "bin", "python3"),
			filepath.Join(projectRoot, "venv", "bin", "python"),
		)
		if runtime.GOOS == "darwin" {
			// 补充常见 Homebrew / 系统路径，降低开箱失败率。
			candidates = append(candidates, "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3")
		}
		candidates = append(candidates, "python3", "python")
	}

	// 去重后保持原顺序，确保“前面的优先级更高”语义成立。
	seen := map[string]struct{}{}
	out := make([]string, 0, len(candidates))
	for _, c := range candidates {
		if c == "" {
			continue
		}
		resolved, ok := resolveExecutable(c)
		if !ok {
			continue
		}
		if _, exists := seen[resolved]; exists {
			continue
		}
		seen[resolved] = struct{}{}
		out = append(out, resolved)
	}
	return out
}

// embeddedPythonCandidates 返回内置 runtime 下的 Python 路径候选。
func embeddedPythonCandidates(projectRoot string) []string {
	base := filepath.Join(projectRoot, "runtime", "python")
	if runtime.GOOS == "windows" {
		return []string{
			filepath.Join(base, "python.exe"),
			filepath.Join(base, "Scripts", "python.exe"),
		}
	}
	return []string{
		filepath.Join(base, "bin", "python3"),
		filepath.Join(base, "bin", "python"),
	}
}

// resolveExecutable 校验并解析可执行文件路径。
//
// 返回:
//   - string: 可执行文件绝对路径（或原路径）。
//   - bool: 是否可用。
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

// checkAutoDetectDeps 检查自动检测依赖是否可导入。
//
// 返回:
//   - bool: 是否通过。
//   - string: 失败原因（为空表示无附加信息）。
func checkAutoDetectDeps(pythonExec string) (bool, string) {
	// 用最小 import 语句探测运行环境是否满足自动检测需求。
	cmd := exec.Command(pythonExec, "-c", "import cv2, numpy")
	var merged bytes.Buffer
	cmd.Stdout = &merged
	cmd.Stderr = &merged
	if err := cmd.Run(); err != nil {
		msg := strings.TrimSpace(merged.String())
		if msg == "" {
			msg = err.Error()
		}
		return false, msg
	}
	return true, ""
}

// trimTail 截取字符串末尾 max 长度，用于压缩错误日志。
func trimTail(s string, max int) string {
	if len(s) <= max {
		return s
	}
	return s[len(s)-max:]
}
