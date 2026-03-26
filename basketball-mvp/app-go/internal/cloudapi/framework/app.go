package framework

import (
	"fmt"
	stdlog "log"

	"basketball-mvp/app-go/internal/cloudapi/framework/provider"
	"github.com/gin-gonic/gin"
)

// App 是云 API 服务容器，负责管理 gin 引擎与 provider。
type App struct {
	Gin       *gin.Engine
	providers []provider.Provider
}

// New 创建应用容器。
func New() *App {
	return &App{}
}

// AddProvider 添加一个 provider。
func (a *App) AddProvider(p provider.Provider) {
	a.providers = append(a.providers, p)
}

// GetGin 返回服务 Gin 实例。
func (a *App) GetGin() *gin.Engine {
	return a.Gin
}

// Bootstrap 按顺序初始化并启动 provider。
func (a *App) Bootstrap() error {
	stdlog.Println("[cloud-api] app bootstrapping...")
	for _, p := range a.providers {
		stdlog.Printf("[cloud-api] provider %s initializing...", p.Name())
		if err := p.Init(); err != nil {
			return fmt.Errorf("provider %s init: %w", p.Name(), err)
		}
	}
	for _, p := range a.providers {
		stdlog.Printf("[cloud-api] provider %s booting...", p.Name())
		if err := p.Boot(); err != nil {
			return fmt.Errorf("provider %s boot: %w", p.Name(), err)
		}
	}
	stdlog.Println("[cloud-api] app bootstrap completed")
	return nil
}

// Terminate 按逆序关闭 provider。
func (a *App) Terminate() error {
	stdlog.Println("[cloud-api] app terminating...")
	for i := len(a.providers) - 1; i >= 0; i-- {
		p := a.providers[i]
		stdlog.Printf("[cloud-api] provider %s closing...", p.Name())
		if err := p.Close(); err != nil {
			stdlog.Printf("[cloud-api] provider %s close failed: %v", p.Name(), err)
		}
	}
	stdlog.Println("[cloud-api] app terminated")
	return nil
}
