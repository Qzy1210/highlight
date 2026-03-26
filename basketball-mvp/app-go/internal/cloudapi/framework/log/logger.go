package log

import (
	"fmt"
	"os"
	"strings"

	"basketball-mvp/app-go/internal/cloudapi/framework/config"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

var (
	logger   *zap.Logger
	fileSink *os.File
)

// New 初始化日志单例。
func New() (*zap.Logger, error) {
	cfg := config.LoggerInstance()
	if cfg == nil {
		cfg = &config.Logger{Level: "info", Encoding: "console"}
	}

	level := parseLevel(cfg.Level)
	encoder := newEncoder(cfg.Encoding)
	writers := []zapcore.WriteSyncer{zapcore.AddSync(os.Stdout)}

	if cfg.File != nil && cfg.File.Open && strings.TrimSpace(cfg.File.OutputPath) != "" {
		if err := os.MkdirAll(filepathDir(cfg.File.OutputPath), 0o755); err != nil {
			return nil, fmt.Errorf("create logger dir: %w", err)
		}
		f, err := os.OpenFile(cfg.File.OutputPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		if err != nil {
			return nil, fmt.Errorf("open logger file: %w", err)
		}
		fileSink = f
		writers = append(writers, zapcore.AddSync(f))
	}

	core := zapcore.NewCore(encoder, zapcore.NewMultiWriteSyncer(writers...), level)
	logger = zap.New(core, zap.AddCaller(), zap.AddStacktrace(zapcore.ErrorLevel))
	return logger, nil
}

// Logger 返回日志单例。
func Logger() *zap.Logger {
	if logger == nil {
		return zap.NewNop()
	}
	return logger
}

// Close 关闭日志资源。
func Close() error {
	if logger != nil {
		_ = logger.Sync()
	}
	if fileSink != nil {
		err := fileSink.Close()
		fileSink = nil
		return err
	}
	return nil
}

func parseLevel(level string) zapcore.Level {
	switch strings.ToLower(strings.TrimSpace(level)) {
	case "debug":
		return zapcore.DebugLevel
	case "warn", "warning":
		return zapcore.WarnLevel
	case "error":
		return zapcore.ErrorLevel
	default:
		return zapcore.InfoLevel
	}
}

func newEncoder(encoding string) zapcore.Encoder {
	encCfg := zapcore.EncoderConfig{
		TimeKey:        "time",
		LevelKey:       "level",
		NameKey:        "logger",
		CallerKey:      "caller",
		MessageKey:     "msg",
		StacktraceKey:  "stacktrace",
		LineEnding:     zapcore.DefaultLineEnding,
		EncodeLevel:    zapcore.CapitalLevelEncoder,
		EncodeTime:     zapcore.ISO8601TimeEncoder,
		EncodeDuration: zapcore.SecondsDurationEncoder,
		EncodeCaller:   zapcore.ShortCallerEncoder,
	}
	if strings.EqualFold(strings.TrimSpace(encoding), "json") {
		return zapcore.NewJSONEncoder(encCfg)
	}
	return zapcore.NewConsoleEncoder(encCfg)
}

func filepathDir(path string) string {
	idx := strings.LastIndex(path, string(os.PathSeparator))
	if idx <= 0 {
		return "."
	}
	return path[:idx]
}
