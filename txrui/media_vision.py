"""提取八连通区域、残余图像纹理和小表情色彩特征，不加载识别模型。"""
from __future__ import annotations


def component_boxes(mask):
    """按相邻行连续段构建八连通区域，返回各区域的左上闭、右下开边界。"""
    import numpy as np

    parents, bounds = [], []

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    previous = []
    for y, row in enumerate(mask):
        changes = np.diff(np.pad(row.astype(np.int8), (1, 1)))
        starts, ends = np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
        current = []
        p = 0
        for left, right in zip(starts.tolist(), ends.tolist()):
            while p < len(previous) and previous[p][1] < left:
                p += 1
            q, hits = p, []
            while q < len(previous) and previous[q][0] <= right:
                hits.append(root(previous[q][2]))
                q += 1
            if hits:
                index = min(hits)
                for hit in hits:
                    if hit != index:
                        parents[hit] = index
                        b = bounds[hit]
                        a = bounds[index]
                        bounds[index] = [min(a[0], b[0]), min(a[1], b[1]),
                                         max(a[2], b[2]), max(a[3], b[3])]
                a = bounds[index]
                bounds[index] = [min(a[0], left), a[1], max(a[2], right), y + 1]
            else:
                index = len(parents)
                parents.append(index)
                bounds.append([left, y, right, y + 1])
            current.append((left, right, index))
        previous = current
    return [tuple(bounds[i]) for i in range(len(parents)) if root(i) == i]


def visual_features(rgb, foreground, text_mask):
    """统计文字框外前景的颜色和灰阶层次，返回残余占比与纹理判断。"""
    import numpy as np

    residual = foreground & ~text_mask
    pixels = rgb[residual]
    if len(pixels) == 0:
        return dict(residual=0.0, colorful=0.0, colors=0, texture=False)
    # 颜色量化抑制抗锯齿、JPEG 噪点，少量阴影不算丰富画面。
    sample = pixels[::max(1, len(pixels) // 20000)].astype(np.int16)
    quant = sample // 32
    codes = quant[:, 0] * 64 + quant[:, 1] * 8 + quant[:, 2]
    _, counts = np.unique(codes, return_counts=True)
    colors = int((counts >= max(3, len(sample) * 0.003)).sum())
    chroma = sample.max(axis=1) - sample.min(axis=1)
    colorful = float((chroma > 55).mean())
    gray = sample.mean(axis=1)
    levels = len(np.unique((gray // 32).astype(int)))
    # 灰阶截图也能作为图片，均匀底色+单色字形不能。
    texture = colors >= 10 or (levels >= 5 and float(gray.std()) >= 28)
    return dict(residual=float(residual.mean()), colorful=colorful,
                colors=colors, texture=bool(texture))


def emoji_evidence(rgb, foreground, text_mask):
    """按彩色像素数量、形状和颜色层次判断表情候选，排除浅绿色气泡底色。"""
    import numpy as np

    pixels = rgb.astype(np.int16)
    chroma = pixels.max(axis=2) - pixels.min(axis=2)
    colorful = (chroma > 65) & (pixels.max(axis=2) > 130) & foreground & ~text_mask
    # 默认微信发出气泡是浅绿，不应因背景色被判成表情。
    bubble_green = ((pixels[:, :, 1] > 175) & (pixels[:, :, 0] > 100)
                    & (pixels[:, :, 2] > 90) & (pixels[:, :, 1] > pixels[:, :, 0])
                    & (pixels[:, :, 1] > pixels[:, :, 2]))
    colorful &= ~bubble_green
    ys, xs = np.nonzero(colorful)
    if len(xs) < max(12, foreground.size * 0.025):
        return False
    width, height = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
    aspect = width / max(1, height)
    if not 0.45 <= aspect <= 2.2:
        return False
    # 色块须具有真实轮廓/内部层次，而不是单色填充。
    crop = colorful[ys.min():ys.max()+1, xs.min():xs.max()+1]
    # 白色眼睛、深色嘴部也属于表情细节，不能只统计高饱和像素。
    values = pixels[ys.min():ys.max()+1, xs.min():xs.max()+1].reshape(-1, 3) // 32
    colors = len(np.unique(values, axis=0))
    return bool(colors >= 3 and 0.15 <= float(crop.mean()) <= 0.94)
