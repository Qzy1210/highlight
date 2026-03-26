package repository

import (
	"database/sql"
	"errors"
	"fmt"
	"time"

	"basketball-mvp/app-go/internal/cloudapi/model"
)

// RefreshTokenRepository 定义 refresh token 存储能力。
type RefreshTokenRepository interface {
	Create(token *model.RefreshToken) error
	FindActiveByHash(tokenHash string) (*model.RefreshToken, error)
	RevokeByHash(tokenHash string) error
}

// MySQLRefreshTokenRepository MySQL refresh token 仓库实现。
type MySQLRefreshTokenRepository struct {
	db *sql.DB
}

// NewMySQLRefreshTokenRepository 创建 refresh token MySQL 仓库。
func NewMySQLRefreshTokenRepository(db *sql.DB) *MySQLRefreshTokenRepository {
	return &MySQLRefreshTokenRepository{db: db}
}

// Create 新增 refresh token。
func (r *MySQLRefreshTokenRepository) Create(token *model.RefreshToken) error {
	const stmt = `
INSERT INTO mvp_refresh_tokens (
	token_hash, jti, user_id, username, expires_at, revoked, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
`
	now := time.Now()
	token.CreatedAt = now
	token.UpdatedAt = now
	if _, err := r.db.Exec(
		stmt,
		token.TokenHash,
		token.JTI,
		token.UserID,
		token.Username,
		token.ExpiresAt,
		token.Revoked,
		token.CreatedAt,
		token.UpdatedAt,
	); err != nil {
		return fmt.Errorf("insert refresh token: %w", err)
	}
	return nil
}

// FindActiveByHash 按 hash 查询可用 refresh token（未撤销且未过期）。
func (r *MySQLRefreshTokenRepository) FindActiveByHash(tokenHash string) (*model.RefreshToken, error) {
	const query = `
SELECT id, token_hash, jti, user_id, username, expires_at, revoked, created_at, updated_at
FROM mvp_refresh_tokens
WHERE token_hash = ?
LIMIT 1
`
	var t model.RefreshToken
	if err := r.db.QueryRow(query, tokenHash).Scan(
		&t.ID,
		&t.TokenHash,
		&t.JTI,
		&t.UserID,
		&t.Username,
		&t.ExpiresAt,
		&t.Revoked,
		&t.CreatedAt,
		&t.UpdatedAt,
	); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrNotFound
		}
		return nil, fmt.Errorf("query refresh token: %w", err)
	}
	if t.Revoked || !t.ExpiresAt.After(time.Now()) {
		return nil, ErrNotFound
	}
	return &t, nil
}

// RevokeByHash 撤销 refresh token。
func (r *MySQLRefreshTokenRepository) RevokeByHash(tokenHash string) error {
	const stmt = `
UPDATE mvp_refresh_tokens
SET revoked = 1, updated_at = ?
WHERE token_hash = ? AND revoked = 0
`
	res, err := r.db.Exec(stmt, time.Now(), tokenHash)
	if err != nil {
		return fmt.Errorf("revoke refresh token: %w", err)
	}
	affected, err := res.RowsAffected()
	if err != nil {
		return fmt.Errorf("read refresh token affected rows: %w", err)
	}
	if affected == 0 {
		return ErrNotFound
	}
	return nil
}
