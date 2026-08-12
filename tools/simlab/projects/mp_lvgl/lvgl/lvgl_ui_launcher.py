# lvgl_ui_launcher.py — LVGL 控制台：功能選擇頁（畫面 + 操作）
#
# 對應 lvgl-console-ui 的 page-launcher（功能選擇）。
# 畫面：標題 + 4 張功能卡 + 焦點指示 + Run 計數器
# 操作（Inputs 驅動）：
#   可調編碼器 A/B  → 旋轉切換焦點（上下循環）
#   編碼器 C(=17)   → 確認（進入選中的功能；目前只印 log）
#   外接按鈕 42     → 退出（目前只印 log）
#
# 用法（soft reboot 後）：
#   import lvgl_ui_launcher

import lvgl as lv
from lvgl_shared import FrameBuffer, Inputs, WIDTH, HEIGHT
import time as _t

# 中文字體（LVGL9 內建 simsun_16_cjk；沒有就 fallback 預設字體）
_ZH = getattr(lv, "font_simsun_16_cjk", None)

# ====== 初始化 ======
fb = FrameBuffer()
fb.setup()
inp = Inputs()

# ====== 畫面：功能選擇 launcher ======
scr = lv.screen_active()
scr.set_style_bg_color(lv.color_hex(0x1A1A2E), 0)

# ── 標題 ──
title = lv.label(scr)
title.set_text("选择功能")
title.align(lv.ALIGN.TOP_MID, 0, 12)
title.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
if _ZH:
    title.set_style_text_font(_ZH, 0)

hint = lv.label(scr)
hint.set_text("旋钮选择 · 确认进入")
hint.align(lv.ALIGN.TOP_MID, 0, 38)
hint.set_style_text_color(lv.color_hex(0x8888AA), 0)

# ── 4 張功能卡 ──
CARDS = [
    ("仪表盘",   0x4A90D9),
    ("数据监控", 0x2ECC71),
    ("设备控制", 0xE67E22),
    ("系统设置", 0x7F8C8D),
]
CARD_W = 216
CARD_H = 56
CARD_X = (WIDTH - CARD_W) // 2
CARD_Y0 = 60
CARD_GAP = 8

cards = []
for i, (name, accent) in enumerate(CARDS):
    y = CARD_Y0 + i * (CARD_H + CARD_GAP)

    c = lv.obj(scr)
    c.set_size(CARD_W, CARD_H)
    c.set_pos(CARD_X, y)
    c.set_style_bg_color(lv.color_hex(0x2A2A3E), 0)
    c.set_style_radius(10, 0)
    c.set_style_border_color(lv.color_hex(accent), 0)
    c.set_style_border_width(2, 0)
    c.set_style_border_opa(120, 0)

    bar = lv.obj(c)
    bar.set_size(6, CARD_H)
    bar.set_pos(0, 0)
    bar.set_style_bg_color(lv.color_hex(accent), 0)
    bar.set_style_radius(10, 0)

    lb = lv.label(c)
    lb.set_text(name)
    lb.set_pos(20, CARD_H // 2 - 12)
    lb.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
    if _ZH:
        lb.set_style_text_font(_ZH, 0)

    ar = lv.label(c)
    ar.set_text(">")
    ar.align(lv.ALIGN.RIGHT_MID, -14, 0)
    ar.set_style_text_color(lv.color_hex(0x8888AA), 0)

    cards.append(c)

# ── 焦點指示點 ──
focus_dots = []
for i in range(len(CARDS)):
    d = lv.obj(scr)
    d.set_size(10, 10)
    d.set_pos(WIDTH // 2 - (len(CARDS) * 14) // 2 + i * 14, 312)
    d.set_style_radius(5, 0)
    d.set_style_bg_color(lv.color_hex(0x3A3A52), 0)
    d.set_style_bg_opa(255, 0)
    focus_dots.append(d)

# ── Run 計數器 ──
run_label = lv.label(scr)
run_label.set_text("Run: 0")
run_label.align(lv.ALIGN.BOTTOM_RIGHT, -6, -2)
run_label.set_style_text_color(lv.color_hex(0x555577), 0)

# ── 狀態列（操作回饋） ──
status = lv.label(scr)
status.set_text("")
status.set_pos(12, 296)
status.set_style_text_color(lv.color_hex(0xFFCC00), 0)

print("Launcher ready — encoder: focus / C: confirm / BTN42: exit")

# ====== 主迴圈 ======
_focus = 0
_run = 0

def _set_focus(idx):
    for i, c in enumerate(cards):
        if i == idx:
            c.set_style_border_opa(255, 0)
            c.set_style_bg_color(lv.color_hex(0x3A3A56), 0)
            focus_dots[i].set_style_bg_color(lv.color_hex(0xFF6600), 0)
        else:
            c.set_style_border_opa(120, 0)
            c.set_style_bg_color(lv.color_hex(0x2A2A3E), 0)
            focus_dots[i].set_style_bg_color(lv.color_hex(0x3A3A52), 0)

_set_focus(0)

while True:
    # ── 輸入處理 ──
    d = inp.enc_delta()
    if d != 0:
        _focus = (_focus + d) % len(CARDS)
        _set_focus(_focus)
        status.set_text("focus: {}".format(CARDS[_focus][0]))

    if inp.confirm_pressed():
        status.set_text("确认 → {}".format(CARDS[_focus][0]))
        print("[confirm] enter {}".format(CARDS[_focus][0]))

    if inp.exit_pressed():
        status.set_text("退出")
        print("[exit]")

    # ── 渲染 ──
    _run += 1
    run_label.set_text("Run: {}".format(_run))

    fb.tick()
    for x1, y1, x2, y2, data in fb.take():
        fb.show_rect(x1, y1, x2, y2, data)

    if _run % 200 == 0:
        print("[{}] focus={}".format(_run, _focus))
