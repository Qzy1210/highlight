package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"

	"basketball-mvp/app-go/internal/config"
	"basketball-mvp/app-go/internal/ffmpeg"
	"basketball-mvp/app-go/internal/models"
	"basketball-mvp/app-go/internal/pipeline"
)

type server struct {
	// projectRoot: 项目根目录（用于定位 engine-py/configs/web）。
	projectRoot string
	// dataRoot: 运行时数据目录（settings、workspace 等）。
	dataRoot string
	// settingsPath: 设置文件路径。
	settingsPath string
	// mu: 保护 jobs/settings 的读写锁。
	mu sync.RWMutex
	// jobs: 内存任务表，key 为 job ID。
	jobs map[string]*models.Job
	// settings: 当前应用设置快照。
	settings models.AppSettings
	// seq: 任务 ID 自增序号。
	seq uint64
	// dialogOpen: 原子标记，防止多个系统文件对话框并发弹出。
	dialogOpen int32
}

// main 启动 HTTP 服务并注册前端所需接口。
func main() {
	r := gin.Default()
	s := &server{jobs: map[string]*models.Job{}}
	// 启动时先解析项目根目录与可用运行时（内置 runtime 优先）。
	s.projectRoot = detectProjectRoot()
	configureEmbeddedRuntimes(s.projectRoot)
	s.dataRoot = detectDataRoot(s.projectRoot)
	s.settingsPath = filepath.Join(s.dataRoot, "settings.json")
	if err := s.loadSettings(); err != nil {
		panic(err)
	}

	webDir := filepath.Join(s.projectRoot, "app-go", "web")
	if _, err := os.Stat(webDir); err != nil {
		webDir = "./web"
	}
	r.Static("/app", webDir)
	r.Static("/workspace", s.dataRoot)
	r.GET("/", func(c *gin.Context) { c.Redirect(http.StatusMovedPermanently, "/app/") })

	r.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	})

	r.GET("/api/v1/settings", s.getSettings)
	r.PUT("/api/v1/settings", s.updateSettings)
	r.POST("/api/v1/dialog/open-video", s.openVideoDialog)
	r.POST("/api/v1/dialog/open-directory", s.openDirectoryDialog)
	r.GET("/api/v1/file", s.serveLocalFile)

	r.POST("/api/v1/jobs", s.createJob)
	r.POST("/api/v1/single-job/start", s.startSingleJob)
	r.GET("/api/v1/jobs/:id", s.getJob)
	r.PUT("/api/v1/jobs/:id/events", s.updateJobEvents)
	r.POST("/api/v1/jobs/:id/reexport", s.reexportJob)

	if strings.TrimSpace(os.Getenv("OPEN_UI")) == "1" {
		go func() {
			time.Sleep(1200 * time.Millisecond)
			openURL("http://127.0.0.1:8088/app/")
		}()
	}
	_ = r.Run(":8088")
}

// detectProjectRoot 解析工程根目录。
//
// 优先级:
//  1. 环境变量 BASKETBALL_MVP_ROOT
//  2. 开发态：当前目录上一级
//  3. 打包态：从可执行文件附近回溯
func detectProjectRoot() string {
	if env := strings.TrimSpace(os.Getenv("BASKETBALL_MVP_ROOT")); env != "" {
		return env
	}
	// 开发态：通常在 app-go 目录启动，向上一层找工程根。
	if cwd, err := os.Getwd(); err == nil {
		cand := filepath.Clean(filepath.Join(cwd, ".."))
		if exists(filepath.Join(cand, "engine-py")) && exists(filepath.Join(cand, "configs")) {
			return cand
		}
	}
	// 打包态：从可执行文件相对路径回溯 Resources/project。
	if exe, err := os.Executable(); err == nil {
		exeDir := filepath.Dir(exe)
		cands := []string{
			filepath.Clean(filepath.Join(exeDir, "..", "Resources", "project")),
			filepath.Clean(filepath.Join(exeDir, "..")),
			filepath.Clean(filepath.Join(exeDir, "..", "..")),
		}
		for _, c := range cands {
			if exists(filepath.Join(c, "engine-py")) && exists(filepath.Join(c, "configs")) {
				return c
			}
		}
	}
	return filepath.Clean(filepath.Join(".."))
}

// detectDataRoot 解析可写数据目录（设置、导出工作区）。
func detectDataRoot(projectRoot string) string {
	if env := strings.TrimSpace(os.Getenv("BASKETBALL_MVP_DATA")); env != "" {
		return env
	}
	// 优先使用工程内 workspace；不可写时退回用户配置目录。
	defaultRoot := filepath.Join(projectRoot, "workspace")
	if isWritableDir(filepath.Dir(defaultRoot)) {
		return defaultRoot
	}
	if cfg, err := os.UserConfigDir(); err == nil && cfg != "" {
		return filepath.Join(cfg, "BasketballMVP", "workspace")
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".basketballmvp", "workspace")
}

// exists 判断路径是否存在。
func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// configureEmbeddedRuntimes 在外部未指定时注入内置运行时环境变量。
func configureEmbeddedRuntimes(projectRoot string) {
	// 若外部未显式指定，则自动注入内置 python/ffmpeg 路径。
	if strings.TrimSpace(os.Getenv("BASKETBALL_MVP_PYTHON")) == "" {
		if py := detectEmbeddedPython(projectRoot); py != "" {
			_ = os.Setenv("BASKETBALL_MVP_PYTHON", py)
		}
	}
	if strings.TrimSpace(os.Getenv("BASKETBALL_MVP_FFMPEG")) == "" {
		if ffmpeg := detectEmbeddedFFmpeg(projectRoot); ffmpeg != "" {
			_ = os.Setenv("BASKETBALL_MVP_FFMPEG", ffmpeg)
		}
	}
}

// detectEmbeddedPython 返回内置 Python 解释器路径（若存在）。
func detectEmbeddedPython(projectRoot string) string {
	base := filepath.Join(projectRoot, "runtime", "python")
	candidates := []string{}
	if runtime.GOOS == "windows" {
		candidates = append(candidates,
			filepath.Join(base, "python.exe"),
			filepath.Join(base, "Scripts", "python.exe"),
		)
	} else {
		candidates = append(candidates,
			filepath.Join(base, "bin", "python3"),
			filepath.Join(base, "bin", "python"),
		)
	}
	return firstExistingFile(candidates)
}

// detectEmbeddedFFmpeg 返回内置 ffmpeg 路径（若存在）。
func detectEmbeddedFFmpeg(projectRoot string) string {
	name := "ffmpeg"
	if runtime.GOOS == "windows" {
		name = "ffmpeg.exe"
	}
	candidates := []string{
		filepath.Join(projectRoot, "runtime", "bin", name),
	}
	return firstExistingFile(candidates)
}

// firstExistingFile 返回候选列表中第一个存在且为文件的路径。
func firstExistingFile(paths []string) string {
	for _, p := range paths {
		if p == "" {
			continue
		}
		st, err := os.Stat(p)
		if err == nil && !st.IsDir() {
			return p
		}
	}
	return ""
}

// isWritableDir 判断目录是否可写（会尝试创建并写入临时文件）。
func isWritableDir(path string) bool {
	if err := os.MkdirAll(path, 0o755); err != nil {
		return false
	}
	test := filepath.Join(path, ".write_test")
	if err := os.WriteFile(test, []byte("ok"), 0o644); err != nil {
		return false
	}
	_ = os.Remove(test)
	return true
}

// defaultSettings 返回默认应用设置。
func (s *server) defaultSettings() models.AppSettings {
	exportRoot := defaultExportRoot()
	return models.AppSettings{ExportRoot: exportRoot, KeepDebug: true}
}

// defaultExportRoot 计算通用默认导出根目录。
func defaultExportRoot() string {
	if home, err := os.UserHomeDir(); err == nil {
		movies := filepath.Join(home, "Movies")
		if isWritableDir(movies) {
			return filepath.Join(movies, "BasketballMVP", "Exports")
		}
	}
	if docs, err := os.UserConfigDir(); err == nil && docs != "" {
		return filepath.Join(docs, "BasketballMVP", "Exports")
	}
	return filepath.Join(".", "exports")
}

// defaultVideoExportRoot 根据视频路径计算单任务默认导出目录。
func defaultVideoExportRoot(videoPath string) string {
	// 单任务模式默认导出到“视频同级/BasketballMVP_Exports”。
	videoDir := filepath.Dir(videoPath)
	if videoDir == "" || videoDir == "." {
		return defaultExportRoot()
	}
	return filepath.Join(videoDir, "BasketballMVP_Exports")
}

// loadSettings 读取设置文件，不存在时写入默认值。
func (s *server) loadSettings() error {
	if err := os.MkdirAll(filepath.Dir(s.settingsPath), 0o755); err != nil {
		return fmt.Errorf("mkdir settings dir: %w", err)
	}
	st := s.defaultSettings()
	raw, err := os.ReadFile(s.settingsPath)
	if err != nil {
		if os.IsNotExist(err) {
			s.settings = st
			return s.saveSettings()
		}
		return fmt.Errorf("read settings: %w", err)
	}
	if err := json.Unmarshal(raw, &st); err != nil {
		return fmt.Errorf("parse settings: %w", err)
	}
	if st.ExportRoot == "" {
		st.ExportRoot = s.defaultSettings().ExportRoot
	}
	s.settings = st
	return nil
}

// saveSettings 持久化当前设置到 settings.json。
func (s *server) saveSettings() error {
	raw, err := json.MarshalIndent(s.settings, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal settings: %w", err)
	}
	if err := os.WriteFile(s.settingsPath, raw, 0o644); err != nil {
		return fmt.Errorf("write settings: %w", err)
	}
	return nil
}

// getSettings 返回当前应用设置。
func (s *server) getSettings(c *gin.Context) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	c.JSON(http.StatusOK, s.settings)
}

// updateSettings 更新并持久化应用设置。
func (s *server) updateSettings(c *gin.Context) {
	var req models.AppSettings
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if req.ExportRoot == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "export_root is required"})
		return
	}
	if err := os.MkdirAll(req.ExportRoot, 0o755); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": fmt.Sprintf("cannot use export_root: %v", err)})
		return
	}
	s.mu.Lock()
	s.settings = req
	err := s.saveSettings()
	s.mu.Unlock()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, req)
}

// openVideoDialog 打开系统视频文件选择框。
func (s *server) openVideoDialog(c *gin.Context) {
	if !atomic.CompareAndSwapInt32(&s.dialogOpen, 0, 1) {
		c.JSON(http.StatusConflict, gin.H{"error": "dialog is already open; finish current selection first"})
		return
	}
	defer atomic.StoreInt32(&s.dialogOpen, 0)

	path, err := openVideoSelectionDialog()
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"video_path": path})
}

// openDirectoryDialog 打开系统目录选择框。
func (s *server) openDirectoryDialog(c *gin.Context) {
	if !atomic.CompareAndSwapInt32(&s.dialogOpen, 0, 1) {
		c.JSON(http.StatusConflict, gin.H{"error": "dialog is already open; finish current selection first"})
		return
	}
	defer atomic.StoreInt32(&s.dialogOpen, 0)

	path, err := openDirectorySelectionDialog()
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"directory": path})
}

// serveLocalFile 以只读方式暴露本地绝对路径文件给前端预览。
func (s *server) serveLocalFile(c *gin.Context) {
	rawPath := c.Query("path")
	if rawPath == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "missing query 'path'"})
		return
	}
	decoded, err := url.QueryUnescape(rawPath)
	if err == nil && decoded != "" {
		rawPath = decoded
	}
	if !filepath.IsAbs(rawPath) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "path must be absolute"})
		return
	}
	st, err := os.Stat(rawPath)
	if err != nil || st.IsDir() {
		c.JSON(http.StatusNotFound, gin.H{"error": "file not found"})
		return
	}
	http.ServeFile(c.Writer, c.Request, rawPath)
}

// createJob 创建并启动一个通用任务（旧接口）。
func (s *server) createJob(c *gin.Context) {
	var req models.CreateJobRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	job := s.enqueueJob(req)
	c.JSON(http.StatusAccepted, job)
}

// enqueueJob 将任务入队并异步执行。
//
// 输入:
//   - req: 任务创建请求。
//
// 返回:
//   - *models.Job: 已创建的任务对象（已放入内存任务表）。
func (s *server) enqueueJob(req models.CreateJobRequest) *models.Job {
	id := s.nextID()
	s.mu.RLock()
	keepDebug := s.settings.KeepDebug
	s.mu.RUnlock()
	if req.KeepDebug != nil {
		keepDebug = *req.KeepDebug
	}
	job := &models.Job{
		ID:          id,
		Status:      models.JobPending,
		VideoPath:   req.VideoPath,
		OutputDir:   req.OutputDir,
		ConfigPath:  req.ConfigPath,
		ManualGoals: req.ManualGoals,
		KeepDebug:   keepDebug,
		ExportRoot:  strings.TrimSpace(req.ExportRoot),
		Progress: models.JobProgress{
			Stage:   "pending",
			Percent: 0,
		},
	}

	s.mu.Lock()
	s.jobs[job.ID] = job
	s.mu.Unlock()

	go s.runJob(job)
	return job
}

// startSingleJob 启动“单任务模式”主流程（前端主入口）。
func (s *server) startSingleJob(c *gin.Context) {
	var req models.SingleStartRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if req.Hoop.R <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "hoop.r must be > 0"})
		return
	}
	if !filepath.IsAbs(req.VideoPath) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "video_path must be absolute path"})
		return
	}
	if _, err := os.Stat(req.VideoPath); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": fmt.Sprintf("video not found: %v", err)})
		return
	}

	exportRoot := strings.TrimSpace(req.ExportRoot)
	if exportRoot == "" {
		exportRoot = defaultVideoExportRoot(req.VideoPath)
	}
	if exportRoot == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "export root is empty"})
		return
	}
	if err := os.MkdirAll(exportRoot, 0o755); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": fmt.Sprintf("cannot create export root: %v", err)})
		return
	}

	runID := buildRunFolderName(req.VideoPath)
	absOutDir := filepath.Join(exportRoot, runID)
	if err := os.MkdirAll(absOutDir, 0o755); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	templatePath := filepath.Join(s.projectRoot, "configs", "pipeline.sample.json")
	raw, err := os.ReadFile(templatePath)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": fmt.Sprintf("read template config: %v", err)})
		return
	}
	var cfg map[string]interface{}
	if err := json.Unmarshal(raw, &cfg); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": fmt.Sprintf("parse template config: %v", err)})
		return
	}
	cfg["hoop"] = map[string]int{"cx": req.Hoop.CX, "cy": req.Hoop.CY, "r": req.Hoop.R}
	// 每次任务写一份独立 pipeline.run.json，便于复盘本次参数。
	runCfgPath := filepath.Join(absOutDir, "pipeline.run.json")
	cfgRaw, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	if err := os.WriteFile(runCfgPath, cfgRaw, 0o644); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	// 单任务默认保留调试产物，避免测试同学无法复盘检测过程。
	keepDebug := true
	job := s.enqueueJob(models.CreateJobRequest{
		VideoPath:  req.VideoPath,
		OutputDir:  absOutDir,
		ConfigPath: runCfgPath,
		KeepDebug:  &keepDebug,
		ExportRoot: exportRoot,
	})

	c.JSON(http.StatusAccepted, gin.H{"job_id": job.ID, "output_dir": absOutDir})
}

// buildRunFolderName 生成任务目录名：<视频名>_<时间戳>。
func buildRunFolderName(videoPath string) string {
	base := strings.TrimSuffix(filepath.Base(videoPath), filepath.Ext(videoPath))
	base = sanitizeName(base)
	return fmt.Sprintf("%s_%s", base, time.Now().Format("20060102_150405"))
}

// sanitizeName 将任意字符串转换为安全目录名片段。
func sanitizeName(s string) string {
	if s == "" {
		return "run"
	}
	out := make([]rune, 0, len(s))
	for _, r := range s {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '_' || r == '-' {
			out = append(out, r)
			continue
		}
		out = append(out, '_')
	}
	return strings.Trim(strings.ReplaceAll(string(out), "__", "_"), "_")
}

// getJob 查询单个任务详情。
func (s *server) getJob(c *gin.Context) {
	id := c.Param("id")
	s.mu.RLock()
	job, ok := s.jobs[id]
	s.mu.RUnlock()
	if !ok {
		c.JSON(http.StatusNotFound, gin.H{"error": "job not found"})
		return
	}
	c.JSON(http.StatusOK, job)
}

// runJob 执行完整流水线并更新任务状态。
func (s *server) runJob(job *models.Job) {
	startAt := time.Now()
	s.mu.Lock()
	job.Status = models.JobRunning
	job.Progress.Stage = "starting"
	job.Progress.Percent = 1
	s.mu.Unlock()

	progressFile := filepath.Join(pipeline.ResolveOutputDir(s.projectRoot, job.OutputDir), "debug", "detect_progress.json")
	// Python 检测阶段会持续写进度文件，这里单独开协程读取并映射到 Job.Progress。
	doneCh := make(chan struct{})
	go s.watchDetectProgress(job.ID, progressFile, startAt, doneCh)

	err := pipeline.Run(s.projectRoot, job, progressFile, func(p models.JobProgress) {
		s.mu.Lock()
		defer s.mu.Unlock()
		p.ElapsedSec = time.Since(startAt).Seconds()
		if p.EstimatedLeftSec <= 0 && p.Percent > 0 {
			total := p.ElapsedSec * (100.0 / p.Percent)
			p.EstimatedLeftSec = maxFloat(0, total-p.ElapsedSec)
		}
		job.Progress = p
	})
	close(doneCh)

	s.mu.Lock()
	defer s.mu.Unlock()
	if err != nil {
		job.Status = models.JobFailed
		job.Error = err.Error()
		job.Progress.Stage = "failed"
		job.Progress.ElapsedSec = time.Since(startAt).Seconds()
		job.Progress.Percent = minFloat(job.Progress.Percent, 99)
		return
	}
	job.Status = models.JobDone
	job.Progress = models.JobProgress{Stage: "done", Percent: 100, ElapsedSec: time.Since(startAt).Seconds()}
	if !job.KeepDebug {
		// 当前产品默认保留调试文件；仅在显式关闭时清理。
		cleanupOutputDir(pipeline.ResolveOutputDir(s.projectRoot, job.OutputDir))
	}
}

// cleanupOutputDir 清理调试中间文件（不删除最终导出视频）。
func cleanupOutputDir(outputDir string) {
	// 向后兼容：历史版本有的文件在根目录，有的在 debug/ 子目录。
	_ = os.Remove(filepath.Join(outputDir, "detect_progress.json"))
	_ = os.Remove(filepath.Join(outputDir, "clips.txt"))
	_ = os.Remove(filepath.Join(outputDir, "merge.stderr.log"))
	_ = os.RemoveAll(filepath.Join(outputDir, "clips"))
	_ = os.RemoveAll(filepath.Join(outputDir, "goal_frames"))
	_ = os.Remove(filepath.Join(outputDir, "roi_debug.jpg"))
	_ = os.Remove(filepath.Join(outputDir, "tuning_suggestions.json"))
	_ = os.RemoveAll(filepath.Join(outputDir, "debug"))
}

// updateJobEvents 覆盖任务事件列表（用于“勾选后导出”）。
func (s *server) updateJobEvents(c *gin.Context) {
	id := c.Param("id")
	var req models.UpdateEventsRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	events := make([]models.GoalEvent, 0, len(req.Events))
	for _, ev := range req.Events {
		if ev.TimeSec < 0 {
			continue
		}
		if ev.Confidence <= 0 {
			ev.Confidence = 1
		}
		if ev.Reason == "" {
			ev.Reason = "manual_edit"
		}
		events = append(events, ev)
	}
	// 统一按时间升序，确保导出片段顺序与时间轴一致。
	sort.Slice(events, func(i, j int) bool { return events[i].TimeSec < events[j].TimeSec })

	s.mu.Lock()
	job, ok := s.jobs[id]
	if !ok {
		s.mu.Unlock()
		c.JSON(http.StatusNotFound, gin.H{"error": "job not found"})
		return
	}
	if job.Status == models.JobRunning {
		s.mu.Unlock()
		c.JSON(http.StatusConflict, gin.H{"error": "job is running; try again later"})
		return
	}
	job.Events = events
	job.Error = ""
	job.Progress = models.JobProgress{Stage: "events_updated", Percent: 100}
	s.mu.Unlock()

	if err := s.persistEditedEvents(job, events); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"id": id, "event_count": len(events), "message": "events updated"})
}

// persistEditedEvents 落盘保存前端编辑后的事件列表。
func (s *server) persistEditedEvents(job *models.Job, events []models.GoalEvent) error {
	outDir := pipeline.ResolveOutputDir(s.projectRoot, job.OutputDir)
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return fmt.Errorf("mkdir output dir: %w", err)
	}
	path := filepath.Join(outDir, "events.edited.json")
	payload := struct {
		EditedAt string             `json:"edited_at"`
		Events   []models.GoalEvent `json:"events"`
	}{EditedAt: time.Now().Format(time.RFC3339), Events: events}
	raw, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal edited events: %w", err)
	}
	if err := os.WriteFile(path, raw, 0o644); err != nil {
		return fmt.Errorf("write edited events: %w", err)
	}
	return nil
}

// reexportJob 使用当前事件列表重新导出视频（跳过检测阶段）。
func (s *server) reexportJob(c *gin.Context) {
	id := c.Param("id")

	s.mu.Lock()
	job, ok := s.jobs[id]
	if !ok {
		s.mu.Unlock()
		c.JSON(http.StatusNotFound, gin.H{"error": "job not found"})
		return
	}
	if job.Status == models.JobRunning {
		s.mu.Unlock()
		c.JSON(http.StatusConflict, gin.H{"error": "job is running; try again later"})
		return
	}
	if len(job.Events) == 0 {
		s.mu.Unlock()
		c.JSON(http.StatusBadRequest, gin.H{"error": "no events to export; update events first"})
		return
	}

	job.Status = models.JobRunning
	job.Error = ""
	// 重导出只做 cut+merge，不重新跑检测。
	job.Progress = models.JobProgress{Stage: "reexport_start", Percent: 1}

	videoPath := job.VideoPath
	outputDir := job.OutputDir
	configPath := job.ConfigPath
	events := append([]models.GoalEvent(nil), job.Events...)
	keepDebug := job.KeepDebug
	s.mu.Unlock()

	go s.runReexport(id, videoPath, outputDir, configPath, events, keepDebug)
	c.JSON(http.StatusAccepted, gin.H{"id": id, "status": "reexport_started"})
}

// runReexport 执行重导出流程（cut -> merge）。
func (s *server) runReexport(jobID, videoPath, outputDir, configPath string, events []models.GoalEvent, keepDebug bool) {
	startAt := time.Now()
	cfg, err := config.LoadPipelineConfig(configPath)
	if err != nil {
		s.finishReexportError(jobID, startAt, fmt.Errorf("load config: %w", err))
		return
	}

	absOutDir := pipeline.ResolveOutputDir(s.projectRoot, outputDir)
	clips, err := ffmpeg.CutClips(videoPath, absOutDir, events, cfg, func(done, total int) {
		pct := 10.0
		if total > 0 {
			pct = 10.0 + 80.0*float64(done)/float64(total)
		}
		// 重导出阶段采用独立百分比映射，避免与主流程进度定义混淆。
		s.mu.Lock()
		if job, ok := s.jobs[jobID]; ok && job.Status == models.JobRunning {
			job.Progress = models.JobProgress{Stage: "reexport_cutting", Percent: pct, ElapsedSec: time.Since(startAt).Seconds(), EstimatedLeftSec: estimateLeft(time.Since(startAt).Seconds(), pct)}
		}
		s.mu.Unlock()
	})
	if err != nil {
		s.finishReexportError(jobID, startAt, fmt.Errorf("cut clips: %w", err))
		return
	}

	s.mu.Lock()
	if job, ok := s.jobs[jobID]; ok && job.Status == models.JobRunning {
		job.Progress = models.JobProgress{Stage: "reexport_merging", Percent: 94, ElapsedSec: time.Since(startAt).Seconds(), EstimatedLeftSec: estimateLeft(time.Since(startAt).Seconds(), 94)}
	}
	s.mu.Unlock()

	highlight, err := ffmpeg.MergeHighlight(absOutDir, clips)
	if err != nil {
		s.finishReexportError(jobID, startAt, fmt.Errorf("merge clips: %w", err))
		return
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	job, ok := s.jobs[jobID]
	if !ok {
		return
	}
	job.ClipPaths = clips
	job.HighlightPath = highlight
	job.Status = models.JobDone
	job.Progress = models.JobProgress{Stage: "reexport_done", Percent: 100, ElapsedSec: time.Since(startAt).Seconds()}
	if !keepDebug {
		cleanupOutputDir(absOutDir)
	}
}

// finishReexportError 统一写入重导出失败状态。
func (s *server) finishReexportError(jobID string, startAt time.Time, err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	job, ok := s.jobs[jobID]
	if !ok {
		return
	}
	job.Status = models.JobFailed
	job.Error = err.Error()
	job.Progress = models.JobProgress{Stage: "reexport_failed", Percent: minFloat(job.Progress.Percent, 99), ElapsedSec: time.Since(startAt).Seconds()}
}

// detectProgressPayload 对应 Python 写出的检测进度 JSON 结构。
type detectProgressPayload struct {
	Stage            string  `json:"stage"`
	Percent          float64 `json:"percent"`
	ProcessedFrames  int     `json:"processed_frames"`
	TotalFrames      int     `json:"total_frames"`
	ElapsedSec       float64 `json:"elapsed_sec"`
	EstimatedLeftSec float64 `json:"estimated_left_sec"`
}

// watchDetectProgress 轮询 Python 进度文件并映射到任务进度。
func (s *server) watchDetectProgress(jobID, progressFile string, startAt time.Time, done <-chan struct{}) {
	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-done:
			return
		case <-ticker.C:
			raw, err := os.ReadFile(progressFile)
			if err != nil {
				continue
			}
			var d detectProgressPayload
			if err := json.Unmarshal(raw, &d); err != nil {
				continue
			}
			// 检测阶段在总流程中占 0~70%，剩余留给剪切与合并。
			totalPercent := minFloat(70, maxFloat(0, d.Percent*0.7))
			s.mu.Lock()
			job, ok := s.jobs[jobID]
			if ok && job.Status == models.JobRunning && (job.Progress.Stage == "starting" || job.Progress.Stage == "detecting" || job.Progress.Stage == "") {
				job.Progress = models.JobProgress{Stage: "detecting", Percent: totalPercent, ElapsedSec: time.Since(startAt).Seconds(), EstimatedLeftSec: d.EstimatedLeftSec, ProcessedFrames: d.ProcessedFrames, TotalFrames: d.TotalFrames}
			}
			s.mu.Unlock()
		}
	}
}

// nextID 生成下一个任务 ID。
func (s *server) nextID() string {
	n := atomic.AddUint64(&s.seq, 1)
	return "job-" + itoa(n)
}

// itoa 将 uint64 转十进制字符串（避免引入 strconv 依赖）。
func itoa(v uint64) string {
	if v == 0 {
		return "0"
	}
	buf := [20]byte{}
	i := len(buf)
	for v > 0 {
		i--
		buf[i] = byte('0' + v%10)
		v /= 10
	}
	return string(buf[i:])
}

// minFloat 返回较小值。
func minFloat(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}

// maxFloat 返回较大值。
func maxFloat(a, b float64) float64 {
	if a > b {
		return a
	}
	return b
}

// estimateLeft 根据“已耗时 + 已完成百分比”估算剩余时长。
func estimateLeft(elapsedSec, percent float64) float64 {
	// 简单线性估算：已耗时 / 已完成百分比。
	if percent <= 0 {
		return 0
	}
	total := elapsedSec * (100.0 / percent)
	return maxFloat(0, total-elapsedSec)
}

// openURL 使用平台默认浏览器打开链接。
func openURL(target string) {
	switch strings.ToLower(strings.TrimSpace(runtimeGOOS())) {
	case "darwin":
		_ = exec.Command("open", target).Start()
	case "windows":
		_ = exec.Command("rundll32", "url.dll,FileProtocolHandler", target).Start()
	default:
		_ = exec.Command("xdg-open", target).Start()
	}
}
