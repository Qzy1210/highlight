package config

var loggerInstance *Logger

// Logger 描述日志配置。
type Logger struct {
	Level    string      `mapstructure:"level"`
	Encoding string      `mapstructure:"encoding"`
	File     *LogFileCfg `mapstructure:"file"`
}

// LogFileCfg 描述本地日志文件配置。
type LogFileCfg struct {
	Open       bool   `mapstructure:"open"`
	OutputPath string `mapstructure:"output_path"`
}

// LoggerInstance 返回日志配置单例。
func LoggerInstance() *Logger {
	return loggerInstance
}
