package config

import (
	"encoding/json"
	"fmt"
	"os"

	"basketball-mvp/app-go/internal/models"
)

// LoadPipelineConfig 读取并标准化流水线配置。
//
// 输入:
//   - path: 配置文件路径。
//
// 返回:
//   - models.PipelineConfig: 解析后的配置（缺省值已补齐）。
//   - error: 文件打开或 JSON 解析失败时返回错误。
func LoadPipelineConfig(path string) (models.PipelineConfig, error) {
	f, err := os.Open(path)
	if err != nil {
		return models.PipelineConfig{}, fmt.Errorf("open config: %w", err)
	}
	defer f.Close()

	var cfg models.PipelineConfig
	if err := json.NewDecoder(f).Decode(&cfg); err != nil {
		return models.PipelineConfig{}, fmt.Errorf("decode config: %w", err)
	}
	if cfg.PreSeconds <= 0 {
		cfg.PreSeconds = 4
	}
	if cfg.PostSeconds <= 0 {
		cfg.PostSeconds = 2
	}
	if cfg.CooldownSec <= 0 {
		cfg.CooldownSec = 2
	}
	return cfg, nil
}
