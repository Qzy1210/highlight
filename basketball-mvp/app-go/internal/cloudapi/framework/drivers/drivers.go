package drivers

import (
	"database/sql"
	"fmt"

	"basketball-mvp/app-go/internal/cloudapi/framework/config"
)

var (
	// SQLDriver 是默认数据库连接池（当前仅 MySQL）。
	SQLDriver *sql.DB
)

// InitDrivers 初始化所有基础驱动。
func InitDrivers() error {
	db, err := InitMySQL(config.MySQLDefault())
	if err != nil {
		return err
	}
	SQLDriver = db
	return nil
}

// MustSQL 返回 SQLDriver，未初始化时返回错误。
func MustSQL() (*sql.DB, error) {
	if SQLDriver == nil {
		return nil, fmt.Errorf("sql driver is not initialized")
	}
	return SQLDriver, nil
}

// TerminateDrivers 关闭所有基础驱动。
func TerminateDrivers() error {
	if SQLDriver == nil {
		return nil
	}
	err := SQLDriver.Close()
	SQLDriver = nil
	return err
}
