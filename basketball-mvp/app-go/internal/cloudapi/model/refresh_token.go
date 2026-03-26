package model

import "time"

// RefreshToken 表示 refresh token 在数据库中的持久化记录。
type RefreshToken struct {
	ID        int64
	TokenHash string
	JTI       string
	UserID    string
	Username  string
	ExpiresAt time.Time
	Revoked   bool
	CreatedAt time.Time
	UpdatedAt time.Time
}
