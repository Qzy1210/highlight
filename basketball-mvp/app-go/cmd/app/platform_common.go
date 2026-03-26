package main

import "runtime"

// runtimeGOOS 返回当前运行时 GOOS（便于测试替换）。
func runtimeGOOS() string {
	return runtime.GOOS
}
