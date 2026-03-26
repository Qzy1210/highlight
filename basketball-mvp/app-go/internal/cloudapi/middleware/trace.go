package middleware

import (
	"fmt"
	"time"

	"github.com/gin-gonic/gin"
)

const traceIDKey = "trace_id"

// TraceID 为每个请求注入 trace_id，便于追踪日志与问题定位。
func TraceID() gin.HandlerFunc {
	return func(c *gin.Context) {
		id := c.GetHeader("X-Trace-Id")
		if id == "" {
			id = fmt.Sprintf("t-%d", time.Now().UnixNano())
		}
		c.Set(traceIDKey, id)
		c.Writer.Header().Set("X-Trace-Id", id)
		c.Next()
	}
}

// GetTraceID 从上下文读取 trace_id。
func GetTraceID(c *gin.Context) string {
	v, ok := c.Get(traceIDKey)
	if !ok {
		return ""
	}
	s, _ := v.(string)
	return s
}
