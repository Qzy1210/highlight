//go:build darwin

package main

import (
	"fmt"

	"github.com/sqweek/dialog"
)

// openVideoSelectionDialog 打开 macOS 视频文件选择框。
//
// 返回:
//   - string: 用户选择的视频绝对路径。
//   - error: 取消或失败时返回错误。
func openVideoSelectionDialog() (string, error) {
	path, err := dialog.File().
		Title("选择篮球视频").
		Filter("Video Files", "mp4", "mov", "mkv", "avi", "wmv", "m4v").
		Load()
	if err != nil {
		return "", fmt.Errorf("open dialog failed: %w", err)
	}
	return path, nil
}

// openDirectorySelectionDialog 打开 macOS 目录选择框。
//
// 返回:
//   - string: 用户选择的目录绝对路径。
//   - error: 取消或失败时返回错误。
func openDirectorySelectionDialog() (string, error) {
	path, err := dialog.Directory().
		Title("选择导出目录").
		Browse()
	if err != nil {
		return "", fmt.Errorf("open dialog failed: %w", err)
	}
	return path, nil
}
