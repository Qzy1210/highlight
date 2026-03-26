package config

import (
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"

	"github.com/spf13/viper"
)

const includesKey = "includes"

var configPathVarMap = map[string]interface{}{
	"app":           &appInstance,
	"logger":        &loggerInstance,
	"mysql.default": &mysqlDefault,
	"auth":          &authInstance,
}

type initialConfig interface {
	initialization()
}

// Init 加载配置并将配置段绑定到对应结构体。
// path 指向主配置文件，env 用于可选环境覆盖（如 dev/prod）。
func Init(path string, env string) error {
	v := viper.New()
	v.SetConfigFile(path)
	v.SetEnvPrefix("MVP")
	v.AutomaticEnv()
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))

	if err := v.ReadInConfig(); err != nil {
		return fmt.Errorf("failed to read config file: %w", err)
	}
	if err := handleIncludes(v, path); err != nil {
		return fmt.Errorf("failed to handle includes: %w", err)
	}
	if env != "" {
		envConfigFile := fmt.Sprintf("%s.%s.yml", strings.TrimSuffix(path, filepath.Ext(path)), env)
		if _, err := os.Stat(envConfigFile); err == nil {
			v.SetConfigFile(envConfigFile)
			if err := v.MergeInConfig(); err != nil {
				return fmt.Errorf("failed to merge env config: %w", err)
			}
		}
	}
	return bindConfigData(v)
}

func handleIncludes(v *viper.Viper, mainConfigPath string) error {
	includes := v.GetStringSlice(includesKey)
	if len(includes) == 0 {
		return nil
	}
	basePath := filepath.Dir(mainConfigPath)
	for _, includeFile := range includes {
		includePath := filepath.Join(basePath, includeFile)
		if _, err := os.Stat(includePath); os.IsNotExist(err) {
			return fmt.Errorf("include config file not found: %s", includePath)
		}
		v.SetConfigFile(includePath)
		if err := v.MergeInConfig(); err != nil {
			return fmt.Errorf("failed to merge include config %s: %w", includePath, err)
		}
	}
	return nil
}

func bindConfigData(v *viper.Viper) error {
	for path, ptr := range configPathVarMap {
		if err := v.UnmarshalKey(path, ptr); err != nil {
			return fmt.Errorf("parse config %s failed: %w", path, err)
		}
	}
	for _, variable := range configPathVarMap {
		tv := reflect.ValueOf(variable).Elem()
		if tv.CanInterface() {
			i := tv.Interface()
			if initer, ok := i.(initialConfig); ok && !reflect.ValueOf(initer).IsNil() {
				initer.initialization()
			}
		}
	}
	return nil
}
