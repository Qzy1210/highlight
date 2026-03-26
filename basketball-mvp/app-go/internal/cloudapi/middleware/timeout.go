package middleware

import (
	"context"
	"net/http"
	"time"

	"basketball-mvp/app-go/internal/cloudapi/response"

	"github.com/gin-gonic/gin"
)

// Timeout 为请求设置统一超时，防止连接长时间占用。
func Timeout(d time.Duration) gin.HandlerFunc {
	if d <= 0 {
		d = 30 * time.Second
	}
	return func(c *gin.Context) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), d)
		defer cancel()
		c.Request = c.Request.WithContext(ctx)
		done := make(chan struct{})
		go func() {
			c.Next()
			close(done)
		}()
		select {
		case <-done:
			return
		case <-ctx.Done():
			c.Abort()
			response.Error(c, http.StatusGatewayTimeout, 100408, "request timeout")
		}
	}
}
