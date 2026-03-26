package controller

import (
	"net/http"

	"basketball-mvp/app-go/internal/cloudapi/logic"
	"basketball-mvp/app-go/internal/cloudapi/middleware"
	"basketball-mvp/app-go/internal/cloudapi/model"
	"basketball-mvp/app-go/internal/cloudapi/response"

	"github.com/gin-gonic/gin"
)

// AuthController 处理鉴权接口。
type AuthController struct {
	auth *logic.AuthLogic
}

// NewAuthController 创建鉴权控制器。
func NewAuthController(auth *logic.AuthLogic) *AuthController {
	return &AuthController{auth: auth}
}

// Login 登录接口。
func (c *AuthController) Login(ctx *gin.Context) {
	var req model.LoginRequest
	if err := ctx.ShouldBindJSON(&req); err != nil {
		response.Error(ctx, http.StatusBadRequest, 100400, err.Error())
		return
	}
	out, err := c.auth.Login(req)
	if err != nil {
		response.Error(ctx, http.StatusUnauthorized, 100401, err.Error())
		return
	}
	response.OK(ctx, out)
}

// Refresh 刷新 access token。
func (c *AuthController) Refresh(ctx *gin.Context) {
	var req model.RefreshTokenRequest
	if err := ctx.ShouldBindJSON(&req); err != nil {
		response.Error(ctx, http.StatusBadRequest, 100400, err.Error())
		return
	}
	out, err := c.auth.Refresh(req)
	if err != nil {
		response.Error(ctx, http.StatusUnauthorized, 100401, err.Error())
		return
	}
	response.OK(ctx, out)
}

// Me 当前用户信息接口。
func (c *AuthController) Me(ctx *gin.Context) {
	userID := middleware.UserID(ctx)
	u, err := c.auth.Me(userID)
	if err != nil {
		response.Error(ctx, http.StatusNotFound, 100404, "user not found")
		return
	}
	response.OK(ctx, gin.H{
		"id":       u.ID,
		"username": u.Username,
	})
}
