package middleware

import (
	"net/http"

	cloudlog "basketball-mvp/app-go/internal/cloudapi/framework/log"
	"basketball-mvp/app-go/internal/cloudapi/response"

	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
)

// Recovery 捕获 panic 并返回标准错误响应。
func Recovery() gin.HandlerFunc {
	return gin.CustomRecovery(func(c *gin.Context, err interface{}) {
		cloudlog.Logger().Error("panic recovered",
			zap.Any("panic", err),
			zap.String("trace_id", GetTraceID(c)),
		)
		response.Error(c, http.StatusInternalServerError, 100500, "internal server error")
	})
}
