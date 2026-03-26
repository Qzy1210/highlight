package bootstrap

import (
	"basketball-mvp/app-go/internal/cloudapi/framework/drivers"
	"basketball-mvp/app-go/internal/cloudapi/framework/provider"
)

// ProviderDriver 初始化基础驱动（MySQL 等）。
func ProviderDriver() provider.Provider {
	return provider.NewProvider("driver", func() error {
		return drivers.InitDrivers()
	}, nil, func() error {
		return drivers.TerminateDrivers()
	})
}
