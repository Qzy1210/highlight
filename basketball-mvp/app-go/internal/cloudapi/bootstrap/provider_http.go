package bootstrap

import (
	"time"

	"basketball-mvp/app-go/internal/cloudapi/framework/config"
	cloudhttp "basketball-mvp/app-go/internal/cloudapi/framework/http"
	"basketball-mvp/app-go/internal/cloudapi/framework/provider"

	"github.com/gin-gonic/gin"
)

var appGin *gin.Engine

// ProviderHTTP 初始化 gin 引擎。
func ProviderHTTP() provider.Provider {
	return provider.NewProvider("http", func() error {
		appCfg := config.AppInstance()
		mode := "release"
		timeout := 60 * time.Second
		if appCfg != nil {
			if appCfg.Mode != "" {
				mode = appCfg.Mode
			}
			timeout = time.Duration(appCfg.RequestTimeoutMilli()) * time.Millisecond
		}
		appGin = cloudhttp.New(mode, timeout)
		return nil
	})
}

// GetGin 返回 gin 引擎实例。
func GetGin() *gin.Engine {
	return appGin
}
