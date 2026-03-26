package bootstrap

import (
	"fmt"

	cloudlog "basketball-mvp/app-go/internal/cloudapi/framework/log"
	"basketball-mvp/app-go/internal/cloudapi/framework/provider"
)

// ProviderLogger 初始化日志。
func ProviderLogger() provider.Provider {
	return provider.NewProvider("logger", func() error {
		if _, err := cloudlog.New(); err != nil {
			return fmt.Errorf("failed to create logger: %w", err)
		}
		return nil
	}, nil, func() error {
		return cloudlog.Close()
	})
}
