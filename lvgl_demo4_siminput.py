# lvgl_demo4_siminput.py — 模擬觸控輸入(不依賴 CST328)
# 用途:驗證 LVGL indev 機制本身能不能驅動滑桿/按鈕
# 自動把「虛擬手指」從左到右掃過滑桿,看滑桿有沒有反應
#
# 如果這個 demo 滑桿會動 → LVGL indev 沒問題,問題在 CST328 I2C 跟 SPI 衝突
# 如果這個 demo 滑桿也不動 → LVGL indev 設定有問題

import lvgl as lv
from lvgl_shared import FrameBuffer, WIDTH, HEIGHT

# ====== 初始化 ======
fb = FrameBuffer()
fb.setup()

# ====== LVGL indev(模擬輸入,完全不碰 I2C) ======
indev = lv.indev_create()
indev.set_type(lv.INDEV_TYPE.POINTER)
indev.set_display(fb._disp)
indev.enable(True)

# 模擬手指狀態
_sim_x = [40]
_sim_y = [200]
_sim_pressed = [False]

def _read_cb(drv, data):
    data.point.x = _sim_x[0]
    data.point.y = _sim_y[0]
    data.state = 1 if _sim_pressed[0] else 0

indev.set_read_cb(_read_cb)

# ====== 畫面 ======
scr = lv.screen_active()
scr.set_style_bg_color(lv.color_hex(0x1A1A2E), 0)

title = lv.label(scr)
title.set_text("SIM INPUT TEST")
title.align(lv.ALIGN.TOP_MID, 0, 5)

status = lv.label(scr)
status.set_text("watching slider...")
status.align(lv.ALIGN.TOP_MID, 0, 30)

# 滑桿(放在 y=200,虛擬手指會掃過這裡)
slider = lv.slider(scr)
slider.set_size(200, 30)
slider.set_range(0, 100)
slider.align(lv.ALIGN.CENTER, 0, 0)

slider_label = lv.label(scr)
slider_label.set_text("Slide: 0%")
slider_label.align(lv.ALIGN.CENTER, 0, 45)

def on_slide(e):
    slider_label.set_text(f"Slide: {slider.get_value()}%")
slider.add_event_cb(on_slide, lv.EVENT.VALUE_CHANGED, None)

# 虛擬手指圓點
dot = lv.obj(scr)
dot.set_size(30, 30)
dot.set_style_radius(15, 0)
dot.set_style_bg_color(lv.color_hex(0xFF6600), 0)
dot.set_style_bg_opa(255, 0)
dot.remove_flag(lv.obj.FLAG.CLICKABLE)
dot.set_pos(_sim_x[0] - 15, _sim_y[0] - 15)

print("Demo4 ready — 虛擬手指會自動掃過滑桿")

# ====== 動畫腳本:虛擬手指按下,從 x=40 掃到 x=200,再放開 ======
n = 0
phase = 0   # 0=等待 1=按下掃過去 2=放開
scan_x = 40

while True:
    n += 1

    # 簡單的狀態機:模擬「按下 → 拖動 → 放開」
    if phase == 0:
        # 等待 50 輪後按下
        if n > 50:
            _sim_pressed[0] = True
            _sim_x[0] = 40
            _sim_y[0] = 200   # 滑桿的 y 位置
            scan_x = 40
            phase = 1
            status.set_text("PRESSED, dragging...")
    elif phase == 1:
        # 每輪往右掃 2px
        scan_x += 2
        _sim_x[0] = scan_x
        _sim_y[0] = 200
        if scan_x >= 200:
            phase = 2
            status.set_text("releasing...")
    elif phase == 2:
        # 放開
        _sim_pressed[0] = False
        status.set_text(f"DONE! slider={slider.get_value()}%")
        phase = 3
    # phase 3: 結束,維持現狀

    # 更新圓點
    dot.set_pos(_sim_x[0] - 15, _sim_y[0] - 15)

    # LVGL 渲染
    fb.tick()

    # show
    for x1, y1, x2, y2, data in fb.take():
        fb.show_rect(x1, y1, x2, y2, data)

    if n % 100 == 0:
        print(f"[{n:5d}] phase={phase} x={_sim_x[0]:3d} pressed={_sim_pressed[0]} slider={slider.get_value()}")
