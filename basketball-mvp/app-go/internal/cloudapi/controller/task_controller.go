package controller

import (
	"net/http"
	"strings"

	"basketball-mvp/app-go/internal/cloudapi/logic"
	"basketball-mvp/app-go/internal/cloudapi/middleware"
	"basketball-mvp/app-go/internal/cloudapi/model"
	"basketball-mvp/app-go/internal/cloudapi/response"

	"github.com/gin-gonic/gin"
)

// TaskController 处理任务相关接口。
type TaskController struct {
	tasks *logic.TaskLogic
}

// NewTaskController 创建任务控制器。
func NewTaskController(tasks *logic.TaskLogic) *TaskController {
	return &TaskController{tasks: tasks}
}

// Create 创建任务。
func (c *TaskController) Create(ctx *gin.Context) {
	var req model.CreateTaskRequest
	if err := ctx.ShouldBindJSON(&req); err != nil {
		response.Error(ctx, http.StatusBadRequest, 100400, err.Error())
		return
	}
	req.VideoPath = strings.TrimSpace(req.VideoPath)
	if req.VideoPath == "" {
		response.Error(ctx, http.StatusBadRequest, 100400, "video_path is required")
		return
	}
	task, err := c.tasks.CreateTask(middleware.UserID(ctx), req.VideoPath)
	if err != nil {
		response.Error(ctx, http.StatusInternalServerError, 100500, err.Error())
		return
	}
	response.OK(ctx, task)
}

// List 查询当前用户任务列表。
func (c *TaskController) List(ctx *gin.Context) {
	out, err := c.tasks.ListTasks(middleware.UserID(ctx))
	if err != nil {
		response.Error(ctx, http.StatusInternalServerError, 100500, err.Error())
		return
	}
	response.OK(ctx, out)
}

// Get 查询任务详情。
func (c *TaskController) Get(ctx *gin.Context) {
	taskID := strings.TrimSpace(ctx.Param("id"))
	out, err := c.tasks.GetTask(middleware.UserID(ctx), taskID)
	if err != nil {
		response.Error(ctx, http.StatusNotFound, 100404, "task not found")
		return
	}
	response.OK(ctx, out)
}

// Terminate 终止任务。
func (c *TaskController) Terminate(ctx *gin.Context) {
	taskID := strings.TrimSpace(ctx.Param("id"))
	if err := c.tasks.TerminateTask(middleware.UserID(ctx), taskID); err != nil {
		response.Error(ctx, http.StatusBadRequest, 100400, err.Error())
		return
	}
	response.OK(ctx, gin.H{
		"id":     taskID,
		"status": "terminated",
	})
}
