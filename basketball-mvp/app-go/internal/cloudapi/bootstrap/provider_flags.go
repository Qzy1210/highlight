package bootstrap

import (
	"flag"
	"os"
	"strings"
	"sync"

	"basketball-mvp/app-go/internal/cloudapi/framework/provider"
)

var (
	envFile       string
	parseFlagOnce sync.Once
)

// ProviderFlags 解析命令行参数。
func ProviderFlags() provider.Provider {
	return provider.NewProvider("flags", func() error {
		return initFlags()
	})
}

func initFlags() error {
	parseFlagOnce.Do(func() {
		defaultFile := strings.TrimSpace(os.Getenv("MVP_CLOUD_CONFIG"))
		if defaultFile == "" {
			defaultFile = "./conf/cloud/dev.yml"
		}
		flag.StringVar(&envFile, "f", defaultFile, "usage: /your/path/to/config-file")
		if !flag.Parsed() {
			flag.Parse()
		}
	})
	return nil
}
