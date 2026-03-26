package http

import (
	"time"

	"basketball-mvp/app-go/internal/cloudapi/middleware"

	"github.com/gin-gonic/gin"
)

// New 创建云 API 的 gin 引擎，并挂载基础中间件链。
func New(mode string, timeout time.Duration) *gin.Engine {
	if mode == "" {
		mode = gin.ReleaseMode
	}
	gin.SetMode(mode)
	r := gin.New()
	r.Use(middleware.CORS())
	r.Use(middleware.TraceID())
	r.Use(middleware.Recovery())
	r.Use(middleware.Timeout(timeout))
	r.Use(middleware.AccessLog())
	return r
}
