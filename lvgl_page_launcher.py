# lvgl_page_launcher.py — page-launcher 功能選擇（橫屏 carousel）
#
# 對應 lvgl-console-ui/pages/launcher.html（320×240 橫屏）：
#   標題 + 橫向 carousel（焦點卡居中 + 兩側露邊）+ 焦點指示點
# 操作：
#   編碼器 A/B → 左右循環焦點
#   C 確認     → on_confirm() 回傳目標頁名（由 lvgl_ui_app 導航）

import lvgl as lv
from lvgl_ui_common import (
    W, ZH, BG, SURFACE, BORDER, TEXT, TEXT3,
    PRIMARY, F_NUM_S, C, mk_label, mk_icon, fade_in,
)

# 卡片定義：(名稱, 描述, accent 色, 目標頁 id, 編號, 圖示名)
# 圖示對齊設計稿 launcher.html 的 app-card 圖示
CARDS = [
    ("儀表盤", "系統運行狀態總覽", 0x4A90D9, "overview", "01", "layout-dashboard"),
    ("數據監控", "傳感器實時數據",   0x2ECC71, "monitor",  "02", "activity"),
    ("設備控制", "繼電器與參數控制", 0xE67E22, "control",  "03", "sliders-horizontal"),
    ("系統設置", "語言·顯示·系統",   0x7F8C8D, "settings", "04", "settings"),
]

CARD_W = 160
CARD_H = 140
CX = (W - CARD_W) // 2   # 80：焦點卡左邊緣（水平居中）
STRIDE = 176              # 相鄰卡左邊緣間距
FOCUS_Y = 48
IDLE_Y = 56

scr = None
cards = []
dots = []
_focus = 0

def build():
    global scr
    scr = lv.obj(None)
    scr.set_style_bg_color(C(BG), 0)

    title = mk_label(scr, "選擇功能", 0, 8, TEXT, ZH)
    title.align(lv.ALIGN.TOP_MID, 0, 8)

    sub = mk_label(scr, "旋鈕 切換 · 按下 確認 · GPIO42 返回", 0, 28, TEXT3, ZH)
    sub.align(lv.ALIGN.TOP_MID, 0, 28)

    # 載入動效:標題/副標題淡入(對齊設計稿 fade-in)
    fade_in(title, dy=4, time_ms=300, delay_ms=0)
    fade_in(sub, dy=4, time_ms=300, delay_ms=80)

    n = len(CARDS)
    for i, (name, desc, accent, _tgt, num, ico) in enumerate(CARDS):
        c = lv.obj(scr)
        c.set_size(CARD_W, CARD_H)
        c.set_style_bg_color(C(SURFACE), 0)
        c.set_style_radius(12, 0)
        c.set_style_border_color(C(BORDER), 0)
        c.set_style_border_width(1, 0)
        c.set_style_pad_all(0, 0)
        c.remove_flag(lv.obj.FLAG.SCROLLABLE)

        # accent 方塊:優先放圖示(對齊設計稿),icon 字體不可用時顯示編號
        blk = lv.obj(c)
        blk.set_size(40, 40)
        blk.set_pos(14, 16)
        blk.set_style_bg_color(C(accent), 0)
        blk.set_style_radius(8, 0)
        blk.set_style_border_width(0, 0)
        blk.set_style_pad_all(0, 0)
        blk.remove_flag(lv.obj.FLAG.SCROLLABLE)
        ic = mk_icon(blk, ico, 0, 0, 0xFFFFFF)
        if ic is not None:
            ic.align(lv.ALIGN.CENTER, 0, 0)
            # 編號移到卡片右上角
            nlb = mk_label(c, num, 0, 0, TEXT3, F_NUM_S)
            nlb.align(lv.ALIGN.TOP_RIGHT, -8, 8)
        else:
            nlb = mk_label(blk, num, 0, 0, 0xFFFFFF, F_NUM_S)
            nlb.align(lv.ALIGN.CENTER, 0, 0)

        mk_label(c, name, 14, 68, TEXT, ZH)
        mk_label(c, desc, 14, 92, TEXT3, ZH)

        cards.append(c)

    # 焦點指示點
    x0 = (W - (n * 8 + (n - 1) * 6)) // 2
    for i in range(n):
        d = lv.obj(scr)
        d.set_size(8, 8)
        d.set_pos(x0 + i * 14, 200)
        d.set_style_radius(4, 0)
        d.set_style_bg_color(C(0xDADCE0), 0)
        d.set_style_border_width(0, 0)
        dots.append(d)

    _layout()
    return scr

def _layout():
    n = len(CARDS)
    for i, c in enumerate(cards):
        rel = ((i - _focus + n + n // 2) % n) - n // 2
        x = CX + rel * STRIDE
        foc = (rel == 0)
        c.set_pos(x, FOCUS_Y if foc else IDLE_Y)
        c.set_style_opa(255 if foc else 160, 0)
        c.set_style_border_color(C(PRIMARY if foc else BORDER), 0)
        c.set_style_border_width(2 if foc else 1, 0)
        if foc:
            c.move_foreground()
        dots[i].set_style_bg_color(C(PRIMARY if foc else 0xDADCE0), 0)

# ====== 頁面接口 ======

def on_enter():
    pass

def on_leave():
    pass

def on_enc(d):
    global _focus
    _focus = (_focus + d) % len(CARDS)
    _layout()

def on_confirm():
    print("[confirm] enter {}".format(CARDS[_focus][0]))
    return CARDS[_focus][3]

def on_exit():
    return False

def update(run):
    pass
