"""ebaz_lcd_test.py drawing logic, against a plain file standing in for /dev/fb0 (no board needed)."""
import importlib.util
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
TOOL = Path(__file__).resolve().parents[1] / "tools" / "ebaz_lcd_test.py"


@pytest.fixture(scope="module")
def lcd():
    spec = importlib.util.spec_from_file_location("ebaz_lcd_test", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_rgb565(lcd):
    assert lcd.rgb565(255, 255, 255) == 0xFFFF
    assert lcd.rgb565(255, 0, 0) == 0xF800
    assert lcd.rgb565(0, 255, 0) == 0x07E0
    assert lcd.rgb565(0, 0, 255) == 0x001F


@pytest.mark.parametrize("w,h", [(240, 240), (135, 240), (240, 320)])
def test_frame_has_border_and_corner_markers(lcd, w, h):
    img = lcd.frame({"w": w, "h": h, "bpp": 16, "stride": w * 2})
    assert img.shape == (h, w)
    white = 0xFFFF
    assert (img[0, :] == white).all() and (img[-1, :] == white).all()
    assert (img[:, 0] == white).all() and (img[:, -1] == white).all()
    assert img[2, 2] == lcd.rgb565(255, 0, 0)
    assert img[2, w - 3] == lcd.rgb565(0, 255, 0)
    assert img[h - 3, 2] == lcd.rgb565(0, 0, 255)
    assert img[h - 3, w - 3] == lcd.rgb565(255, 255, 0)


def test_write_fb_honours_stride(lcd, tmp_path):
    info = {"w": 4, "h": 3, "bpp": 16, "stride": 12}                  # 4 bytes padding per row
    img = np.arange(12, dtype=np.uint16).reshape(3, 4)
    f = tmp_path / "fb"
    lcd.write_fb(str(f), img, info)
    data = f.read_bytes()
    assert len(data) == 36
    assert np.frombuffer(data[12:20], dtype="<u2").tolist() == [4, 5, 6, 7]
    assert data[8:12] == b"\x00\x00\x00\x00"


def test_only_16_bpp(lcd):
    with pytest.raises(SystemExit):
        lcd.frame({"w": 4, "h": 4, "bpp": 32, "stride": 16})
