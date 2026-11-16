"""视频预览必须按图片上传，取图失败时保留视频占位。"""
import asyncio
from unittest.mock import AsyncMock

from txrui import collector


def test_video_capture_returns_png_metadata(monkeypatch):
    class Backend:
        def media_screen_rect(self, bubble):
            return None

        def crop_media(self, bubble):
            return b"\x89PNG\r\n\x1a\npreview"

    data, filename, mime = asyncio.run(collector._grab_video(Backend(), None, {"kind": "video"}))
    assert data.startswith(b"\x89PNG")
    assert filename == "video_preview.png"
    assert mime == "image/png"


def test_uploaded_video_preview_segment_is_image(monkeypatch):
    grab = AsyncMock(return_value=(b"png", "video_preview.png", "image/png"))
    upload = AsyncMock(return_value={"ok": True, "media_id": "preview-id", "mime": "image/png"})
    monkeypatch.setattr(collector, "_grab_video", grab)
    monkeypatch.setattr(collector, "_upload", upload)
    segments = asyncio.run(collector._upload_bubbles(None, None, [{"kind": "video", "text": "00:05"}]))
    seg = segments[0]
    assert seg["type"] == "image"
    assert seg["mime"] == "image/png"
    assert seg["text"] == "[视频预览]"
    assert seg["extra"]["original_type"] == "video"
    assert seg["extra"]["preview"] is True


def test_video_without_preview_remains_placeholder(monkeypatch):
    monkeypatch.setattr(collector, "_grab_video", AsyncMock(return_value=(b"", "video_preview.png", "image/png")))
    segments = asyncio.run(collector._upload_bubbles(None, None, [{"kind": "video"}]))
    assert segments[0]["type"] == "video"
    assert segments[0]["extra"]["placeholder"] is True
    assert "media_id" not in segments[0]
