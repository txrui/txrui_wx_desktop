"""抓取当前微信窗口并离线复现消息识别，不发送消息。"""
import json
from pathlib import Path
from txrui.backend import TxruiBackend
from txrui import ocr, media, scale

root = Path(__file__).resolve().parent / 'diagnostics' / 'messages'
root.mkdir(parents=True, exist_ok=True)
backend = TxruiBackend()
backend.connect()
shot = backend._shot(foreground=False)
if shot is None:
    raise RuntimeError('窗口截图失败')
shot.save(root / 'window.png')
w,h = shot.size
r = backend._message_region
region = shot.crop((int(w*r[0]),int(h*r[1]),int(w*r[2]),int(h*r[3])))
region.save(root / 'region.png')
items = ocr.ocr_image(region)
bubbles = media.detect_media_bubbles(region, items, scale.active_scale())
from unittest.mock import patch

# 使用同一张截图回放，排除两次截图或 OCR 波动影响。
title = backend.read_title(foreground=False)
with patch.object(backend, '_shot', return_value=shot), \
        patch.object(backend, 'read_title', return_value=title), \
        patch('txrui.backend._ocr.ocr_image', return_value=items):
    messages = backend.get_messages(None, detect_media=True)
result = {'scale':scale.active_scale(), 'region':r, 'ocr':items, 'bubbles':bubbles,
          'messages':messages}

(root / 'result-after.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
