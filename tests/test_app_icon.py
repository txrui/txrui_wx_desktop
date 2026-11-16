from PIL import Image

from build_exe import build_icon


def test_logo_icon_sizes(tmp_path):
    Image.new("RGBA", (1024, 1024), (12, 34, 56, 255)).save(tmp_path / "logo.png")
    icon_path = build_icon(tmp_path)
    with Image.open(icon_path) as icon:
        assert icon.format == "ICO"
        assert icon.ico.sizes() == {(16, 16), (24, 24), (32, 32), (48, 48),
                                    (64, 64), (128, 128), (256, 256)}
        assert icon.convert("RGBA").getpixel((128, 128)) == (12, 34, 56, 255)


def test_non_square_logo_keeps_aspect_ratio(tmp_path):
    Image.new("RGBA", (512, 256), (12, 34, 56, 255)).save(tmp_path / "logo.png")
    with Image.open(build_icon(tmp_path)) as icon:
        image = icon.convert("RGBA")
        assert image.getpixel((128, 0))[3] == 0
        assert image.getpixel((128, 128)) == (12, 34, 56, 255)
