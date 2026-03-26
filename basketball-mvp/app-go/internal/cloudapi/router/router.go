package router

import (
	"net/http"

	"basketball-mvp/app-go/internal/cloudapi/auth"
	"basketball-mvp/app-go/internal/cloudapi/controller"
	"basketball-mvp/app-go/internal/cloudapi/logic"
	"basketball-mvp/app-go/internal/cloudapi/middleware"

	"github.com/gin-gonic/gin"
)

// Dependencies 聚合路由依赖，便于装配和测试。
type Dependencies struct {
	JWT   *auth.JWTService
	Auth  *logic.AuthLogic
	Tasks *logic.TaskLogic
}

// Register 注册云 API 路由。
func Register(r *gin.Engine, dep Dependencies) {
	r.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	})

	api := r.Group("/api/v1")
	{
		authCtl := controller.NewAuthController(dep.Auth)
		api.POST("/auth/login", authCtl.Login)
		api.POST("/auth/refresh", authCtl.Refresh)

		authorized := api.Group("")
		authorized.Use(middleware.RequireAuth(dep.JWT))
		{
			authorized.GET("/auth/me", authCtl.Me)

			taskCtl := controller.NewTaskController(dep.Tasks)
			authorized.POST("/jobs", taskCtl.Create)
			authorized.GET("/jobs", taskCtl.List)
			authorized.GET("/jobs/:id", taskCtl.Get)
			authorized.POST("/jobs/:id/terminate", taskCtl.Terminate)
		}
	}
}
