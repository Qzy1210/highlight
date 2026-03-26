package main

import (
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	webview "github.com/webview/webview_go"
)

type nativeDialogResult struct {
	// VideoPath: 选择的视频路径（video 对话框返回）。
	VideoPath string `json:"video_path,omitempty"`
	// Directory: 选择的目录路径（directory 对话框返回）。
	Directory string `json:"directory,omitempty"`
	// Error: 打开对话框失败时的错误信息。
	Error string `json:"error,omitempty"`
}

// main 启动桌面壳：拉起后端服务并打开 WebView 页面。
func main() {
	exe, err := os.Executable()
	if err != nil {
		fmt.Printf("resolve executable failed: %v\n", err)
		os.Exit(1)
	}
	exeDir := filepath.Dir(exe)

	projectRoot := os.Getenv("BASKETBALL_MVP_ROOT")
	if projectRoot == "" {
		// 打包后默认从可执行文件相对路径定位内置 project 目录。
		projectRoot = detectEmbeddedProject(exeDir)
	}
	dataRoot := os.Getenv("BASKETBALL_MVP_DATA")
	if dataRoot == "" {
		dataRoot = defaultDataRoot()
	}
	if err := os.MkdirAll(dataRoot, 0o755); err != nil {
		fmt.Printf("create data root failed: %v\n", err)
		os.Exit(1)
	}

	serverBin := filepath.Join(exeDir, serverBinaryName())
	if _, err := os.Stat(serverBin); err != nil {
		fmt.Printf("server binary missing: %v\n", err)
		os.Exit(1)
	}

	serverCmd := exec.Command(serverBin)
	// 桌面壳负责把运行时路径透传给后端服务进程。
	serverEnv := append(os.Environ(),
		"BASKETBALL_MVP_ROOT="+projectRoot,
		"BASKETBALL_MVP_DATA="+dataRoot,
	)
	if py := detectPythonForDesktop(exeDir, projectRoot); py != "" {
		serverEnv = append(serverEnv, "BASKETBALL_MVP_PYTHON="+py)
		fmt.Printf("use python runtime: %s\n", py)
	}
	if ff := detectFFmpegForDesktop(exeDir, projectRoot); ff != "" {
		serverEnv = append(serverEnv, "BASKETBALL_MVP_FFMPEG="+ff)
		fmt.Printf("use ffmpeg binary: %s\n", ff)
	}
	serverCmd.Env = serverEnv
	serverCmd.Stdout = os.Stdout
	serverCmd.Stderr = os.Stderr
	if err := serverCmd.Start(); err != nil {
		fmt.Printf("start server failed: %v\n", err)
		os.Exit(1)
	}
	defer func() {
		if serverCmd.Process != nil {
			_ = serverCmd.Process.Kill()
		}
		_, _ = serverCmd.Process.Wait()
	}()

	if err := waitHealth("http://127.0.0.1:8088/health", 12*time.Second); err != nil {
		fmt.Printf("server health check failed: %v\n", err)
		os.Exit(1)
	}

	w := webview.New(false)
	defer w.Destroy()
	bindDesktopDialogs(w)
	w.SetTitle("Basketball MVP")
	w.SetSize(1320, 900, webview.HintNone)
	// 使用启动时间作为 query 参数，避免 WebView 命中旧缓存页面。
	w.Navigate(fmt.Sprintf("http://127.0.0.1:8088/app/?v=%d", time.Now().UnixNano()))
	w.Run()
}

// bindDesktopDialogs 把原生文件对话框能力注入前端 JS（window.desktopOpenXxx）。
func bindDesktopDialogs(w webview.WebView) {
	_ = w.Bind("desktopOpenVideoDialog", func() nativeDialogResult {
		path, err := openVideoSelectionDialog()
		if err != nil {
			return nativeDialogResult{Error: err.Error()}
		}
		return nativeDialogResult{VideoPath: path}
	})
	_ = w.Bind("desktopOpenDirectoryDialog", func() nativeDialogResult {
		path, err := openDirectorySelectionDialog()
		if err != nil {
			return nativeDialogResult{Error: err.Error()}
		}
		return nativeDialogResult{Directory: path}
	})
}

// detectEmbeddedProject 根据可执行文件位置回溯内置 project 目录。
func detectEmbeddedProject(exeDir string) string {
	// 兼容 macOS .app 与 Windows 普通目录结构。
	cands := []string{
		filepath.Clean(filepath.Join(exeDir, "..", "Resources", "project")),
		filepath.Clean(filepath.Join(exeDir, "resources", "project")),
		filepath.Clean(filepath.Join(exeDir, "..")),
	}
	for _, c := range cands {
		if _, err := os.Stat(filepath.Join(c, "engine-py")); err == nil {
			return c
		}
	}
	return filepath.Clean(filepath.Join(exeDir, ".."))
}

// serverBinaryName 返回当前平台后端服务二进制文件名。
func serverBinaryName() string {
	if runtime.GOOS == "windows" {
		return "basketball_mvp_server.exe"
	}
	return "basketball_mvp_server"
}

// defaultDataRoot 返回桌面壳默认数据目录。
func defaultDataRoot() string {
	if cfg, err := os.UserConfigDir(); err == nil && cfg != "" {
		return filepath.Join(cfg, "BasketballMVP", "workspace")
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".basketballmvp", "workspace")
}

// waitHealth 轮询健康检查接口，直到服务可用或超时。
func waitHealth(url string, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		resp, err := http.Get(url)
		if err == nil && resp != nil {
			_ = resp.Body.Close()
			if resp.StatusCode >= 200 && resp.StatusCode < 300 {
				return nil
			}
		}
		time.Sleep(250 * time.Millisecond)
	}
	return fmt.Errorf("timeout waiting for %s", url)
}

// detectPythonForDesktop 解析桌面态可用 Python（环境变量优先）。
func detectPythonForDesktop(exeDir, projectRoot string) string {
	if env := strings.TrimSpace(os.Getenv("BASKETBALL_MVP_PYTHON")); env != "" {
		if isFile(env) {
			return env
		}
	}

	cands := []string{}
	if runtime.GOOS == "windows" {
		// 优先包内 runtime，再退回开发环境虚拟环境。
		cands = append(cands,
			filepath.Join(projectRoot, "runtime", "python", "python.exe"),
			filepath.Join(projectRoot, "runtime", "python", "Scripts", "python.exe"),
			filepath.Join(projectRoot, ".venv", "Scripts", "python.exe"),
			filepath.Join(projectRoot, "venv", "Scripts", "python.exe"),
			filepath.Clean(filepath.Join(exeDir, "..", "..", "Resources", "project", "runtime", "python", "python.exe")),
			filepath.Clean(filepath.Join(exeDir, "..", "..", "Resources", "project", "runtime", "python", "Scripts", "python.exe")),
			filepath.Clean(filepath.Join(exeDir, "..", "..", "..", "..", ".venv", "Scripts", "python.exe")),
			filepath.Clean(filepath.Join(exeDir, "..", "..", "..", "..", "venv", "Scripts", "python.exe")),
		)
	} else {
		// macOS/Linux 同样先找包内 runtime，再找工程本地 venv。
		cands = append(cands,
			filepath.Join(projectRoot, "runtime", "python", "bin", "python3"),
			filepath.Join(projectRoot, "runtime", "python", "bin", "python"),
			filepath.Join(projectRoot, ".venv", "bin", "python3"),
			filepath.Join(projectRoot, ".venv", "bin", "python"),
			filepath.Join(projectRoot, "venv", "bin", "python3"),
			filepath.Join(projectRoot, "venv", "bin", "python"),
			filepath.Clean(filepath.Join(exeDir, "..", "..", "Resources", "project", "runtime", "python", "bin", "python3")),
			filepath.Clean(filepath.Join(exeDir, "..", "..", "Resources", "project", "runtime", "python", "bin", "python")),
			filepath.Clean(filepath.Join(exeDir, "..", "..", "..", "..", ".venv", "bin", "python3")),
			filepath.Clean(filepath.Join(exeDir, "..", "..", "..", "..", ".venv", "bin", "python")),
			filepath.Clean(filepath.Join(exeDir, "..", "..", "..", "..", "venv", "bin", "python3")),
			filepath.Clean(filepath.Join(exeDir, "..", "..", "..", "..", "venv", "bin", "python")),
		)
	}

	for _, p := range cands {
		if isFile(p) {
			return p
		}
	}
	return ""
}

// detectFFmpegForDesktop 解析桌面态可用 ffmpeg（环境变量优先）。
func detectFFmpegForDesktop(exeDir, projectRoot string) string {
	if env := strings.TrimSpace(os.Getenv("BASKETBALL_MVP_FFMPEG")); env != "" {
		if isFile(env) {
			return env
		}
	}

	name := "ffmpeg"
	if runtime.GOOS == "windows" {
		name = "ffmpeg.exe"
	}
	cands := []string{
		filepath.Join(projectRoot, "runtime", "bin", name),
		filepath.Clean(filepath.Join(exeDir, "..", "..", "Resources", "project", "runtime", "bin", name)),
	}
	for _, p := range cands {
		if isFile(p) {
			return p
		}
	}
	return ""
}

// isFile 判断路径是否为有效文件。
func isFile(path string) bool {
	if strings.TrimSpace(path) == "" {
		return false
	}
	st, err := os.Stat(path)
	return err == nil && !st.IsDir()
}
