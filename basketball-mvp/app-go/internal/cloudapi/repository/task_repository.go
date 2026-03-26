package repository

import (
	"database/sql"
	"errors"
	"fmt"
	"sort"
	"sync"
	"time"

	"basketball-mvp/app-go/internal/cloudapi/model"
)

// TaskRepository 任务存储接口。
type TaskRepository interface {
	Create(task *model.Task) error
	ListByUser(userID string) ([]model.Task, error)
	GetByIDForUser(taskID, userID string) (*model.Task, error)
	Update(task *model.Task) error
}

// MemoryTaskRepository 内存任务存储实现（首版占位，后续可切数据库）。
type MemoryTaskRepository struct {
	mu    sync.RWMutex
	tasks map[string]*model.Task
}

// NewMemoryTaskRepository 创建内存任务仓库。
func NewMemoryTaskRepository() *MemoryTaskRepository {
	return &MemoryTaskRepository{
		tasks: map[string]*model.Task{},
	}
}

// Create 新增任务。
func (r *MemoryTaskRepository) Create(task *model.Task) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	c := *task
	now := time.Now()
	c.CreatedAt = now
	c.UpdatedAt = now
	r.tasks[c.ID] = &c
	return nil
}

// ListByUser 查询某个用户的任务列表。
func (r *MemoryTaskRepository) ListByUser(userID string) ([]model.Task, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]model.Task, 0, len(r.tasks))
	for _, t := range r.tasks {
		if t.UserID != userID {
			continue
		}
		out = append(out, *t)
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].CreatedAt.After(out[j].CreatedAt)
	})
	return out, nil
}

// GetByIDForUser 按用户读取任务，防止越权访问。
func (r *MemoryTaskRepository) GetByIDForUser(taskID, userID string) (*model.Task, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	t, ok := r.tasks[taskID]
	if !ok {
		return nil, ErrNotFound
	}
	if t.UserID != userID {
		return nil, ErrNotFound
	}
	c := *t
	return &c, nil
}

// Update 更新任务状态。
func (r *MemoryTaskRepository) Update(task *model.Task) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	_, ok := r.tasks[task.ID]
	if !ok {
		return ErrNotFound
	}
	c := *task
	c.UpdatedAt = time.Now()
	r.tasks[c.ID] = &c
	return nil
}

// MySQLTaskRepository MySQL 任务仓库实现。
type MySQLTaskRepository struct {
	db *sql.DB
}

// NewMySQLTaskRepository 创建 MySQL 任务仓库。
func NewMySQLTaskRepository(db *sql.DB) *MySQLTaskRepository {
	return &MySQLTaskRepository{db: db}
}

// Create 新增任务。
func (r *MySQLTaskRepository) Create(task *model.Task) error {
	const stmt = `
INSERT INTO mvp_tasks (
	id, user_id, video_path, status, error, result_path, terminated, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
`
	now := time.Now()
	task.CreatedAt = now
	task.UpdatedAt = now
	if _, err := r.db.Exec(
		stmt,
		task.ID,
		task.UserID,
		task.VideoPath,
		task.Status,
		task.Error,
		task.ResultPath,
		task.Terminated,
		task.CreatedAt,
		task.UpdatedAt,
	); err != nil {
		return fmt.Errorf("insert task: %w", err)
	}
	return nil
}

// ListByUser 查询用户任务列表。
func (r *MySQLTaskRepository) ListByUser(userID string) ([]model.Task, error) {
	const query = `
SELECT id, user_id, video_path, status, error, result_path, terminated, created_at, updated_at
FROM mvp_tasks
WHERE user_id = ?
ORDER BY created_at DESC
`
	rows, err := r.db.Query(query, userID)
	if err != nil {
		return nil, fmt.Errorf("query tasks: %w", err)
	}
	defer rows.Close()

	out := make([]model.Task, 0)
	for rows.Next() {
		var t model.Task
		if err := rows.Scan(
			&t.ID,
			&t.UserID,
			&t.VideoPath,
			&t.Status,
			&t.Error,
			&t.ResultPath,
			&t.Terminated,
			&t.CreatedAt,
			&t.UpdatedAt,
		); err != nil {
			return nil, fmt.Errorf("scan task row: %w", err)
		}
		out = append(out, t)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate task rows: %w", err)
	}
	return out, nil
}

// GetByIDForUser 查询当前用户的任务详情。
func (r *MySQLTaskRepository) GetByIDForUser(taskID, userID string) (*model.Task, error) {
	const query = `
SELECT id, user_id, video_path, status, error, result_path, terminated, created_at, updated_at
FROM mvp_tasks
WHERE id = ? AND user_id = ?
LIMIT 1
`
	var t model.Task
	if err := r.db.QueryRow(query, taskID, userID).Scan(
		&t.ID,
		&t.UserID,
		&t.VideoPath,
		&t.Status,
		&t.Error,
		&t.ResultPath,
		&t.Terminated,
		&t.CreatedAt,
		&t.UpdatedAt,
	); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrNotFound
		}
		return nil, fmt.Errorf("query task by id: %w", err)
	}
	return &t, nil
}

// Update 更新任务。
func (r *MySQLTaskRepository) Update(task *model.Task) error {
	const stmt = `
UPDATE mvp_tasks
SET status = ?, error = ?, result_path = ?, terminated = ?, updated_at = ?
WHERE id = ? AND user_id = ?
`
	now := time.Now()
	task.UpdatedAt = now
	res, err := r.db.Exec(
		stmt,
		task.Status,
		task.Error,
		task.ResultPath,
		task.Terminated,
		task.UpdatedAt,
		task.ID,
		task.UserID,
	)
	if err != nil {
		return fmt.Errorf("update task: %w", err)
	}
	affect, err := res.RowsAffected()
	if err != nil {
		return fmt.Errorf("read task update affected: %w", err)
	}
	if affect == 0 {
		return ErrNotFound
	}
	return nil
}
