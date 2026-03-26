package middleware

import (
	"time"

	cloudlog "basketball-mvp/app-go/internal/cloudapi/framework/log"
	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
)

// AccessLog 记录请求访问日志。
func AccessLog() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		cloudlog.Logger().Info("request",
			zap.String("method", c.Request.Method),
			zap.String("path", c.Request.URL.Path),
			zap.Int("status", c.Writer.Status()),
			zap.Int64("cost_ms", time.Since(start).Milliseconds()),
			zap.String("trace_id", GetTraceID(c)),
		)
	}
}
