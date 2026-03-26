//go:build !darwin && !windows

package main

import "fmt"

// openVideoSelectionDialog 非 macOS/Windows 平台的占位实现。
func openVideoSelectionDialog() (string, error) {
	return "", fmt.Errorf("dialog API is not implemented on this platform")
}

// openDirectorySelectionDialog 非 macOS/Windows 平台的占位实现。
func openDirectorySelectionDialog() (string, error) {
	return "", fmt.Errorf("dialog API is not implemented on this platform")
}
