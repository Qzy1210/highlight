package config

var appInstance *App

// App 描述云服务基础配置。
type App struct {
	Name             string `mapstructure:"name"`
	Env              string `mapstructure:"env"`
	Port             int    `mapstructure:"port"`
	Mode             string `mapstructure:"mode"`
	RequestTimeoutMS int    `mapstructure:"request_timeout_ms"`
}

// AppInstance 返回应用配置单例。
func AppInstance() *App {
	return appInstance
}

// RequestTimeoutMilli 返回请求超时毫秒值。
func (a *App) RequestTimeoutMilli() int {
	if a == nil || a.RequestTimeoutMS <= 0 {
		return 60000
	}
	return a.RequestTimeoutMS
}
