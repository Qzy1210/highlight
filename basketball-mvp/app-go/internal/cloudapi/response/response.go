package response

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// Payload 统一响应结构。
type Payload struct {
	Code    int         `json:"code"`
	Message string      `json:"message"`
	Data    interface{} `json:"data,omitempty"`
	TraceID string      `json:"trace_id,omitempty"`
}

// OK 返回成功响应。
func OK(c *gin.Context, data interface{}) {
	c.JSON(http.StatusOK, Payload{
		Code:    0,
		Message: "ok",
		Data:    data,
		TraceID: readTraceID(c),
	})
}

// Error 返回错误响应。
func Error(c *gin.Context, httpStatus, bizCode int, message string) {
	c.JSON(httpStatus, Payload{
		Code:    bizCode,
		Message: message,
		TraceID: readTraceID(c),
	})
}

func readTraceID(c *gin.Context) string {
	v, ok := c.Get("trace_id")
	if !ok {
		return ""
	}
	s, _ := v.(string)
	return s
}
