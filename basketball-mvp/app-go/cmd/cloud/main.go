package main

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"basketball-mvp/app-go/internal/cloudapi/bootstrap"
	cloudcfg "basketball-mvp/app-go/internal/cloudapi/framework/config"
	cloudlog "basketball-mvp/app-go/internal/cloudapi/framework/log"
	"basketball-mvp/app-go/internal/cloudapi/router"
	"go.uber.org/zap"
)

func main() {
	app, err := bootstrap.New()
	if err != nil {
		panic(fmt.Sprintf("failed to create app: %v", err))
	}

	jwtSvc, authLogic, taskLogic, err := bootstrap.BuildDeps()
	if err != nil {
		cloudlog.Logger().Fatal("build dependencies failed", zap.Error(err))
	}
	router.Register(app.GetGin(), router.Dependencies{
		JWT:   jwtSvc,
		Auth:  authLogic,
		Tasks: taskLogic,
	})

	port := resolvePort()
	srv := &http.Server{
		Addr:    fmt.Sprintf(":%d", port),
		Handler: app.GetGin(),
	}

	go func() {
		cloudlog.Logger().Info("starting cloud api server", zap.Int("port", port))
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			cloudlog.Logger().Fatal("cloud api server failed", zap.Error(err))
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		cloudlog.Logger().Error("shutdown cloud api server failed", zap.Error(err))
	}
	if err := app.Terminate(); err != nil {
		cloudlog.Logger().Error("terminate providers failed", zap.Error(err))
	}
}

func resolvePort() int {
	if cfg := cloudcfg.AppInstance(); cfg != nil && cfg.Port > 0 {
		return cfg.Port
	}
	raw := strings.TrimSpace(os.Getenv("MVP_CLOUD_PORT"))
	if raw == "" {
		return 8090
	}
	n, err := strconv.Atoi(raw)
	if err != nil || n <= 0 || n > 65535 {
		return 8090
	}
	return n
}
