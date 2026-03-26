package models

// JobStatus 表示任务执行状态。
type JobStatus string

const (
	// JobPending: 任务已创建，尚未开始执行。
	JobPending JobStatus = "pending"
	// JobRunning: 任务正在执行（检测/剪辑/合并中）。
	JobRunning JobStatus = "running"
	// JobDone: 任务成功完成。
	JobDone JobStatus = "done"
	// JobFailed: 任务失败，Error 字段包含失败原因。
	JobFailed JobStatus = "failed"
)

// CreateJobRequest 是通用任务创建请求（API: POST /api/v1/jobs）。
type CreateJobRequest struct {
	// VideoPath: 输入视频绝对路径。
	VideoPath string `json:"video_path" binding:"required"`
	// OutputDir: 本次任务输出目录（可为绝对路径或相对 projectRoot 的路径）。
	OutputDir string `json:"output_dir" binding:"required"`
	// ConfigPath: pipeline 配置文件路径。
	ConfigPath string `json:"config_path" binding:"required"`
	// ManualGoals: 手工指定进球秒数；非空时检测阶段跳过自动识别。
	ManualGoals []float64 `json:"manual_goals"`
	// KeepDebug: 是否保留调试产物；nil 表示沿用服务端默认设置。
	KeepDebug *bool `json:"keep_debug,omitempty"`
	// ExportRoot: 本次任务归属的导出根目录（仅用于展示/记录）。
	ExportRoot string `json:"export_root,omitempty"`
}

// HoopConfig 表示篮框标定结果（中心点 + 半径，单位像素）。
type HoopConfig struct {
	// CX: 篮框中心点 x 坐标（像素）。
	CX int `json:"cx" binding:"required"`
	// CY: 篮框中心点 y 坐标（像素）。
	CY int `json:"cy" binding:"required"`
	// R: 篮框半径（像素）。
	R int `json:"r" binding:"required"`
}

// AutoHoopConfig 表示自动篮框模式请求参数。
type AutoHoopConfig struct {
	// Enabled: 是否启用自动篮框（ONNX）模式。
	Enabled bool `json:"enabled"`
	// ModelPath: ONNX 模型路径；为空时服务端自动选择最新 best.onnx。
	ModelPath string `json:"model_path,omitempty"`
	// ConfThreshold: 置信度阈值（可选，<=0 时使用引擎默认值）。
	ConfThreshold float64 `json:"conf_threshold,omitempty"`
	// IoUThreshold: NMS IoU 阈值（可选，<=0 时使用引擎默认值）。
	IoUThreshold float64 `json:"iou_threshold,omitempty"`
}

// HoopCandidate 表示自动检测得到的一个篮框候选。
type HoopCandidate struct {
	// ID: 候选唯一标识（用于前端下拉选择）。
	ID string `json:"id"`
	// CX: 候选篮框中心 x（像素）。
	CX int `json:"cx"`
	// CY: 候选篮框中心 y（像素）。
	CY int `json:"cy"`
	// R: 候选篮框半径（像素）。
	R int `json:"r"`
	// Score: 候选分数（越高越优先）。
	Score float64 `json:"score"`
	// Count: 跨帧聚类命中次数（用于稳定性判断）。
	Count int `json:"count,omitempty"`
	// Frame: 该候选最佳检测帧号（用于回溯定位）。
	Frame int `json:"frame,omitempty"`
	// FrameImage: 该候选对应帧截图（已圈出候选篮框）。
	FrameImage string `json:"frame_image,omitempty"`
}

// DetectHoopRequest 表示“自动检测篮框”请求。
type DetectHoopRequest struct {
	// VideoPath: 输入视频绝对路径。
	VideoPath string `json:"video_path" binding:"required"`
}

// DetectHoopResponse 表示自动篮框检测结果。
type DetectHoopResponse struct {
	// Status: 候选状态（none/single/multiple）。
	Status string `json:"status"`
	// Candidates: 候选列表。
	Candidates []HoopCandidate `json:"candidates"`
	// PreviewImage: 候选可视化预览图绝对路径（可选）。
	PreviewImage string `json:"preview_image,omitempty"`
	// ModelPath: 使用的 ONNX 模型路径。
	ModelPath string `json:"model_path,omitempty"`
	// DebugJSON: 调试明细 JSON 路径。
	DebugJSON string `json:"debug_json,omitempty"`
	// Error: 检测失败时的错误详情（可选）。
	Error string `json:"error,omitempty"`
}

// SingleStartRequest 表示单任务模式启动请求。
type SingleStartRequest struct {
	// VideoPath: 输入视频绝对路径。
	VideoPath string `json:"video_path" binding:"required"`
	// ExportRoot: 导出根目录。为空时使用“视频同级/BasketballMVP_Exports”。
	ExportRoot string `json:"export_root,omitempty"`
	// KeepDebug: 是否保留调试产物（当前单任务默认保留）。
	KeepDebug bool `json:"keep_debug,omitempty"`
	// Hoop: 前端确认回填后的篮框参数（必填）。
	Hoop HoopConfig `json:"hoop"`
	// AutoHoop: 自动篮框检测配置（默认关闭）。
	AutoHoop AutoHoopConfig `json:"auto_hoop,omitempty"`
}

// UpdateEventsRequest 表示前端编辑后的事件列表。
type UpdateEventsRequest struct {
	// Events: 用户最终确认要导出的事件（可删减、调整）。
	Events []GoalEvent `json:"events" binding:"required"`
}

// GoalEvent 表示一个进球事件。
type GoalEvent struct {
	// TimeSec: 事件发生时间（秒）。
	TimeSec float64 `json:"time_sec"`
	// Confidence: 置信度（0~1+，由检测链路打分）。
	Confidence float64 `json:"confidence"`
	// Reason: 触发原因（如 ball_cross+net_motion、manual_edit）。
	Reason string `json:"reason"`
	// NetMotion: 篮网运动强度（可选，自动检测时有值）。
	NetMotion float64 `json:"net_motion,omitempty"`
	// FrameImage: 调试截图路径（可选）。
	FrameImage string `json:"frame_image,omitempty"`
}

// PipelineConfig 表示剪辑窗口相关配置。
type PipelineConfig struct {
	// 每个进球片段往前保留秒数
	PreSeconds float64 `json:"pre_seconds"`
	// 每个进球片段往后保留秒数
	PostSeconds float64 `json:"post_seconds"`
	// 事件冷却时间（当前用于检测阶段配置透传）
	CooldownSec float64 `json:"cooldown_sec"`
}

// Job 表示完整任务对象（用于前后端通信和内存状态存储）。
type Job struct {
	// ID: 任务唯一 ID（如 job-1）。
	ID string `json:"id"`
	// Status: 当前执行状态。
	Status JobStatus `json:"status"`
	// Error: 失败原因（仅 failed 时通常非空）。
	Error string `json:"error,omitempty"`
	// VideoPath: 输入视频路径。
	VideoPath string `json:"video_path"`
	// OutputDir: 本次任务输出目录。
	OutputDir string `json:"output_dir"`
	// ConfigPath: 本次任务配置文件路径。
	ConfigPath string `json:"config_path"`
	// ManualGoals: 手工指定事件列表（可选）。
	ManualGoals []float64 `json:"manual_goals,omitempty"`
	// Events: 检测或编辑后的事件列表。
	Events []GoalEvent `json:"events,omitempty"`
	// ClipPaths: 已切片段文件路径列表。
	ClipPaths []string `json:"clip_paths,omitempty"`
	// HighlightPath: 最终导出视频路径。
	HighlightPath string `json:"highlight_path,omitempty"`
	// DetectionJSON: 原始检测 JSON 路径。
	DetectionJSON string `json:"detection_json,omitempty"`
	// Progress: 当前进度快照。
	Progress JobProgress `json:"progress"`
	// 是否保留调试产物（roi_debug、clips、goal_frames等）
	KeepDebug bool `json:"keep_debug,omitempty"`
	// 当前任务导出根目录（便于前端展示）
	ExportRoot string `json:"export_root,omitempty"`
}

// JobProgress 表示任务执行进度。
type JobProgress struct {
	// Stage: 阶段标识（detecting/cutting_clips/merging/done 等）。
	Stage string `json:"stage"`
	// Percent: 总体进度百分比（0~100）。
	Percent float64 `json:"percent"`
	// ElapsedSec: 已耗时（秒）。
	ElapsedSec float64 `json:"elapsed_sec"`
	// EstimatedLeftSec: 预计剩余耗时（秒）。
	EstimatedLeftSec float64 `json:"estimated_left_sec"`
	// ProcessedFrames: 已处理帧数（检测阶段使用）。
	ProcessedFrames int `json:"processed_frames,omitempty"`
	// TotalFrames: 总帧数（检测阶段使用）。
	TotalFrames int `json:"total_frames,omitempty"`
}

// AppSettings 表示应用级设置。
type AppSettings struct {
	// 用户默认导出目录
	ExportRoot string `json:"export_root"`
	// 是否保留调试文件
	KeepDebug bool `json:"keep_debug"`
}
