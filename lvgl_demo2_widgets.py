# lvgl_demo2_widgets.py — Widget 互動(動態計數器版)
# 螢幕上有:
#   - 跳動的 Run 計數器(證明主迴圈在跑)
#   - 按鈕(點擊計數)
#   - 滑桿(拖動改值)
#   - 弧形進度條
#   - 開關按鈕

import lvgl as lv
from lvgl_shared import setup_all, WIDTH, HEIGHT

# ====== 初始化 ======
disp, timer, _ = setup_all()

# ====== 畫面 ======
scr = lv.screen_active()
scr.set_style_bg_color(lv.color_hex(0x303030), 0)

# --- 標題 ---
title = lv.label(scr)
title.set_text("Widget Demo")
title.align(lv.ALIGN.TOP_MID, 0, 8)

# --- 跳動計數器 ---
run_label = lv.label(scr)
run_label.set_text("Run: 0")
run_label.align(lv.ALIGN.TOP_MID, 0, 35)
run_label.set_style_text_color(lv.color_hex(0x00FF00), 0)

# --- 按鈕 + 標籤 ---
btn = lv.button(scr)
btn.set_size(120, 50)
btn.align(lv.ALIGN.CENTER, 0, -40)

btn_label = lv.label(btn)
btn_label.set_text("Click Me")

counter_label = lv.label(scr)
counter_label.set_text("Count: 0")
counter_label.align(lv.ALIGN.CENTER, 0, 20)
_count = [0]

def on_btn_click(e):
    _count[0] += 1
    counter_label.set_text(f"Count: {_count[0]}")

btn.add_event_cb(on_btn_click, lv.EVENT.CLICKED, None)

# --- 滑桿 ---
slider = lv.slider(scr)
slider.set_size(WIDTH - 40, 20)
slider.align(lv.ALIGN.BOTTOM_MID, 0, -60)

slider_label = lv.label(scr)
slider_label.set_text("Value: 0")
slider_label.align(lv.ALIGN.BOTTOM_MID, 0, -30)

def on_slider_change(e):
    slider_label.set_text(f"Value: {slider.get_value()}")

slider.add_event_cb(on_slider_change, lv.EVENT.VALUE_CHANGED, None)

# --- 進度條(Arc) ---
arc = lv.arc(scr)
arc.set_size(120, 120)
arc.align(lv.ALIGN.TOP_MID, -80, 80)
arc.set_range(0, 100)
arc.set_value(30)

arc_label = lv.label(scr)
arc_label.set_text("30%")
arc_label.align(lv.ALIGN.TOP_MID, -80, 80)

def on_arc_change(e):
    arc_label.set_text(f"{arc.get_value()}%")

arc.add_event_cb(on_arc_change, lv.EVENT.VALUE_CHANGED, None)

# --- 開關 ---
sw = lv.switch(scr)
sw.align(lv.ALIGN.TOP_MID, 80, 80)

sw_label = lv.label(scr)
sw_label.set_text("OFF")
sw_label.align(lv.ALIGN.TOP_MID, 80, 60)

def on_switch_change(e):
    sw_label.set_text("ON" if sw.get_state() else "OFF")

sw.add_event_cb(on_switch_change, lv.EVENT.VALUE_CHANGED, None)

print("Demo2 ready — Run counter should be ticking")

# ====== 主迴圈(動態更新) ======
n = 0
while True:
    timer.tick_and_handler(5000)
    n += 1
    run_label.set_text(f"Run: {n}")
