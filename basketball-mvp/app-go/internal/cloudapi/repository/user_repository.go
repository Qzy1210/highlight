package repository

import (
	"database/sql"
	"errors"
	"fmt"
	"sync"
	"time"

	"basketball-mvp/app-go/internal/cloudapi/model"

	mysqlDriver "github.com/go-sql-driver/mysql"
)

// UserRepository 用户存储接口。
type UserRepository interface {
	FindByUsername(username string) (*model.User, error)
	FindByID(id string) (*model.User, error)
	Create(user *model.User) error
}

// MemoryUserRepository 内存用户存储实现（首版占位，后续可切数据库）。
type MemoryUserRepository struct {
	mu         sync.RWMutex
	byID       map[string]*model.User
	byUsername map[string]*model.User
}

// NewMemoryUserRepository 创建内存用户仓库。
func NewMemoryUserRepository(users []*model.User) *MemoryUserRepository {
	r := &MemoryUserRepository{
		byID:       make(map[string]*model.User, len(users)),
		byUsername: make(map[string]*model.User, len(users)),
	}
	for _, u := range users {
		c := *u
		r.byID[c.ID] = &c
		r.byUsername[c.Username] = &c
	}
	return r
}

// FindByUsername 按用户名查找用户。
func (r *MemoryUserRepository) FindByUsername(username string) (*model.User, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	u, ok := r.byUsername[username]
	if !ok {
		return nil, ErrNotFound
	}
	c := *u
	return &c, nil
}

// FindByID 按用户 ID 查找。
func (r *MemoryUserRepository) FindByID(id string) (*model.User, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	u, ok := r.byID[id]
	if !ok {
		return nil, ErrNotFound
	}
	c := *u
	return &c, nil
}

// Create 新增用户。
func (r *MemoryUserRepository) Create(user *model.User) error {
	if user == nil {
		return errors.New("user is nil")
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, ok := r.byID[user.ID]; ok {
		return ErrConflict
	}
	if _, ok := r.byUsername[user.Username]; ok {
		return ErrConflict
	}
	c := *user
	r.byID[c.ID] = &c
	r.byUsername[c.Username] = &c
	return nil
}

// MySQLUserRepository MySQL 用户仓库实现。
type MySQLUserRepository struct {
	db *sql.DB
}

// NewMySQLUserRepository 创建 MySQL 用户仓库。
func NewMySQLUserRepository(db *sql.DB) *MySQLUserRepository {
	return &MySQLUserRepository{db: db}
}

// FindByUsername 按用户名查找用户。
func (r *MySQLUserRepository) FindByUsername(username string) (*model.User, error) {
	const query = `
SELECT id, username, password_hash
FROM mvp_users
WHERE username = ?
LIMIT 1
`
	var u model.User
	if err := r.db.QueryRow(query, username).Scan(&u.ID, &u.Username, &u.PasswordHash); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrNotFound
		}
		return nil, fmt.Errorf("query user by username: %w", err)
	}
	return &u, nil
}

// FindByID 按 ID 查找用户。
func (r *MySQLUserRepository) FindByID(id string) (*model.User, error) {
	const query = `
SELECT id, username, password_hash
FROM mvp_users
WHERE id = ?
LIMIT 1
`
	var u model.User
	if err := r.db.QueryRow(query, id).Scan(&u.ID, &u.Username, &u.PasswordHash); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrNotFound
		}
		return nil, fmt.Errorf("query user by id: %w", err)
	}
	return &u, nil
}

// Create 新增用户。
func (r *MySQLUserRepository) Create(user *model.User) error {
	if user == nil {
		return errors.New("user is nil")
	}
	const stmt = `
INSERT INTO mvp_users (id, username, password_hash, created_at, updated_at)
VALUES (?, ?, ?, ?, ?)
`
	now := time.Now()
	if _, err := r.db.Exec(stmt, user.ID, user.Username, user.PasswordHash, now, now); err != nil {
		var mysqlErr *mysqlDriver.MySQLError
		if errors.As(err, &mysqlErr) && mysqlErr.Number == 1062 {
			return ErrConflict
		}
		return fmt.Errorf("insert user: %w", err)
	}
	return nil
}
