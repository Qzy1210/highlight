package bootstrap

import (
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"

	"basketball-mvp/app-go/internal/cloudapi/auth"
	cloudcfg "basketball-mvp/app-go/internal/cloudapi/framework/config"
	"basketball-mvp/app-go/internal/cloudapi/framework/drivers"
	"basketball-mvp/app-go/internal/cloudapi/logic"
	"basketball-mvp/app-go/internal/cloudapi/model"
	"basketball-mvp/app-go/internal/cloudapi/repository"

	"golang.org/x/crypto/bcrypt"
)

// BuildDeps 构建业务依赖（repo/logic/auth）。
func BuildDeps() (*auth.JWTService, *logic.AuthLogic, *logic.TaskLogic, error) {
	db, err := drivers.MustSQL()
	if err != nil {
		return nil, nil, nil, err
	}
	if err := ensureSchema(db); err != nil {
		return nil, nil, nil, err
	}

	userRepo := repository.NewMySQLUserRepository(db)
	taskRepo := repository.NewMySQLTaskRepository(db)
	refreshRepo := repository.NewMySQLRefreshTokenRepository(db)

	if err := seedDefaultUser(userRepo); err != nil {
		return nil, nil, nil, err
	}

	authCfg := cloudcfg.AuthInstance()
	jwtSvc := auth.NewJWTService(
		authCfg.Secret(),
		time.Duration(authCfg.AccessTTL())*time.Second,
		time.Duration(authCfg.RefreshTTL())*time.Second,
		authCfg.IssuerName(),
	)
	authLogic := logic.NewAuthLogic(userRepo, refreshRepo, jwtSvc)
	taskLogic := logic.NewTaskLogic(taskRepo)
	return jwtSvc, authLogic, taskLogic, nil
}

func ensureSchema(db *sql.DB) error {
	stmts := []string{
		`CREATE TABLE IF NOT EXISTS mvp_users (
			id VARCHAR(64) NOT NULL,
			username VARCHAR(128) NOT NULL,
			password_hash VARCHAR(255) NOT NULL,
			created_at DATETIME NOT NULL,
			updated_at DATETIME NOT NULL,
			PRIMARY KEY (id),
			UNIQUE KEY uk_username (username)
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4`,
		`CREATE TABLE IF NOT EXISTS mvp_tasks (
			id VARCHAR(64) NOT NULL,
			user_id VARCHAR(64) NOT NULL,
			video_path TEXT NOT NULL,
			status VARCHAR(32) NOT NULL,
			error TEXT NULL,
			result_path TEXT NULL,
			terminated TINYINT(1) NOT NULL DEFAULT 0,
			created_at DATETIME NOT NULL,
			updated_at DATETIME NOT NULL,
			PRIMARY KEY (id),
			KEY idx_user_created (user_id, created_at)
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4`,
		`CREATE TABLE IF NOT EXISTS mvp_refresh_tokens (
			id BIGINT NOT NULL AUTO_INCREMENT,
			token_hash VARCHAR(128) NOT NULL,
			jti VARCHAR(128) NOT NULL,
			user_id VARCHAR(64) NOT NULL,
			username VARCHAR(128) NOT NULL,
			expires_at DATETIME NOT NULL,
			revoked TINYINT(1) NOT NULL DEFAULT 0,
			created_at DATETIME NOT NULL,
			updated_at DATETIME NOT NULL,
			PRIMARY KEY (id),
			UNIQUE KEY uk_token_hash (token_hash),
			UNIQUE KEY uk_jti (jti),
			KEY idx_user_id (user_id),
			KEY idx_expires_at (expires_at)
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4`,
	}
	for _, stmt := range stmts {
		if _, err := db.Exec(stmt); err != nil {
			return fmt.Errorf("init schema failed: %w", err)
		}
	}
	return nil
}

func seedDefaultUser(users repository.UserRepository) error {
	cfg := cloudcfg.AuthInstance()
	username := ""
	password := ""
	if cfg != nil {
		username = strings.TrimSpace(cfg.DefaultUsername)
		password = strings.TrimSpace(cfg.DefaultPassword)
	}
	if username == "" {
		username = "admin"
	}
	if password == "" {
		password = "ChangeMe123"
	}

	if _, err := users.FindByUsername(username); err == nil {
		return nil
	} else if !errors.Is(err, repository.ErrNotFound) {
		return err
	}

	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return err
	}
	return users.Create(&model.User{
		ID:           "u-admin",
		Username:     username,
		PasswordHash: string(hash),
	})
}
