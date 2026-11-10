#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_GO_DIR="$ROOT_DIR/app-go"
DIST_DIR="$ROOT_DIR/dist"
ARCH_INPUT="host"
REQUIRE_RUNTIME="0"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/build_macos_app.sh [--arch host|arm64|amd64|universal] [--require-runtime]

Runtime bundle (optional but recommended):
  runtime/macos-arm64/
  runtime/macos-amd64/
  runtime/macos-universal/   # for --arch universal
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch)
      ARCH_INPUT="${2:-}"
      shift 2
      ;;
    --require-runtime)
      REQUIRE_RUNTIME="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

normalize_arch() {
  case "$1" in
    arm64|aarch64) echo "arm64" ;;
    amd64|x86_64) echo "amd64" ;;
    universal) echo "universal" ;;
    host|"") normalize_arch "$(uname -m)" ;;
    *)
      echo "unsupported architecture: $1" >&2
      exit 1
      ;;
  esac
}

ARCH="$(normalize_arch "$ARCH_INPUT")"
APP_NAME="BasketballMVP"
if [[ "$ARCH_INPUT" != "host" ]]; then
  APP_NAME="BasketballMVP-${ARCH}"
fi
APP_BUNDLE="$DIST_DIR/${APP_NAME}.app"
APP_MACOS_DIR="$APP_BUNDLE/Contents/MacOS"
APP_RES_DIR="$APP_BUNDLE/Contents/Resources/project"

build_go() {
  local arch="$1"
  local output="$2"
  local pkg="$3"
  pushd "$APP_GO_DIR" >/dev/null
  CGO_ENABLED=1 GOOS=darwin GOARCH="$arch" go build -o "$output" "$pkg"
  popd >/dev/null
}

build_go_universal() {
  local output="$1"
  local pkg="$2"
  local tmpdir="$3"
  local arm_bin="$tmpdir/$(basename "$output").arm64"
  local amd_bin="$tmpdir/$(basename "$output").amd64"
  build_go "arm64" "$arm_bin" "$pkg"
  build_go "amd64" "$amd_bin" "$pkg"
  lipo -create -output "$output" "$arm_bin" "$amd_bin"
}

copy_runtime_bundle() {
  local runtime_arch="$1"
  local src="$ROOT_DIR/runtime/macos-${runtime_arch}"
  local dst="$APP_RES_DIR/runtime"
  if [[ -d "$src" ]]; then
    mkdir -p "$dst"
    cp -R "$src"/. "$dst/"
    echo "Bundled runtime from: $src"
  else
    if [[ "$REQUIRE_RUNTIME" == "1" ]]; then
      echo "ERROR: runtime bundle not found: $src" >&2
      exit 1
    fi
    echo "WARN: runtime bundle not found: $src"
    echo "      app will fallback to system Python/FFmpeg."
  fi
}

copy_detector_model() {
  # 拷贝检测模型到 App 内置目录。
  # 入参：$1=模型类别名（hoop/ball），$2=训练产物 glob 目录。
  # 优先使用仓库内 models/<kind>/best.onnx（可入库、可复现），
  # 其次回退到训练目录里最新的 best.onnx。
  local kind="$1"
  local run_dir="$2"
  local embedded="$ROOT_DIR/models/$kind/best.onnx"
  local dst_dir="$APP_RES_DIR/models/$kind"
  mkdir -p "$dst_dir"

  if [[ -f "$embedded" ]]; then
    cp "$embedded" "$dst_dir/best.onnx"
    echo "Bundled $kind model from: $embedded"
    return
  fi

  local matches=()
  if [[ -d "$run_dir" ]]; then
    while IFS= read -r p; do
      matches+=("$p")
    done < <(find "$run_dir" -type f -path '*/weights/best.onnx' 2>/dev/null)
  fi

  if [[ ${#matches[@]} -eq 0 ]]; then
    echo "WARN: $kind model not found at $embedded or under: $run_dir"
    echo "      expected path pattern: models/$kind/best.onnx or */weights/best.onnx"
    return
  fi

  local latest
  latest="$(ls -1t "${matches[@]}" | head -n 1)"
  if [[ -n "$latest" && -f "$latest" ]]; then
    cp "$latest" "$dst_dir/best.onnx"
    echo "Bundled $kind model from: $latest"
  else
    echo "WARN: $kind model candidate invalid: $latest"
  fi
}

mkdir -p "$DIST_DIR"
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_MACOS_DIR" "$APP_RES_DIR/app-go"

tmpdir=""
if [[ "$ARCH" == "universal" ]]; then
  tmpdir="$(mktemp -d)"
  build_go_universal "$APP_MACOS_DIR/basketball_mvp_server" "./cmd/app" "$tmpdir"
  build_go_universal "$APP_MACOS_DIR/BasketballMVP" "./cmd/desktop" "$tmpdir"
  copy_runtime_bundle "universal"
else
  build_go "$ARCH" "$APP_MACOS_DIR/basketball_mvp_server" "./cmd/app"
  build_go "$ARCH" "$APP_MACOS_DIR/BasketballMVP" "./cmd/desktop"
  copy_runtime_bundle "$ARCH"
fi

cp -R "$ROOT_DIR/engine-py" "$APP_RES_DIR/"
cp -R "$ROOT_DIR/configs" "$APP_RES_DIR/"
cp -R "$ROOT_DIR/app-go/web" "$APP_RES_DIR/app-go/"
copy_detector_model "hoop" "$ROOT_DIR/training/hoop_detector/runs"
copy_detector_model "ball" "$ROOT_DIR/training/ball_detector/runs"
chmod +x "$APP_MACOS_DIR/BasketballMVP" "$APP_MACOS_DIR/basketball_mvp_server"

cat > "$APP_BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>BasketballMVP</string>
  <key>CFBundleIdentifier</key>
  <string>cn.360.basketballmvp.${ARCH}</string>
  <key>CFBundleName</key>
  <string>${APP_NAME}</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>11.0</string>
</dict>
</plist>
PLIST

if [[ -n "$tmpdir" ]]; then
  rm -rf "$tmpdir"
fi

echo "Built: $APP_BUNDLE"
