package drivers

import (
	"database/sql"
	"fmt"
	"time"

	"basketball-mvp/app-go/internal/cloudapi/framework/config"

	_ "github.com/go-sql-driver/mysql"
)

// InitMySQL 创建并初始化 MySQL 连接池。
func InitMySQL(cfg *config.MySQL) (*sql.DB, error) {
	if cfg == nil {
		return nil, fmt.Errorf("mysql config is nil")
	}
	dsn := buildDSN(cfg)
	db, err := sql.Open("mysql", dsn)
	if err != nil {
		return nil, fmt.Errorf("open mysql: %w", err)
	}

	if cfg.MaxIdleConns > 0 {
		db.SetMaxIdleConns(cfg.MaxIdleConns)
	}
	if cfg.MaxOpenConns > 0 {
		db.SetMaxOpenConns(cfg.MaxOpenConns)
	}
	if cfg.ConnMaxLifetime > 0 {
		db.SetConnMaxLifetime(time.Duration(cfg.ConnMaxLifetime) * time.Second)
	}

	if err := db.Ping(); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("ping mysql: %w", err)
	}
	return db, nil
}

func buildDSN(cfg *config.MySQL) string {
	charset := cfg.Charset
	if charset == "" {
		charset = "utf8mb4"
	}
	return fmt.Sprintf(
		"%s:%s@tcp(%s:%d)/%s?charset=%s&parseTime=true&loc=Asia%%2FShanghai",
		cfg.Username,
		cfg.Password,
		cfg.Host,
		cfg.Port,
		cfg.Database,
		charset,
	)
}
