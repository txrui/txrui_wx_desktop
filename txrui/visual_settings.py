"""统一声明视觉区域、点位、颜色和阈值，并校验手动覆盖配置。

配置定义用于控制页面展示，运行时按键读取覆盖值或默认值；不包含连接令牌。
"""
from __future__ import annotations

import math

SCHEMA = {}


def _add(key, label, kind, default, group, source, minimum=0, maximum=255, hint=""):
    SCHEMA[key] = dict(key=key, label=label, type=kind, default=default,
                       group=group, source=source, min=minimum, max=maximum, hint=hint)


for key, label, source in [
    ("input", "输入框区域", "sender.input_box_rect"),
    ("unread", "未读红点检测区域", "backend.iter_unread_sessions / webbridge.debug_badges"),
    ("voice_pill", "录音发送胶囊检测区域", "voice_send._capsule_green_count"),
    ("recall_menu", "撤回菜单识别区域", "recall.recall_message"),
    ("recall_confirm", "撤回确认识别区域", "recall.recall_message"),
]:
    _add(key, label, "rect", None, "区域", source, hint="未覆盖时自动推算；坐标相对微信整窗。撤回菜单/确认区默认整窗，弹出后可刷新截图标定。")
for key, label, source in [
    ("input_focus", "输入框聚焦点击位置", "sender._focus_input / backend.mark_session_read / voice_send.send_voice"),
    ("send_button", "发送按钮点击位置", "sender._submit"),
    ("selected_sample", "会话高亮取色位置", "backend._is_row_selected"),
]:
    _add(key, label, "point", None, "点击位置", source,
         hint="坐标相对微信整窗；高亮取色位置运行时仅使用 X，Y 随当前会话行变化。发送按钮仅在点击发送模式使用。")
for key, label, default, group, source in [
    ("badge_color", "未读红点颜色", [250,81,81], "颜色", "badge.detect_red_clusters"),
    ("selected_color", "选中会话背景色", [221,221,221], "颜色", "backend._is_row_selected"),
    ("self_color", "自己消息气泡背景色", [158,237,151], "颜色", "message_layout.text_is_self"),
    ("panel_color", "消息面板背景色", [250,250,250], "颜色", "media.detect_media_bubbles"),
    ("voice_color", "录音发送胶囊颜色", [7,193,96], "颜色", "voice_send._capsule_green_count"),
]:
    _add(key, label, "color", default, group, source)
for key, label, default, source in [
    ("window_auto_resize", "连接时自动调整微信窗口大小", True, "backend.connect"),
    ("selected_color_manual", "使用指定会话选中色（关闭则自动学习）", False, "backend._is_row_selected"),
    ("self_color_manual", "使用指定自己气泡色（关闭则使用绿色通道判据）", False, "message_layout.text_is_self"),
    ("panel_color_manual", "使用指定面板背景色（关闭则自动取众数）", False, "media.detect_media_bubbles"),
    ("voice_color_manual", "使用指定录音胶囊色（关闭则使用绿色通道判据）", False, "voice_send._capsule_green_count"),
]:
    _add(key, label, "bool", default, "窗口" if key.startswith("window_") else "颜色", source)
_add("send_mode", "发送触发方式", "select", "enter", "发送", "sender._submit", hint="enter=回车；ctrl_enter=Ctrl+Enter；click=点击已标定的发送按钮。保存/取色/预览不会发送消息。")
SCHEMA["send_mode"]["choices"] = {"enter":"回车", "ctrl_enter":"Ctrl+Enter", "click":"点击发送按钮"}

# 数值参数：(键、标签、默认值、最小值、最大值、分组、真实调用点、单位提示)
for row in [
    ("window_width","连接时窗口目标宽度",1500,400,8000,"窗口","backend.connect","物理像素；下次连接生效"),
    ("window_height","连接时窗口目标高度",1000,300,8000,"窗口","backend.connect","物理像素；下次连接生效"),
    ("row_merge_y","消息同行合并距离",18,1,500,"消息归属","backend.get_messages","消息裁剪图像素"),
    ("media_attach_y","旧媒体纵向关联距离（已停用）",60,1,1000,"媒体检测","兼容旧配置","现按文字框与媒体框实际重叠关联"),
    ("selected_sample_x","自动高亮取色向右偏移",5,0,1000,"未读与会话","backend._is_row_selected","相对会话区左界，物理像素；显式取色点优先"),
    ("edge_gray_min","水平边界灰度下限",170,0,255,"自动边界","regions.detect_header_y / detect_input_top_y","灰度"),
    ("edge_std_max","水平边界标准差上限",15,0.1,255,"自动边界","regions.detect_header_y / detect_input_top_y","灰度标准差"),
    ("title_min_top","标题裁剪最小顶边",36,0,500,"自动边界","regions.regions_for_window","基准档像素"),
    ("title_left_pad","标题左侧留白",12,0,500,"自动边界","regions.regions_for_window","基准档像素"),
    ("title_bottom_gap","标题下边框间距",2,0,100,"自动边界","regions.regions_for_window","物理像素"),
    ("message_top_gap","消息区上边框间距",4,0,100,"自动边界","regions.regions_for_window","物理像素"),
    ("message_bottom_gap","消息区下边框间距",2,0,100,"自动边界","regions.regions_for_window","物理像素"),
    ("menu_click_x","撤回菜单项点击 X 比例",0.5,0,1,"动态点击","recall.recall_message","相对 OCR 菜单项宽度"),
    ("menu_click_y","撤回菜单项点击 Y 比例",0.5,0,1,"动态点击","recall.recall_message","相对 OCR 菜单项高度"),
    ("confirm_click_x","撤回确认按钮点击 X 比例",0.5,0,1,"动态点击","recall.recall_message","相对 OCR 确认按钮宽度"),
    ("confirm_click_y","撤回确认按钮点击 Y 比例",0.5,0,1,"动态点击","recall.recall_message","相对 OCR 确认按钮高度"),
    ("badge_tol","未读红点颜色容差",5,0,255,"未读与会话","badge.detect_red_clusters","RGB 各通道容差"),
    ("badge_area_min","红点最小面积",60,1,100000,"未读与会话","badge.detect_red_clusters","基准档像素面积，随 DPI 平方换算"),
    ("badge_area_max","红点最大面积",1000,1,100000,"未读与会话","badge.detect_red_clusters","基准档像素面积，随 DPI 平方换算"),
    ("badge_click_x","红点中心点击 X 偏移",45,-1000,1000,"未读与会话","backend._click_row","基准档像素，随 DPI 换算"),
    ("badge_click_y","红点中心点击 Y 偏移",0,-1000,1000,"未读与会话","backend._click_row","基准档像素，随 DPI 换算"),
    ("badge_row_tol","未读同一行去重距离",40,1,1000,"未读与会话","backend.iter_unread_sessions","基准档像素"),
    ("selected_tol","会话选中色容差",12,0,255,"未读与会话","backend._is_row_selected","RGB 各通道容差"),
    ("chat_click_x","会话 OCR 结果点击 X 偏移",0,-1000,1000,"未读与会话","backend.ensure_chat","相对动态文字框中心，基准档像素"),
    ("chat_click_y","会话 OCR 结果点击 Y 偏移",0,-1000,1000,"未读与会话","backend.ensure_chat","相对动态文字框中心，基准档像素"),
    ("self_tol","自己气泡指定色容差",20,0,255,"消息归属","message_layout.text_is_self","RGB 各通道容差"),
    ("self_g_min","自己气泡绿色通道下限",120,0,255,"消息归属","message_layout.text_is_self","绿色 G"),
    ("self_gr","自己气泡 G-R 下限",15,0,255,"消息归属","message_layout.text_is_self","颜色通道差"),
    ("self_gb","自己气泡 G-B 下限",8,0,255,"消息归属","message_layout.text_is_self","颜色通道差"),
    ("self_fill","自己气泡色占比下限",0.35,0,1,"消息归属","message_layout.text_is_self","0~1"),
    ("self_split","自己消息左右分界",0.5,0,1,"消息归属","message_layout.text_is_self","消息裁剪图宽度比例"),
    ("media_bg_diff","媒体前景背景灰度差",18,0,255,"媒体检测","media.detect_media_bubbles","灰度差"),
    ("media_fill","媒体前景占比下限",0.12,0,1,"媒体检测","media.detect_media_bubbles","0~1"),
    ("media_min_h","媒体最小高度",66,1,2000,"媒体检测","media.detect_media_bubbles","基准档像素"),
    ("media_min_w","媒体最小宽度",60,1,2000,"媒体检测","media.detect_media_bubbles","基准档像素"),
    ("file_max_h","文件气泡最大高度",200,1,2000,"媒体检测","media.detect_media_bubbles","基准档像素"),
    ("emoji_max_h","小表情最大高度",46,1,2000,"媒体检测","media.detect_media_bubbles","基准档像素"),
    ("emoji_max_w","小表情最大宽度",90,1,2000,"媒体检测","media.detect_media_bubbles","基准档像素"),
    ("emoji_min_h","小表情最小高度",18,1,2000,"媒体检测","media.detect_media_bubbles","基准档像素"),
    ("emoji_min_w","小表情最小宽度",14,1,2000,"媒体检测","media.detect_media_bubbles","基准档像素"),
    ("audio_max_h","语音条最大高度",34,1,2000,"媒体检测","media.detect_media_bubbles","基准档像素"),
    ("audio_aspect","语音条最小宽高比",2.6,0.1,20,"媒体检测","media.classify_box","宽 / 高"),
    ("video_aspect","旧视频宽高比判据（已停用）",1.35,0.1,20,"媒体检测","兼容旧配置","现须有视频时长证据，宽图按图片处理"),
    ("ocr_overlap_pad","媒体 OCR 文本框扩边",6,0,100,"媒体检测","media._text_boxes_overlap","裁剪图像素"),
    ("bubble_crop_pad","媒体气泡截图扩边",2,0,100,"媒体检测","media.crop_bubble","裁剪图像素"),
    ("media_click_x","打开媒体点击 X 比例",0.5,0,1,"动态点击","media_grab.grab_original_image","相对当前识别气泡宽度"),
    ("media_click_y","打开媒体点击 Y 比例",0.5,0,1,"动态点击","media_grab.grab_original_image","相对当前识别气泡高度"),
    ("recall_click_x","撤回消息点击 X 比例",0.5,0,1,"动态点击","recall.recall_message","相对动态消息文字框宽度"),
    ("recall_click_y","撤回消息点击 Y 比例",0.5,0,1,"动态点击","recall.recall_message","相对动态消息文字框高度"),
    ("voice_g_min","录音胶囊 G 下限",120,0,255,"录音检测","voice_send._capsule_green_count","绿色通道"),
    ("voice_gr","录音胶囊 G-R 下限",40,0,255,"录音检测","voice_send._capsule_green_count","颜色通道差"),
    ("voice_gb","录音胶囊 G-B 下限",20,0,255,"录音检测","voice_send._capsule_green_count","颜色通道差"),
    ("voice_tol","录音胶囊指定色容差",20,0,255,"录音检测","voice_send._capsule_green_count","RGB 各通道容差"),
    ("voice_area_min","录音胶囊绿色最小面积",150,1,100000,"录音检测","voice_send._send_pill_visible","基准档像素面积"),
    ("divider_left","竖分隔线搜索左界",0.15,0,1,"自动边界","regions.detect_divider_x","整窗宽度比例"),
    ("divider_right","竖分隔线搜索右界",0.55,0,1,"自动边界","regions.detect_divider_x","整窗宽度比例"),
    ("header_top","标题边界搜索上界",0.03,0,1,"自动边界","regions.detect_header_y","整窗高度比例"),
    ("header_bottom","标题边界搜索下界",0.14,0,1,"自动边界","regions.detect_header_y","整窗高度比例"),
    ("header_min","排除系统顶栏高度",64,1,1000,"自动边界","regions.detect_header_y","基准档像素"),
    ("header_max","标题边界搜索最小下界",220,1,2000,"自动边界","regions.detect_header_y","基准档像素"),
    ("header_text_h","标题文字保留高度",50,1,1000,"自动边界","regions.regions_for_window","基准档像素"),
    ("edge_contrast","区域分隔线最小色差",3,1,100,"自动边界","regions.detect_*","灰度或 RGB 均值差"),
    ("edge_coverage","区域分隔线覆盖率",0.75,0.1,1,"自动边界","regions.detect_*","0~1"),
    ("input_scan_top","输入框边界搜索上界",0.4,0,1,"自动边界","regions.detect_input_top_y","整窗高度比例"),
    ("input_scan_bottom","输入框边界搜索下界",0.9,0,1,"自动边界","regions.detect_input_top_y","整窗高度比例"),
]:
    key,label,default,lo,hi,group,source,hint=row
    _add(key,label,"number",default,group,source,lo,hi,hint)


def overrides():
    from .region_settings import get_visual
    return get_visual()


def value(key):
    return overrides().get(key, SCHEMA[key]["default"])


def validate(values):
    if not isinstance(values, dict) or set(values) - set(SCHEMA):
        raise ValueError("视觉配置包含未知字段或格式错误")
    out = {}
    for key, val in values.items():
        spec = SCHEMA[key]
        kind = spec["type"]
        def finite(x):
            return not isinstance(x, bool) and isinstance(x, (int,float)) and math.isfinite(x)
        if kind == "bool":
            good = isinstance(val, bool)
        elif kind == "select":
            good = isinstance(val, str) and val in spec["choices"]
        elif kind == "number":
            good = finite(val) and spec["min"] <= val <= spec["max"]
        elif kind == "color":
            good = isinstance(val, (list,tuple)) and len(val)==3 and all(finite(x) and int(x)==x and 0<=x<=255 for x in val)
        elif kind in ("point","rect"):
            good = isinstance(val, (list,tuple)) and len(val)==(2 if kind=="point" else 4) and all(finite(x) and 0<=x<=1 for x in val)
            if good and kind=="rect":
                good = val[0]<val[2] and val[1]<val[3]
        else:
            good = False
        if not good:
            raise ValueError(f"{spec['label']}：值或范围不合法")
        out[key] = list(val) if isinstance(val,(tuple,list)) else val
    merged = {k:s["default"] for k,s in SCHEMA.items()}
    merged.update(out)
    for low,high in [("badge_area_min","badge_area_max"),("emoji_min_h","emoji_max_h"),
                     ("emoji_min_w","emoji_max_w"),("divider_left","divider_right"),
                     ("header_top","header_bottom"),("input_scan_top","input_scan_bottom")]:
        if merged[low] >= merged[high]:
            raise ValueError(f"{SCHEMA[low]['label']}必须小于{SCHEMA[high]['label']}")
    return out


def effective(w, h, primary, use_overrides=True):
    """供编辑器展示的有效区域、点位和参数，不写入配置或触发界面操作。"""
    from .scale import k
    kk = k()
    cx, cy = .7, 1 - 149*kk/h
    bw, bh = max(120*kk,w*.45)/w,40*kk/h
    defaults = {"input":[max(0,cx-bw/2),max(0,cy-bh/2),min(1,cx+bw/2),min(1,cy+bh/2)],
                "unread":list(primary[0]), "voice_pill":[.5,.86,.95,.99],
                "recall_menu":[0,0,1,1], "recall_confirm":[0,0,1,1],
                "input_focus":[cx, max(0,min(1,cy))],
                "send_button":[.95,max(0,min(1,1-32*kk/h))],
                "selected_sample":[min(1,primary[0][0]+5/w),.5]}
    settings = overrides() if use_overrides else {}
    if "input" in settings and "input_focus" not in settings:
        box=settings["input"]
        defaults["input_focus"]=[(box[0]+box[2])/2,(box[1]+box[3])/2]
    return {key:settings.get(key,defaults.get(key,spec["default"])) for key,spec in SCHEMA.items()}


def rect(key, w, h, fallback):
    box = overrides().get(key, fallback)
    return tuple(int(v*d) for v,d in zip(box,(w,h,w,h)))


def color_mask(pixels, color_key, tol_key):
    import numpy as np
    return (np.abs(pixels - np.asarray(value(color_key), dtype=np.int16)) <= value(tol_key)).all(axis=-1)
