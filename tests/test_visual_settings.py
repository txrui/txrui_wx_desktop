"""验证视觉配置的保存、校验及调用效果；窗口和发送操作使用模拟接口。"""
import base64
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import numpy as np
import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from txrui import region_settings as store, visual_settings as visual
from txrui import sender, badge, message_layout, media

BOXES = {"session":[.05,.12,.3,.95],"message":[.31,.15,.99,.8],"title":[.32,.04,.85,.12]}


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(store,"_PATH",tmp_path/"regions.json")
    monkeypatch.setattr(store,"_CACHE",None)
    monkeypatch.setattr(store,"_VISUAL",{})


def configure(**values):
    store.save_profile({}, values)


def test_profile_reload_and_legacy_preservation():
    store.save_profile(BOXES,{"input_focus":[.6,.8],"badge_color":[1,2,3]})
    store._CACHE=None
    assert visual.value("badge_color")==[1,2,3]
    assert store.get_regions()==store.validate(BOXES)
    store.save_regions(BOXES)
    assert visual.value("input_focus")==[.6,.8]
    store.reset_regions()
    assert visual.value("badge_color")==[250,81,81]


@pytest.mark.parametrize("values",[
    {"unknown":1},{"send_mode":"invalid"},{"self_fill":2},
    {"input_focus":[float("nan"),.5]}, {"input":[.4,.4,.2,.8]},
    {"badge_color":[0,256,0]},{"badge_color":[1.5,2,3]},
    {"selected_color_manual":1},{"badge_area_min":2000,"badge_area_max":1000},
    {"divider_left":.6,"divider_right":.4},
])
def test_profile_validation(values):
    with pytest.raises(ValueError): configure(**values)
    assert not store.get_visual()


def test_configured_badge_color_reaches_detector():
    image=Image.new("RGB",(100,100),"white")
    ImageDraw.Draw(image).rectangle((30,30,45,45),fill=(20,80,180))
    assert not badge.detect_red_clusters(image,(0,0,1,1))
    configure(badge_color=[20,80,180],badge_tol=0,badge_area_min=1,badge_area_max=100000)
    assert badge.detect_red_clusters(image,(0,0,1,1))==[(30,30,45,45)]


def test_configured_self_color_reaches_message_classification():
    image=Image.new("RGB",(200,100),(30,50,210))
    item=dict(x=10,y=10,w=30,h=20)
    assert not message_layout.text_is_self(image,item)
    configure(self_color_manual=True,self_color=[30,50,210],self_tol=0)
    assert message_layout.text_is_self(image,item)


def test_media_background_and_classification_reach_runtime():
    image=Image.new("RGB",(300,300),(80,80,80))
    configure(panel_color_manual=True,panel_color=[80,80,80])
    assert not media.detect_media_bubbles(image,[],175)
    configure(panel_color_manual=True,panel_color=[255,255,255],video_aspect=3)
    assert media.detect_media_bubbles(image,[],175)[0]["kind"]=="image"
    assert media.classify_box(200,100,"",200)=="image"
    # 调整宽高比参数后，无时长文本的矩形仍判为图片。
    configure(video_aspect=1.1)
    assert media.classify_box(200,100,"",200)=="image"
    assert media.classify_box(200,100,"00:15",200)=="video"


@pytest.mark.skipif(sys.platform!="win32", reason="Windows 坐标接口")
def test_input_and_submission_points_support_negative_monitor():
    configure(input=[.4,.75,.95,.95],input_focus=[.61,.82],send_button=[.94,.96],send_mode="click")
    gui=Mock()
    with patch("txrui.capture.window_rect",return_value=(-1600,20,1500,1000)), \
         patch.dict(sys.modules,{"pyautogui":gui}):
        assert sender.input_box_rect(123)==(-1000,770,825,200)
        assert sender.input_focus_point(123)==(-685,840)
        sender._submit(123)
        gui.click.assert_called_once_with(-190,980)
        gui.press.assert_not_called()
    configure(send_mode="ctrl_enter")
    with patch.dict(sys.modules,{"pyautogui":gui}):
        sender._submit(123)
        gui.hotkey.assert_called_once_with("ctrl","enter")
    configure(send_mode="click")
    with patch.dict(sys.modules,{"pyautogui":gui}),pytest.raises(ValueError):
        sender._submit(123)


def test_text_and_image_are_submitted_once():
    configure(send_mode="enter")
    gui = Mock()
    clipboard_events = []
    pyperclip = SimpleNamespace(copy=lambda text: clipboard_events.append(("text", text)))
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(image, format="PNG")
    with patch.object(sender, "_focus_input", return_value=True), \
         patch.object(sender, "_submit", side_effect=lambda hwnd: clipboard_events.append(("submit",))), \
         patch("txrui.media_grab.copy_image_to_clipboard", side_effect=lambda value: clipboard_events.append(("image",)) or True), \
         patch.dict(sys.modules, {"pyautogui": gui, "pyperclip": pyperclip}):
        assert sender.send_text_and_image(123, "转发：群 用户 ", image.getvalue())
    assert clipboard_events == [("text", "转发：群 用户 "), ("image",), ("submit",)]
    assert gui.hotkey.call_args_list == [call("ctrl", "v"), call("ctrl", "v")]


@pytest.mark.skipif(sys.platform!="win32", reason="Windows 语音接口")
def test_voice_region_color_and_signed_channels():
    from txrui.voice_send import _capsule_green_count
    arr=np.zeros((100,100,3),dtype=np.uint8)
    arr[10:20,10:20]=[20,60,210]
    configure(voice_pill=[.1,.1,.2,.2],voice_color_manual=True,voice_color=[20,60,210],voice_tol=0)
    assert _capsule_green_count(arr)==100
    configure(voice_pill=[.5,.5,.6,.6])
    assert _capsule_green_count(arr)==0


@pytest.mark.skipif(sys.platform!="win32", reason="Windows 截图接口")
def test_bridge_full_profile_and_lossless_picker():
    from txrui.webbridge import TxruiBridge
    bridge=TxruiBridge(SimpleNamespace(backend=SimpleNamespace(_hwnd=123,_apply_regions=Mock())))
    shot=Image.new("RGB",(1500,1000),(20,80,180))
    with patch("txrui.capture.capture_window",return_value=shot):
        result=bridge.debug_regions("save",BOXES,[1500,1000],{"input_focus":[.6,.8],"badge_color":[20,80,180]},False)
        assert result["ok"] and not result["manual"]
        assert not store.get_regions()
        assert len(result["schema"])==len(visual.SCHEMA)
        assert result["display"]==[1500,1000]
        image=Image.open(io.BytesIO(base64.b64decode(result["image"].split(",")[1])))
        assert image.getpixel((50,50))==(20,80,180)
        bad=bridge.debug_regions("save",BOXES,[1500,1000],{"send_mode":"click"})
        assert not bad["ok"]
        assert visual.value("badge_color")==[20,80,180]
        assert bridge.debug_regions("reset")["ok"]
        assert not store.get_visual()


@pytest.mark.skipif(sys.platform!="win32", reason="Windows 窗口接口")
@pytest.mark.parametrize("enabled",[True,False])
def test_configured_startup_window_size(enabled):
    from txrui.backend import TxruiBackend
    configure(window_auto_resize=enabled,window_width=1600,window_height=900)
    with patch("txrui.backend._cap.find_wechat_window",return_value=123), \
         patch("txrui.backend._cap.ensure_visible"), \
         patch("txrui.backend._cap.resize_wechat_window",return_value=True) as resize, \
         patch("txrui.backend._cap._with_per_monitor_dpi",return_value=(0,0,1600,900)), \
         patch("txrui.backend._cap.monitor_dpi_scale",return_value=0), \
         patch("txrui.backend._cap.capture_window",return_value=Image.new("RGB",(100,100))), \
         patch.object(TxruiBackend,"_apply_regions"):
        assert TxruiBackend().connect()
        if enabled:
            resize.assert_called_once_with(123,1600,900)
        else:
            resize.assert_not_called()


@pytest.mark.skipif(sys.platform!="win32", reason="Windows 截图接口")
def test_recall_scope_restores_window_coordinates():
    from txrui.recall import _ocr_scope
    configure(recall_menu=[.3,.2,.6,.7])
    with patch("txrui.ocr.ocr_image",return_value=[dict(x=5,y=8,w=40,h=20,text="撤回")]) as ocr:
        items=_ocr_scope(Image.new("RGB",(1000,800)),"recall_menu")
        assert ocr.call_args.args[0].size==(300,400)
        assert (items[0]["x"],items[0]["y"])==(305,168)
