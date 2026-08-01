# ui/launcher.py — 動態主頁面（讀 registry 產生卡片,不硬編碼）
import lvgl as lv
from ui import ui_common as u
from ui.registry import ordered

scr = None
cards = []
_focus = 0

CARD_W = 160
CARD_H = 140
CX = (u.W - CARD_W) // 2
STRIDE = 176
FOCUS_Y = 48
IDLE_Y = 56


def build():
    global scr, cards
    scr = lv.obj(None)
    scr.set_style_bg_color(u.C(u.BG), 0)

    title = u.mk_label(scr, "選擇功能", 0, 8, u.TEXT, u.ZH)
    title.align(lv.ALIGN.TOP_MID, 0, 8)
    sub = u.mk_label(scr, "旋鈕 切換 · 按下 確認 · GPIO42 返回", 0, 28, u.TEXT3, u.ZH)
    sub.align(lv.ALIGN.TOP_MID, 0, 28)

    metas = ordered()
    cards = []
    for i, meta in enumerate(metas):
        c = lv.obj(scr)
        c.set_size(CARD_W, CARD_H)
        c.set_style_bg_color(u.C(u.SURFACE), 0)
        c.set_style_radius(12, 0)
        c.set_style_border_color(u.C(u.BORDER), 0)
        c.set_style_border_width(1, 0)
        c.set_style_pad_all(0, 0)
        c.remove_flag(lv.obj.FLAG.SCROLLABLE)

        blk = lv.obj(c)
        blk.set_size(40, 40)
        blk.set_pos(14, 16)
        blk.set_style_bg_color(u.C(meta["accent"]), 0)
        blk.set_style_radius(8, 0)
        blk.set_style_border_width(0, 0)
        blk.set_style_pad_all(0, 0)
        blk.remove_flag(lv.obj.FLAG.SCROLLABLE)
        ic = u.mk_icon(blk, meta["icon"], 0, 0, 0xFFFFFF)
        if ic is not None:
            ic.align(lv.ALIGN.CENTER, 0, 0)
        num = u.mk_label(c, "{:02d}".format(meta["order"]), 0, 0, u.TEXT3, u.F_NUM_S)
        num.align(lv.ALIGN.TOP_RIGHT, -8, 8)

        u.mk_label(c, meta["title"], 14, 68, u.TEXT, u.ZH)
        u.mk_label(c, meta["desc"], 14, 92, u.TEXT3, u.ZH)
        cards.append(c)

    n = len(cards)
    x0 = (u.W - (n * 8 + (n - 1) * 6)) // 2
    for i in range(n):
        d = lv.obj(scr)
        d.set_size(8, 8)
        d.set_pos(x0 + i * 14, 200)
        d.set_style_radius(4, 0)
        d.set_style_bg_color(u.C(0xDADCE0), 0)
        d.set_style_border_width(0, 0)

    _layout()
    return scr


def _layout():
    n = len(cards)
    for i, c in enumerate(cards):
        rel = ((i - _focus + n + n // 2) % n) - n // 2
        x = CX + rel * STRIDE
        foc = rel == 0
        c.set_pos(x, FOCUS_Y if foc else IDLE_Y)
        c.set_style_opa(255 if foc else 160, 0)
        c.set_style_border_color(u.C(u.PRIMARY if foc else u.BORDER), 0)
        c.set_style_border_width(2 if foc else 1, 0)


def on_enc(d):
    global _focus
    n = len(cards)
    if n == 0:
        return
    _focus = (_focus + d) % n
    _layout()


def on_confirm():
    metas = ordered()
    if not metas:
        return None
    target = metas[_focus]["id"]
    print("[launcher] enter", target)
    return target


def on_exit():
    return False


def update(run):
    pass
