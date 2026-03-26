package repository

import "errors"

var (
	// ErrNotFound 表示记录不存在。
	ErrNotFound = errors.New("record not found")
	// ErrConflict 表示记录冲突（如唯一键冲突）。
	ErrConflict = errors.New("record conflict")
)
