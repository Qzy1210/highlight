//go:build windows

package main

import (
	"fmt"
	"os/exec"
	"strings"
)

// openVideoSelectionDialog 通过 PowerShell 打开 Windows 视频文件选择框。
func openVideoSelectionDialog() (string, error) {
	script := `$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.OpenFileDialog; $d.Filter='Video Files|*.mp4;*.mov;*.mkv;*.avi;*.wmv;*.m4v|All Files|*.*'; $r=$d.ShowDialog(); if($r -ne [System.Windows.Forms.DialogResult]::OK){ exit 2 }; Write-Output $d.FileName`
	return runPowerShellDialog(script)
}

// openDirectorySelectionDialog 通过 PowerShell 打开 Windows 目录选择框。
func openDirectorySelectionDialog() (string, error) {
	script := `$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.FolderBrowserDialog; $r=$d.ShowDialog(); if($r -ne [System.Windows.Forms.DialogResult]::OK){ exit 2 }; Write-Output $d.SelectedPath`
	return runPowerShellDialog(script)
}

// runPowerShellDialog 执行对话框脚本并解析用户选择结果。
//
// 输入:
//   - script: PowerShell 脚本文本。
//
// 返回:
//   - string: 选择的路径。
//   - error: 执行失败、取消选择或无输出时返回错误。
func runPowerShellDialog(script string) (string, error) {
	out, err := exec.Command("powershell", "-NoProfile", "-Command", script).CombinedOutput()
	if err != nil {
		msg := strings.TrimSpace(string(out))
		if msg == "" {
			msg = err.Error()
		}
		return "", fmt.Errorf("open dialog failed: %s", msg)
	}
	path := strings.TrimSpace(string(out))
	if path == "" {
		return "", fmt.Errorf("no path selected")
	}
	return path, nil
}
