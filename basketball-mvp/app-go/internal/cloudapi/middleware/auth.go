package middleware

import (
	"net/http"
	"strings"

	"basketball-mvp/app-go/internal/cloudapi/auth"
	"basketball-mvp/app-go/internal/cloudapi/response"

	"github.com/gin-gonic/gin"
)

const userIDKey = "auth_user_id"
const usernameKey = "auth_username"

// RequireAuth 校验 Bearer Token，并将用户信息注入上下文。
func RequireAuth(jwtSvc *auth.JWTService) gin.HandlerFunc {
	return func(c *gin.Context) {
		header := strings.TrimSpace(c.GetHeader("Authorization"))
		parts := strings.SplitN(header, " ", 2)
		if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
			response.Error(c, http.StatusUnauthorized, 100401, "missing bearer token")
			c.Abort()
			return
		}
		token := strings.TrimSpace(parts[1])
		claims, err := jwtSvc.ParseAccess(token)
		if err != nil {
			response.Error(c, http.StatusUnauthorized, 100401, "invalid token")
			c.Abort()
			return
		}
		c.Set(userIDKey, claims.UserID)
		c.Set(usernameKey, claims.Username)
		c.Next()
	}
}

// UserID 读取当前登录用户 ID。
func UserID(c *gin.Context) string {
	v, _ := c.Get(userIDKey)
	s, _ := v.(string)
	return s
}

// Username 读取当前登录用户名。
func Username(c *gin.Context) string {
	v, _ := c.Get(usernameKey)
	s, _ := v.(string)
	return s
}
