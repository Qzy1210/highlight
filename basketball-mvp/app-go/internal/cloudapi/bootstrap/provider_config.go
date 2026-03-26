package bootstrap

import (
	"fmt"
	"os"
	"strings"

	"basketball-mvp/app-go/internal/cloudapi/framework/config"
	"basketball-mvp/app-go/internal/cloudapi/framework/provider"
)

// ProviderConfig 读取并绑定配置。
func ProviderConfig() provider.Provider {
	return provider.NewProvider("config", func() error {
		env := strings.TrimSpace(os.Getenv("MVP_CLOUD_ENV"))
		if err := config.Init(envFile, env); err != nil {
			return fmt.Errorf("failed to load config: %w", err)
		}
		return nil
	})
}
