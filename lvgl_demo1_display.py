# lvgl_demo1_display.py — 最小顯示測試 + 色彩自我診斷
# 螢幕從上到下顯示:紅、綠、藍、白(帶黑色"OK"字樣)
# 如果顏色和標籤不符 → byte swap 問題;完全無畫面 → 硬體

import lvgl as lv
from lvgl_shared import setup_all, WIDTH, HEIGHT

disp, timer, _ = setup_all()

scr = lv.screen_active()
scr.set_style_bg_color(lv.color_hex(0x000000), 0)

H = HEIGHT // 4
# 色條:紅→綠→藍→白,每條 80px 高 + 標籤
colors = [
    (0xFF0000, "RED  (should be red)"),
    (0x00FF00, "GREEN (should be green)"),
    (0x2015FF, "BLUE  (should be blue)"),
    (0xFFFFFF, "WHITE (should be white)"),
]
for i, (rgb, txt) in enumerate(colors):
    r = lv.obj(scr)
    r.set_size(WIDTH, H)
    r.set_pos(0, i * H)
    r.set_style_bg_color(lv.color_hex(rgb), 0)
    # 標籤
    lb = lv.label(r)
    lb.set_text(txt)
    lb.center()
    # 白色條上標籤用黑字
    if i == 3:
        lb.set_style_text_color(lv.color_hex(0x000000), 0)
    else:
        lb.set_style_text_color(lv.color_hex(0xFFFFFF), 0)

print("Demo1 ready — 4 color bars: RED | GREEN | BLUE | WHITE")

while True:
    timer.tick_and_handler(5000)
