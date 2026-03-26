package logic

import (
	"errors"
	"fmt"
	"sync/atomic"
	"time"

	"basketball-mvp/app-go/internal/cloudapi/model"
	"basketball-mvp/app-go/internal/cloudapi/repository"
)

// TaskLogic 处理任务创建、查询与终止。
type TaskLogic struct {
	tasks repository.TaskRepository
	seq   uint64
}

// NewTaskLogic 创建任务逻辑层。
func NewTaskLogic(tasks repository.TaskRepository) *TaskLogic {
	return &TaskLogic{tasks: tasks}
}

// CreateTask 创建一个用户任务（首版先以异步占位流程模拟）。
func (l *TaskLogic) CreateTask(userID, videoPath string) (*model.Task, error) {
	seq := atomic.AddUint64(&l.seq, 1)
	id := fmt.Sprintf("task-%d-%d", time.Now().UnixNano(), seq)
	task := &model.Task{
		ID:        id,
		UserID:    userID,
		VideoPath: videoPath,
		Status:    model.TaskQueued,
	}
	if err := l.tasks.Create(task); err != nil {
		return nil, err
	}

	// 首版占位：模拟排队->运行->完成，后续替换为真实 pipeline 任务执行。
	go func() {
		created, err := l.tasks.GetByIDForUser(id, userID)
		if err != nil {
			return
		}
		created.Status = model.TaskRunning
		_ = l.tasks.Update(created)

		time.Sleep(2 * time.Second)
		latest, err := l.tasks.GetByIDForUser(id, userID)
		if err != nil {
			return
		}
		if latest.Terminated {
			latest.Status = model.TaskTerminated
			_ = l.tasks.Update(latest)
			return
		}
		latest.Status = model.TaskDone
		latest.ResultPath = ""
		_ = l.tasks.Update(latest)
	}()
	return task, nil
}

// GetTask 查询当前用户任务详情。
func (l *TaskLogic) GetTask(userID, taskID string) (*model.Task, error) {
	return l.tasks.GetByIDForUser(taskID, userID)
}

// ListTasks 查询当前用户任务列表。
func (l *TaskLogic) ListTasks(userID string) ([]model.Task, error) {
	return l.tasks.ListByUser(userID)
}

// TerminateTask 终止当前用户任务。
func (l *TaskLogic) TerminateTask(userID, taskID string) error {
	t, err := l.tasks.GetByIDForUser(taskID, userID)
	if err != nil {
		return err
	}
	if t.Status == model.TaskDone || t.Status == model.TaskFailed || t.Status == model.TaskTerminated {
		return errors.New("task is not running")
	}
	t.Terminated = true
	t.Status = model.TaskTerminated
	return l.tasks.Update(t)
}
