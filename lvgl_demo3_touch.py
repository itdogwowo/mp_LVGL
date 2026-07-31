# lvgl_demo3_touch.py — 觸控 + 緩衝分離架構
# 觸控 I2C 在主迴圈讀(避免跟 SPI 衝突),read_cb 只讀緩衝值
# 你控制 show:tick() → take() → show_rect()

import lvgl as lv
from lvgl_shared import FrameBuffer, CST328, Pins, WIDTH, HEIGHT
import time as _t

# ====== 初始化 ======
fb = FrameBuffer()
fb.setup()

touch = CST328(
    sda=Pins.TOUCH_SDA, scl=Pins.TOUCH_SCL,
    rst=Pins.TOUCH_RST, int_pin=Pins.TOUCH_INT
)

# ====== LVGL indev(read_cb 只讀緩衝,不做 I2C) ======
indev = lv.indev_create()
indev.set_type(lv.INDEV_TYPE.POINTER)
indev.set_display(fb._disp)
indev.enable(True)

_touch_x = [120]
_touch_y = [160]
_touch_pressed = [False]

def _read_cb(drv, data):
    """只讀緩衝值,I2C 在主迴圈做。"""
    data.point.x = _touch_x[0]
    data.point.y = _touch_y[0]
    data.state = 1 if _touch_pressed[0] else 0

indev.set_read_cb(_read_cb)

# ====== 畫面 ======
scr = lv.screen_active()
scr.set_style_bg_color(lv.color_hex(0x1A1A2E), 0)

touch_label = lv.label(scr)
touch_label.set_text("( --- , --- )")
touch_label.align(lv.ALIGN.TOP_MID, 0, 5)

# 按鈕(明確座標)
btn = lv.button(scr)
btn.set_size(140, 50)
btn.set_pos(50, 50)
btn_label = lv.label(btn)
btn_label.set_text("Tap Me")
btn_label.center()

_tap_count = [0]
def on_tap(e):
    _tap_count[0] += 1
    btn_label.set_text(f"Tapped: {_tap_count[0]}")
btn.add_event_cb(on_tap, lv.EVENT.PRESSED, None)

# 滑桿(明確座標,大一點好拖)
slider = lv.slider(scr)
slider.set_size(200, 30)
slider.set_range(0, 100)
slider.set_pos(20, 150)

slider_label = lv.label(scr)
slider_label.set_text("Slide: 0%")
slider_label.set_pos(70, 190)

def on_slide(e):
    slider_label.set_text(f"Slide: {slider.get_value()}%")
slider.add_event_cb(on_slide, lv.EVENT.VALUE_CHANGED, None)

# FPS
fps_label = lv.label(scr)
fps_label.set_text("FPS: --")
fps_label.set_pos(90, 290)
fps_label.set_style_text_color(lv.color_hex(0x00FF00), 0)

# 手指圓點(最後建立 = 最上層)
dot = lv.obj(scr)
dot.set_size(30, 30)
dot.set_style_radius(15, 0)
dot.set_style_bg_color(lv.color_hex(0xFF6600), 0)
dot.set_style_bg_opa(255, 0)
dot.set_style_border_color(lv.color_hex(0xFFFFFF), 0)
dot.set_style_border_width(2, 0)
dot.remove_flag(lv.obj.FLAG.CLICKABLE)
dot.set_pos(-30, -30)

print("Demo3 ready — 觸控 + 緩衝分離")

# ====== 主迴圈 ======
_fps_frames = 0
_fps_last = _t.ticks_ms()
_no_touch_count = 0
_RELEASE_DELAY = 5   # 連續 5 次無觸控才報 RELEASED
_sm_x = 120.0
_sm_y = 160.0
_SMOOTH = 0.7
_last_dot_x = -30
_last_dot_y = -30
_last_txt = ""
n = 0

while True:
    # 1. 讀觸控 I2C(主迴圈做,不在 read_cb 裡)
    pos = touch.read()
    if pos:
        _touch_x[0] = pos[0]
        _touch_y[0] = pos[1]
        _touch_pressed[0] = True
        _no_touch_count = 0
    else:
        _no_touch_count += 1
        if _no_touch_count >= _RELEASE_DELAY:
            _touch_pressed[0] = False

    # 2. 更新圓點(EMA 平滑)— 只在位置真的變了才 set_pos
    n += 1
    if _touch_pressed[0]:
        _sm_x += (_touch_x[0] - _sm_x) * _SMOOTH
        _sm_y += (_touch_y[0] - _sm_y) * _SMOOTH
        new_dx = int(_sm_x) - 15
        new_dy = int(_sm_y) - 15
        if new_dx != _last_dot_x or new_dy != _last_dot_y:
            dot.set_pos(new_dx, new_dy)
            _last_dot_x = new_dx
            _last_dot_y = new_dy
        new_txt = f"({_touch_x[0]:3d}, {_touch_y[0]:3d})"
        if new_txt != _last_txt:
            touch_label.set_text(new_txt)
            _last_txt = new_txt
    else:
        if _last_dot_x != -30:
            dot.set_pos(-30, -30)
            _last_dot_x = -30
            _last_dot_y = -30
        if _last_txt != "( --- , --- )":
            touch_label.set_text("( --- , --- )")
            _last_txt = "( --- , --- )"

    # 3. 手動觸發 indev 讀取(每輪都讀,不等 LVGL 的 30ms 節拍)
    indev.read()

    # 4. LVGL tick + 渲染
    fb.tick()

    # 5. ★ 你來 show ★
    for x1, y1, x2, y2, data in fb.take():
        fb.show_rect(x1, y1, x2, y2, data)

    # 5. FPS
    _fps_frames += 1
    now = _t.ticks_ms()
    elapsed = _t.ticks_diff(now, _fps_last)
    if elapsed >= 1000:
        fps_label.set_text(f"FPS: {_fps_frames * 1000 // elapsed}")
        _fps_frames = 0
        _fps_last = now

    if n % 200 == 0:
        if _touch_pressed[0]:
            print(f"[{n:6d}] PRESSED  x={_touch_x[0]:3d} y={_touch_y[0]:3d}")
        else:
            print(f"[{n:6d}] released")
