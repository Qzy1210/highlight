#!/usr/bin/env python3
"""本地进球真值标注工具（零依赖，仅用标准库）。

启动后在浏览器里逐条播放视频，在“进球发生”的时刻打点，导出真值 JSON。
真值用于后续 compare_events.py 对 MOG2 / YOLO+MOG2 两种检测做事件级对比。

用法:
    python3 scripts/annotate_truth.py \
        --videos /path/to/video_dir \
        --truth-dir /path/to/basketball-mvp/workspace/truth \
        --port 8765

HTTP 接口:
    GET  /                     标注页面
    GET  /api/videos           视频列表
    GET  /video/<name>         视频流（支持 Range，便于拖动进度条）
    GET  /api/truth/<name>     读取已标注真值
    POST /api/truth/<name>     保存真值 {events: [{time_sec, note}]}
"""

import argparse
import json
import mimetypes
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

# 允许的视频扩展名
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}

# 允许出现在文件名里的字符（防止路径穿越）
_SAFE_NAME = re.compile(r"^[^/\\]+$")


class AnnotatorServer(ThreadingHTTPServer):
    """携带视频目录与真值目录的 HTTP 服务。"""

    def __init__(self, addr, handler, videos_dir: Path, truth_dir: Path, html_path: Path):
        super().__init__(addr, handler)
        self.videos_dir = videos_dir
        self.truth_dir = truth_dir
        self.html_path = html_path


def list_videos(videos_dir: Path):
    """列出可用视频（按名字排序）。"""
    if not videos_dir.is_dir():
        return []
    out = []
    for p in sorted(videos_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            out.append(p.name)
    return out


def truth_path(truth_dir: Path, name: str) -> Path:
    """由视频名推导真值 JSON 路径。"""
    stem = Path(name).stem
    return truth_dir / f"{stem}.truth.json"


class Handler(BaseHTTPRequestHandler):
    """请求处理：页面 / 视频流 / 真值读写。"""

    server: AnnotatorServer

    def log_message(self, fmt, *args):  # noqa: A003 - 覆盖基类以降低噪声
        pass

    # ---------- helpers ----------
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _safe_video_path(self, name: str):
        """把 URL 中的名字解析为 videos_dir 下的真实文件路径。

        Returns:
            合法路径，或 None（非法/不存在）。
        """
        name = unquote(name)
        if not name or not _SAFE_NAME.match(name):
            return None
        path = (self.server.videos_dir / name).resolve()
        try:
            path.relative_to(self.server.videos_dir.resolve())
        except ValueError:
            return None
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTS:
            return None
        return path

    # ---------- GET ----------
    def do_GET(self):  # noqa: N802 - 基类命名
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/" or route == "/index.html":
            return self._serve_html()
        if route == "/api/videos":
            return self._send_json({"videos": list_videos(self.server.videos_dir)})
        if route.startswith("/api/truth/"):
            return self._get_truth(route[len("/api/truth/"):])
        if route.startswith("/video/"):
            return self._serve_video(route[len("/video/"):])

        self.send_error(404, "not found")

    def _serve_html(self):
        try:
            body = self.server.html_path.read_bytes()
        except OSError as e:
            self.send_error(500, f"read html: {e}")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _get_truth(self, name: str):
        if self._safe_video_path(name) is None:
            return self.send_error(404, "video not found")
        tp = truth_path(self.server.truth_dir, name)
        if tp.is_file():
            try:
                return self._send_json(json.loads(tp.read_text(encoding="utf-8")))
            except Exception as e:  # noqa: BLE001
                return self._send_json({"events": [], "error": str(e)})
        return self._send_json({"video": name, "events": []})

    def _serve_video(self, name: str):
        """流式返回视频，支持单段 Range（进度条拖动）。"""
        path = self._safe_video_path(name)
        if path is None:
            return self.send_error(404, "video not found")

        file_size = path.stat().st_size
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        range_header = self.headers.get("Range")

        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not m:
                return self.send_error(400, "bad range")
            start_s, end_s = m.group(1), m.group(2)
            if start_s == "":
                # bytes=-N 表示最后 N 字节
                length = int(end_s or 0)
                start = max(0, file_size - length)
                end = file_size - 1
            else:
                start = int(start_s)
                end = int(end_s) if end_s else file_size - 1
            end = min(end, file_size - 1)
            if start > end or start >= file_size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{file_size}")
                self.end_headers()
                return
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Content-Length", str(length))
            self.end_headers()
            self._write_file_slice(path, start, length)
            return

        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(file_size))
        self.end_headers()
        self._write_file_slice(path, 0, file_size)

    def _write_file_slice(self, path: Path, start: int, length: int):
        chunk = 1024 * 512
        remaining = length
        try:
            with open(path, "rb") as f:
                f.seek(start)
                while remaining > 0:
                    data = f.read(min(chunk, remaining))
                    if not data:
                        break
                    self.wfile.write(data)
                    remaining -= len(data)
        except (BrokenPipeError, ConnectionResetError):
            # 浏览器拖动进度条会中断旧连接，属正常现象。
            pass

    # ---------- POST ----------
    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        if not route.startswith("/api/truth/"):
            return self.send_error(404, "not found")

        name = route[len("/api/truth/"):]
        if self._safe_video_path(name) is None:
            return self.send_error(404, "video not found")

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.send_error(400, "bad content-length")
        if length <= 0 or length > 5 * 1024 * 1024:
            return self.send_error(413, "payload too large or empty")

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            return self.send_error(400, "invalid json")

        events_in = payload.get("events", [])
        if not isinstance(events_in, list):
            return self.send_error(400, "events must be a list")

        cleaned = []
        for item in events_in:
            if not isinstance(item, dict):
                continue
            try:
                t = float(item.get("time_sec"))
            except (TypeError, ValueError):
                continue
            if t < 0:
                continue
            cleaned.append({"time_sec": round(t, 3), "note": str(item.get("note", "")).strip()})
        cleaned.sort(key=lambda e: e["time_sec"])

        record = {
            "video": name,
            "video_path": str((self.server.videos_dir / name).resolve()),
            "duration_sec": payload.get("duration_sec"),
            "events": cleaned,
        }

        self.server.truth_dir.mkdir(parents=True, exist_ok=True)
        tp = truth_path(self.server.truth_dir, name)
        tp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._send_json({"ok": True, "saved": str(tp), "count": len(cleaned)})


def main():
    parser = argparse.ArgumentParser(description="Local basketball goal truth annotator")
    default_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--videos", default=str(Path(default_root).parents[0] / "video"),
                        help="video directory to annotate")
    parser.add_argument("--truth-dir", default=str(default_root / "workspace" / "truth"),
                        help="output directory for truth json")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    videos_dir = Path(args.videos).expanduser().resolve()
    truth_dir = Path(args.truth_dir).expanduser().resolve()
    html_path = Path(__file__).resolve().parent / "annotator.html"

    if not videos_dir.is_dir():
        raise SystemExit(f"videos dir not found: {videos_dir}")
    if not html_path.is_file():
        raise SystemExit(f"annotator.html not found: {html_path}")

    truth_dir.mkdir(parents=True, exist_ok=True)
    server = AnnotatorServer((args.host, args.port), Handler, videos_dir, truth_dir, html_path)
    url = f"http://{args.host}:{args.port}/"
    print(f"videos : {videos_dir}")
    print(f"truth  : {truth_dir}")
    print(f"videos found: {len(list_videos(videos_dir))}")
    print(f"open   : {url}")
    print("Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
