package model

import "time"

// TaskStatus 定义任务状态。
type TaskStatus string

const (
	// TaskQueued 表示排队中。
	TaskQueued TaskStatus = "queued"
	// TaskRunning 表示处理中。
	TaskRunning TaskStatus = "running"
	// TaskDone 表示完成。
	TaskDone TaskStatus = "done"
	// TaskFailed 表示失败。
	TaskFailed TaskStatus = "failed"
	// TaskTerminated 表示用户终止。
	TaskTerminated TaskStatus = "terminated"
)

// Task 表示云端任务（按 user_id 隔离）。
type Task struct {
	ID         string     `json:"id"`
	UserID     string     `json:"user_id"`
	VideoPath  string     `json:"video_path"`
	Status     TaskStatus `json:"status"`
	Error      string     `json:"error,omitempty"`
	ResultPath string     `json:"result_path,omitempty"`
	CreatedAt  time.Time  `json:"created_at"`
	UpdatedAt  time.Time  `json:"updated_at"`
	Terminated bool       `json:"terminated"`
}

// CreateTaskRequest 创建任务请求。
type CreateTaskRequest struct {
	VideoPath string `json:"video_path" binding:"required"`
}
