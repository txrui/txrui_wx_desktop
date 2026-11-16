"""延迟加载 RapidOCR 移动版模型，识别文本框并清理汉字间多余空格。

引擎初始化失败后缓存不可用状态；识别失败返回空列表。
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)
_ENGINE = None


def get_engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE or None
    try:
        from rapidocr import RapidOCR
        from rapidocr.utils.typings import ModelType, OCRVersion
        _ENGINE = RapidOCR(params={
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.model_type": ModelType.MOBILE,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
            "Det.limit_side_len": 224,
            "Det.limit_type": "min",
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        })
        return _ENGINE
    except Exception as e:
        logger.warning(f"RapidOCR 不可用: {e}")
        _ENGINE = False
        return None


def norm_cjk(text: str) -> str:
    if not text:
        return text
    out = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    out = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[，。！？：；、（）「」『』])", "", out)
    out = re.sub(r"(?<=[，。！？：；、（）「」『』])\s+(?=[\u4e00-\u9fff])", "", out)
    return out.strip()


def ocr_image(img, max_w: int = 0) -> list[dict]:
    """返回文本和矩形框；启用 max_w 时坐标对应缩放后的输入图，不还原原尺寸。"""
    engine = get_engine()
    if not engine:
        return []
    if max_w > 0 and img.width > max_w:
        ratio = max_w / img.width
        from PIL import Image
        img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
    import numpy as np
    try:
        rgb = img.convert("RGB")
    except Exception as e:
        logger.warning(f"OCR 图像转换失败: {e}")
        return []
    # 记录灰度和裁剪尺寸，辅助排查黑图或区域配置异常。
    try:
        _a = np.asarray(rgb.convert("L"))
        _mean, _mx = float(_a.mean()), int(_a.max())
        if _mx < 10:
            logger.warning(f"OCR 输入疑似黑图 {rgb.size[0]}x{rgb.size[1]} mean={_mean:.1f} max={_mx}（微信被完全遮挡/最小化时 PrintWindow 返回黑图）")
        elif rgb.size[0] < 30 or rgb.size[1] < 30:
            logger.warning(f"OCR 输入裁剪过小 {rgb.size[0]}x{rgb.size[1]}（三区域错位？看截图识别页预览）")
        else:
            logger.debug(f"OCR 输入 {rgb.size[0]}x{rgb.size[1]} mean={_mean:.1f} max={_mx}")
    except Exception:
        pass
    try:
        out = engine(np.array(rgb))
        txts = out.txts if out.txts is not None else []
        scores = out.scores if out.scores is not None else []
        boxes = out.boxes if out.boxes is not None else []
        items = []
        for box, text, _s in zip(boxes, txts, scores):
            text = norm_cjk(str(text).strip())
            if not text:
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x, y, x2, y2 = min(xs), min(ys), max(xs), max(ys)
            items.append({"text": text, "x": int(x), "y": int(y),
                          "w": int(x2 - x), "h": int(y2 - y)})
        return items
    except Exception as e:
        logger.warning(f"OCR 失败: {e}")
        return []
