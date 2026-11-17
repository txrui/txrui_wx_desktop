"""使用标准库提供静态控制页面，并将接口请求分派到桥接对象公开方法。

接口参数取自请求中的 args 和 kwargs；服务默认监听本机，未实现请求鉴权。
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

WEBUI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webui")
if not os.path.isdir(WEBUI_DIR):
    WEBUI_DIR = os.path.join(os.getcwd(), "webui")

MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".png": "image/png", ".ico": "image/x-icon",
        ".svg": "image/svg+xml"}


class _Handler(BaseHTTPRequestHandler):
    bridge = None

    def log_message(self, *a):
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            path = "/index.html"
        if path.startswith("/api/"):
            self._send(404, b'{"ok": false}', "application/json")
            return
        asset_root = os.path.dirname(WEBUI_DIR) if path == "/logo.png" else WEBUI_DIR
        fp = os.path.normpath(os.path.join(asset_root, path.lstrip("/")))
        normalized_root = os.path.normpath(asset_root)
        if (not fp.startswith(normalized_root + os.sep) and fp != normalized_root) or not os.path.isfile(fp):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        _, ext = os.path.splitext(fp)
        try:
            with open(fp, "rb") as f:
                self._send(200, f.read(), MIME.get(ext.lower(), "application/octet-stream"))
        except OSError:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            self._send(404, b'{"ok": false}', "application/json")
            return
        name = path[len("/api/"):]
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
        except ValueError:
            data = {}
        args = data.get("args", []) if isinstance(data, dict) else []
        kwargs = data.get("kwargs", {}) if isinstance(data, dict) else {}
        if not isinstance(args, list):
            args = [args]
        if not isinstance(kwargs, dict):
            kwargs = {}
        fn = getattr(self.bridge, name, None)
        if fn is None or name.startswith("_"):
            self._send(404, json.dumps({"ok": False, "error": f"未知接口: {name}"},
                                       ensure_ascii=False).encode("utf-8"), "application/json")
            return
        try:
            res = fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if not isinstance(res, dict):
            res = {"ok": True, "result": res}
        self._send(200, json.dumps(res, ensure_ascii=False).encode("utf-8"), "application/json")


class WebServer:
    def __init__(self, bridge, host: str = "127.0.0.1", port: int = 17880):
        self.bridge = bridge
        self.host = host
        self.port = port
        self._srv: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        _Handler.bridge = self.bridge
        # 端口占用时向上漂移
        for p in range(self.port, self.port + 20):
            try:
                srv = ThreadingHTTPServer((self.host, p), _Handler)
                srv.daemon_threads = True
                self._srv = srv
                self.port = p
                break
            except OSError:
                continue
        if self._srv is None:
            raise RuntimeError("无可用端口")
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True,
                                        name="txrui-webserver")
        self._thread.start()
        return f"http://{self.host}:{self.port}/"

    def stop(self) -> None:
        srv, self._srv = self._srv, None
        if srv is None:
            return
        try:
            srv.shutdown()
        finally:
            # shutdown() 只停止 serve_forever，不会释放监听 socket。
            srv.server_close()
            thread, self._thread = self._thread, None
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=2)
