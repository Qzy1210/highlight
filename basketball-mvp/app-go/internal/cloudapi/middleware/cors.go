package middleware

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// CORS 允许桌面端页面跨域访问云端 API。
func CORS() gin.HandlerFunc {
	return func(c *gin.Context) {
		h := c.Writer.Header()
		h.Set("Access-Control-Allow-Origin", "*")
		h.Set("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
		h.Set("Access-Control-Allow-Headers", "Content-Type,Authorization,X-Trace-Id")
		h.Set("Access-Control-Expose-Headers", "X-Trace-Id")
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}
