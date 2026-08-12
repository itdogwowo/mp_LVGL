# ui/lvgl/launcher.py — 動態首頁(讀 registry 產生卡片)
#
# 橫屏 320×240 佈局:卡片橫向輪播(旋鈕左右選,按下確認)。
# 對齊 mp_LVGL/ui/lvgl_ui_launcher.py 的輪播風格。
import lvgl as lv
from ui.lvgl.registry import ordered
from ui.lvgl import ui_common as u

_ANIM = getattr(lv, "anim_t", None)
_EASE = getattr(lv, "anim_path_ease_out", None)

scr = None
cards = []
dots = []
_focus = 0
_mounted = False

CARD_W = 160
CARD_H = 140
CX = 0
STRIDE = 176
FOCUS_Y = 48
IDLE_Y = 56


def _slide_to(wid, x, y, time_ms=260, delay_ms=0):
    """單一 exec callback 同時更新 x/y,避免內容與邊框分離。"""
    sx, sy = wid.get_x(), wid.get_y()
    if _ANIM is None or (sx == x and sy == y):
        wid.set_pos(x, y)
        return None
    a = _ANIM()
    try:
        a.init()
    except Exception:
        pass
    a.set_var(wid)
    a.set_values(0, 1000)
    a.set_duration(time_ms)
    a.set_delay(delay_ms)
    if _EASE is not None:
        try:
            a.set_path_cb(_EASE)
        except Exception:
            pass

    def _exec(_a, v, _w=wid, _sx=sx, _sy=sy, _tx=x, _ty=y):
        k = v / 1000.0
        _w.set_pos(int(_sx + (_tx - _sx) * k), int(_sy + (_ty - _sy) * k))

    a.set_custom_exec_cb(_exec)
    a.start()
    return a


def build():
    global scr, cards, dots, _focus, CX, _mounted
    _focus = 0
    _mounted = False
    CX = (u.W - CARD_W) // 2
    scr = lv.obj(None)
    scr.set_style_bg_color(u.C(u.BG), 0)
    title = u.mk_label(scr, "選擇功能", 0, 8, u.TEXT, u.ZH)
    title.align(lv.ALIGN.TOP_MID, 0, 8)
    sub = u.mk_label(scr, "旋鈕切換 · 按下確認", 0, 28, u.TEXT3, u.ZH)
    sub.align(lv.ALIGN.TOP_MID, 0, 28)

    metas = ordered()
    cards = []
    for meta in metas:
        c = lv.obj(scr)
        c.set_size(CARD_W, CARD_H)
        c.set_style_bg_color(u.C(u.SURFACE), 0)
        c.set_style_radius(12, 0)
        c.set_style_border_color(u.C(u.BORDER), 0)
        c.set_style_border_width(1, 0)
        c.set_style_pad_all(0, 0)
        # 縮放 pivot 置中(聚焦 100% / 非聚焦 94%,HTML 卡片同款)
        c.set_style_transform_pivot_x(CARD_W // 2, 0)
        c.set_style_transform_pivot_y(CARD_H // 2, 0)
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

    # 分頁指示點
    n = len(cards)
    x0 = (u.W - (n * 8 + (n - 1) * 6)) // 2
    dots = []
    for i in range(n):
        d = lv.obj(scr)
        d.set_size(8, 8)
        d.set_pos(x0 + i * 14, u.H - 40)
        d.set_style_radius(4, 0)
        d.set_style_bg_color(u.C(0xDADCE0), 0)
        d.set_style_border_width(0, 0)
        dots.append(d)

    _layout(False)
    _mounted = True
    return scr


def _layout(animated=True):
    """輪播佈局:位置/透明度/縮放/邊框 300ms ease-out 過渡,
    依與焦點的距離階梯延遲(30ms/步,對齊 HTML 卡片逐張滑入)。"""
    n = len(cards)
    for i, c in enumerate(cards):
        rel = ((i - _focus + n + n // 2) % n) - n // 2
        x = CX + rel * STRIDE
        foc = rel == 0
        delay = min(60, abs(rel) * 30)
        y = FOCUS_Y if foc else IDLE_Y
        border = u.PRIMARY if foc else u.BORDER
        if animated:
            u.cancel(c)
            _slide_to(c, x, y, 280, delay)
            u.opa_to(c, 255 if foc else 160, 300, delay)
            u.scale_to(c, 100 if foc else 94, 300, delay)
            u.border_width_to(c, 2 if foc else 1, 260, delay)
            u.color_anim(c, lambda col, _c=c: _c.set_style_border_color(col, 0),
                         u.PRIMARY if foc else u.BORDER,
                         u.BORDER if foc else u.PRIMARY,
                         260, delay)
        else:
            c.set_pos(x, y)
            c.set_style_opa(255 if foc else 160, 0)
            c.set_style_border_width(2 if foc else 1, 0)
            c.set_style_border_color(u.C(border), 0)
            scale_setter = getattr(c, "set_style_transform_scale", None)
            if scale_setter is not None:
                scale_setter(int((100 if foc else 94) * 2.56), 0)
        if foc:
            c.move_foreground()
    for di, d in enumerate(dots):
        if animated:
            u.cancel(d)
            u.color_anim(d, lambda col, _d=d: _d.set_style_bg_color(col, 0),
                         0xDADCE0 if di == _focus else u.PRIMARY,
                         u.PRIMARY if di == _focus else 0xDADCE0,
                         260, 0)
        else:
            d.set_style_bg_color(u.C(u.PRIMARY if di == _focus else 0xDADCE0), 0)


def on_enc(d):
    global _focus
    n = len(cards)
    if n == 0:
        return
    _focus = (_focus + d) % n
    _layout(_mounted)


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
