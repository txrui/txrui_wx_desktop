"""Windows Server 环境下桌面窗口不可用时应保留网页控制台。"""
from types import SimpleNamespace
from unittest.mock import Mock, patch

from txrui import web


class FakeServer:
    def __init__(self, bridge, host, port):
        self.bridge = bridge
        self.host = host
        self.port = port
        self.stopped = False

    def start(self):
        return f"http://{self.host}:{self.port}/"

    def stop(self):
        self.stopped = True


class FakeRuntime:
    def __init__(self):
        self.prepared = False
        self.stopped = False

    def prepare_wechat(self):
        self.prepared = True

    def stop(self):
        self.stopped = True


def test_explicit_browser_mode_skips_webview_and_cleans_up():
    runtime = FakeRuntime()
    server = FakeServer(None, "127.0.0.1", 17880)
    with patch("txrui.webserver.WebServer", return_value=server), \
            patch("txrui.web._serve_in_browser") as serve_browser:
        web.run_web(runtime, SimpleNamespace(), browser=True)

    assert runtime.prepared
    assert runtime.stopped
    assert server.stopped
    serve_browser.assert_called_once_with("http://127.0.0.1:17880/")


def test_windows_missing_chromium_skips_legacy_ie():
    runtime = FakeRuntime()
    server = FakeServer(None, "127.0.0.1", 17880)
    fake_webview = SimpleNamespace(create_window=Mock())
    with patch("txrui.webserver.WebServer", return_value=server), \
            patch("txrui.web.sys.platform", "win32"), \
            patch("txrui.desktop_runtime.prepare_desktop_runtime"), \
            patch("txrui.desktop_runtime.initialize_webview",
                  return_value=SimpleNamespace(renderer="mshtml")), \
            patch.dict("sys.modules", {"webview": fake_webview}), \
            patch("txrui.web._serve_in_browser") as serve_browser:
        web.run_web(runtime, SimpleNamespace())
    fake_webview.create_window.assert_not_called()
    serve_browser.assert_called_once()
    assert runtime.stopped and server.stopped


def test_create_window_failure_falls_back_to_browser():
    runtime = FakeRuntime()
    server = FakeServer(None, "127.0.0.1", 17880)
    webview = SimpleNamespace(create_window=Mock(side_effect=RuntimeError("WebView2 missing")))
    with patch("txrui.webserver.WebServer", return_value=server), \
            patch("txrui.web.sys.platform", "linux"), \
            patch.dict("sys.modules", {"webview": webview}), \
            patch("txrui.web._serve_in_browser") as serve_browser:
        web.run_web(runtime, SimpleNamespace())

    assert runtime.stopped
    assert server.stopped
    serve_browser.assert_called_once_with("http://127.0.0.1:17880/")


def test_webview_start_failure_falls_back_and_cleans_up():
    class ClosingEvent:
        def __iadd__(self, callback):
            self.callback = callback
            return self

    class FakeWindow:
        def __init__(self):
            self.events = SimpleNamespace(closing=ClosingEvent())
            self.destroyed = False

        def destroy(self):
            self.destroyed = True

    runtime = FakeRuntime()
    server = FakeServer(None, "127.0.0.1", 17880)
    window = FakeWindow()
    fake_webview = SimpleNamespace(
        create_window=Mock(return_value=window),
        start=Mock(side_effect=RuntimeError("WebView2 runtime unavailable")),
    )
    with patch("txrui.webserver.WebServer", return_value=server), \
            patch("txrui.web.sys.platform", "linux"), \
            patch.dict("sys.modules", {"webview": fake_webview, "pystray": None}), \
            patch("txrui.web._serve_in_browser") as serve_browser:
        web.run_web(runtime, SimpleNamespace())

    assert window.destroyed
    assert runtime.stopped
    assert server.stopped
    serve_browser.assert_called_once_with("http://127.0.0.1:17880/")
