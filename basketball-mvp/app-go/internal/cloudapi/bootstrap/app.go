package bootstrap

import "basketball-mvp/app-go/internal/cloudapi/framework"

// New 创建并启动云服务基础设施容器。
func New() (*framework.App, error) {
	app := framework.New()

	// provider 顺序与 gin_fram 保持一致：flags -> config -> logger -> driver -> http。
	app.AddProvider(ProviderFlags())
	app.AddProvider(ProviderConfig())
	app.AddProvider(ProviderLogger())
	app.AddProvider(ProviderDriver())
	app.AddProvider(ProviderHTTP())

	if err := app.Bootstrap(); err != nil {
		return nil, err
	}
	app.Gin = GetGin()
	return app, nil
}
